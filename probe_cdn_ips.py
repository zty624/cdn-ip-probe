#!/usr/bin/env python3
"""Rank CDN edge IPs for a domain by forcing curl to connect to each IP.

The probe keeps the URL hostname unchanged and uses curl --resolve, so TLS SNI
and Host remain the CDN domain while the TCP connection goes to a candidate IP.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import ipaddress
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CURL_WRITE_OUT = (
    '{"remote_ip":"%{remote_ip}",'
    '"http_version":"%{http_version}",'
    '"http_code":%{http_code},'
    '"time_connect":%{time_connect},'
    '"time_appconnect":%{time_appconnect},'
    '"time_starttransfer":%{time_starttransfer},'
    '"time_total":%{time_total},'
    '"speed_download":%{speed_download},'
    '"size_download":%{size_download}}'
)


@dataclass(frozen=True)
class Candidate:
    ip: str
    source: str


@dataclass(frozen=True)
class ProbeResult:
    ip: str
    attempt: int
    ok: bool
    code: int
    http_version: str
    connect_ms: float
    tls_ms: float
    ttfb_ms: float
    total_ms: float
    speed_bps: float
    size_bytes: float
    err: str


def clean_line(line: str) -> str:
    return line.split("#", 1)[0].strip()


def sample_spread(net: ipaddress._BaseNetwork, count: int) -> list[str]:
    if count <= 0:
        return []

    first = int(net.network_address)
    size = net.num_addresses
    if size == 1:
        return [str(net.network_address)]

    # Avoid IPv4 network/broadcast addresses for small manual ranges.
    start = first + 1 if net.version == 4 and size > 2 else first
    end = first + size - 2 if net.version == 4 and size > 2 else first + size - 1
    usable = max(1, end - start + 1)
    count = min(count, usable)
    step = usable / (count + 1)

    ips: list[str] = []
    for idx in range(1, count + 1):
        value = start + int(step * idx)
        ips.append(str(ipaddress.ip_address(value)))
    return ips


def sample_per_prefix(
    net: ipaddress._BaseNetwork,
    prefix_len: int,
    count: int,
    limit: int | None,
) -> list[str]:
    if count <= 0:
        return []
    if prefix_len < net.prefixlen:
        prefix_len = net.prefixlen
    if prefix_len > net.max_prefixlen:
        raise SystemExit(f"bad prefix length /{prefix_len} for {net}")

    ips: list[str] = []
    for sub in net.subnets(new_prefix=prefix_len):
        ips.extend(sample_spread(sub, count))
        if limit is not None and len(ips) >= limit:
            return ips[:limit]
    return ips


def load_candidates(args: argparse.Namespace) -> list[Candidate]:
    path = args.candidates
    seen: set[str] = set()
    candidates: list[Candidate] = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = clean_line(raw)
        if not line:
            continue
        for token in line.replace(",", " ").split():
            try:
                if "/" in token:
                    net = ipaddress.ip_network(token, strict=False)
                    remaining = None if args.limit is None else args.limit - len(candidates)
                    if remaining is not None and remaining <= 0:
                        return candidates
                    if args.sample_strategy == "spread":
                        ips = sample_spread(net, args.sample_per_cidr)
                    else:
                        ips = sample_per_prefix(
                            net,
                            args.per_prefix_len,
                            args.sample_per_prefix,
                            remaining,
                        )
                else:
                    ips = [str(ipaddress.ip_address(token))]
            except ValueError as exc:
                raise SystemExit(f"bad candidate entry {token!r} in {path}: {exc}") from exc

            for ip in ips:
                if ip in seen:
                    continue
                seen.add(ip)
                candidates.append(Candidate(ip=ip, source=token))
                if args.limit is not None and len(candidates) >= args.limit:
                    return candidates

    return candidates


def resolve_value(ip: str) -> str:
    addr = ipaddress.ip_address(ip)
    if addr.version == 6:
        return f"[{ip}]"
    return ip


def proxy_clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.lower() in {
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
        }:
            env.pop(key, None)
    return env


def parse_statuses(raw: str | None) -> set[int] | None:
    if not raw:
        return None
    statuses: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            statuses.update(range(int(start_s), int(end_s) + 1))
        else:
            statuses.add(int(part))
    return statuses


async def run_probe(
    candidate: Candidate,
    attempt: int,
    args: argparse.Namespace,
    ok_statuses: set[int] | None,
    sem: asyncio.Semaphore,
) -> ProbeResult:
    url = f"{args.scheme}://{args.host}:{args.port}{args.path}"
    resolve = f"{args.host}:{args.port}:{resolve_value(candidate.ip)}"
    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--output",
        "/dev/null",
        "--noproxy",
        "*",
        "--connect-timeout",
        str(args.connect_timeout),
        "--max-time",
        str(args.timeout),
        "--resolve",
        resolve,
        "--write-out",
        CURL_WRITE_OUT,
    ]

    if args.http == "h2":
        cmd.append("--http2")
    elif args.http == "h1":
        cmd.append("--http1.1")
    elif args.http == "h3":
        cmd.append("--http3")

    if args.method == "HEAD":
        cmd.append("--head")
    elif args.method != "GET":
        raise SystemExit(f"unsupported method: {args.method}")

    if args.max_bytes > 0:
        cmd.extend(["--range", f"0-{args.max_bytes - 1}"])

    cmd.append(url)

    async with sem:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proxy_clean_env(),
        )
        stdout, stderr = await proc.communicate()

    data: dict[str, object] = {}
    err = stderr.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        err = (err + " " + stdout.decode("utf-8", errors="replace")).strip()

    code = int(data.get("http_code") or 0)
    status_ok = code in ok_statuses if ok_statuses is not None else code > 0
    ok = proc.returncode == 0 and status_ok
    return ProbeResult(
        ip=candidate.ip,
        attempt=attempt,
        ok=ok,
        code=code,
        http_version=str(data.get("http_version") or ""),
        connect_ms=float(data.get("time_connect") or 0) * 1000,
        tls_ms=float(data.get("time_appconnect") or 0) * 1000,
        ttfb_ms=float(data.get("time_starttransfer") or 0) * 1000,
        total_ms=float(data.get("time_total") or 0) * 1000,
        speed_bps=float(data.get("speed_download") or 0),
        size_bytes=float(data.get("size_download") or 0),
        err=err,
    )


def median(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return statistics.median(values)


def summarize(candidates: list[Candidate], results: list[ProbeResult]) -> list[dict[str, object]]:
    by_ip: dict[str, list[ProbeResult]] = {}
    source_by_ip = {item.ip: item.source for item in candidates}
    for item in results:
        by_ip.setdefault(item.ip, []).append(item)

    rows: list[dict[str, object]] = []
    for ip, items in by_ip.items():
        oks = [item for item in items if item.ok]
        row = {
            "ip": ip,
            "source": source_by_ip.get(ip, ""),
            "attempts": len(items),
            "success": len(oks),
            "success_rate": len(oks) / len(items) if items else 0,
            "http_codes": ",".join(sorted({str(item.code) for item in items})),
            "http_versions": ",".join(sorted({item.http_version for item in items if item.http_version})),
            "connect_ms_p50": median(item.connect_ms for item in oks),
            "tls_ms_p50": median(item.tls_ms for item in oks),
            "ttfb_ms_p50": median(item.ttfb_ms for item in oks),
            "total_ms_p50": median(item.total_ms for item in oks),
            "speed_bps_avg": statistics.fmean(item.speed_bps for item in oks) if oks else 0,
            "last_error": next((item.err for item in reversed(items) if item.err), ""),
        }
        rows.append(row)

    rows.sort(
        key=lambda row: (
            -float(row["success_rate"]),
            float(row["total_ms_p50"]) or 999999,
            float(row["ttfb_ms_p50"]) or 999999,
            -float(row["speed_bps_avg"]),
        )
    )
    return rows


def write_outputs(
    out_dir: Path,
    host: str,
    port: int,
    rows: list[dict[str, object]],
    results: list[ProbeResult],
) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = out_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / "summary.tsv"
    with summary_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()) if rows else ["ip"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    raw_path = run_dir / "raw.tsv"
    with raw_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(ProbeResult.__dataclass_fields__), delimiter="\t")
        writer.writeheader()
        for item in results:
            writer.writerow(item.__dict__)

    if rows and float(rows[0]["success_rate"]) > 0:
        best_ip = str(rows[0]["ip"])
        (run_dir / "best_ip.txt").write_text(best_ip + "\n", encoding="utf-8")
        (run_dir / "best_resolve.txt").write_text(f"{host}:{port}:{resolve_value(best_ip)}\n", encoding="utf-8")
        hint = {
            "connect_address": best_ip,
            "keep_sni": host,
            "keep_host_header": host,
            "keep_port": port,
        }
        (run_dir / "connection_hint.json").write_text(json.dumps(hint, indent=2) + "\n", encoding="utf-8")

    return run_dir


def print_table(rows: list[dict[str, object]], top: int) -> None:
    if not rows:
        print("no results")
        return

    print("rank  ip                         ok    total  ttfb   tls    code  hver")
    for idx, row in enumerate(rows[:top], start=1):
        print(
            f"{idx:<5} "
            f"{str(row['ip']):<26} "
            f"{int(row['success']):>2}/{int(row['attempts']):<2} "
            f"{float(row['total_ms_p50']):>6.0f} "
            f"{float(row['ttfb_ms_p50']):>6.0f} "
            f"{float(row['tls_ms_p50']):>6.0f} "
            f"{str(row['http_codes']):<5} "
            f"{str(row['http_versions']):<4}"
        )


async def main_async(args: argparse.Namespace) -> int:
    candidates = load_candidates(args)
    if not candidates:
        print(f"no candidates loaded from {args.candidates}", file=sys.stderr)
        return 2

    ok_statuses = parse_statuses(args.ok_status)
    sem = asyncio.Semaphore(args.concurrency)
    tasks = [
        run_probe(candidate, attempt, args, ok_statuses, sem)
        for candidate in candidates
        for attempt in range(1, args.repeat + 1)
    ]

    print(
        f"probing {len(candidates)} IPs x {args.repeat} attempts "
        f"against {args.scheme}://{args.host}:{args.port}{args.path}"
    )
    results = await asyncio.gather(*tasks)
    rows = summarize(candidates, results)
    run_dir = write_outputs(args.out_dir, args.host, args.port, rows, results)
    print_table(rows, args.top)
    print(f"\nresults: {run_dir}")
    if rows and float(rows[0]["success_rate"]) > 0:
        print(f"best_ip: {rows[0]['ip']}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe and rank CDN preferred IPs for one hostname.")
    parser.add_argument("--host", required=True, help="CDN hostname, e.g. cdn.example.com")
    parser.add_argument("--path", default="/cdn-cgi/trace", help="HTTP path to probe")
    parser.add_argument("--scheme", choices=["https", "http"], default="https")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--candidates", type=Path, default=Path("candidates/cloudflare_ipv4.txt"))
    parser.add_argument("--out-dir", type=Path, default=Path("results"))
    parser.add_argument("--sample-per-cidr", type=int, default=4)
    parser.add_argument("--sample-strategy", choices=["spread", "per-prefix"], default="spread")
    parser.add_argument("--per-prefix-len", type=int, default=24)
    parser.add_argument("--sample-per-prefix", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="limit expanded candidate count")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--connect-timeout", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--method", choices=["GET", "HEAD"], default="GET")
    parser.add_argument("--http", choices=["auto", "h1", "h2", "h3"], default="h2")
    parser.add_argument("--max-bytes", type=int, default=4096)
    parser.add_argument("--ok-status", default="200", help="accepted status list/ranges, e.g. 200,204,301-399")
    parser.add_argument("--top", type=int, default=15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.candidates = args.candidates.expanduser().resolve()
    args.out_dir = args.out_dir.expanduser().resolve()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
