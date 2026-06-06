from __future__ import annotations

import asyncio
import csv
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from probe_cdn_ips import load_candidates, parse_statuses, run_probe, summarize, write_outputs


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
FRONTEND_DIST = ROOT / "webui" / "frontend" / "dist"


class ScanRequest(BaseModel):
    host: str = Field(min_length=1)
    path: str = "/cdn-cgi/trace"
    scheme: Literal["https", "http"] = "https"
    port: int = Field(default=443, ge=1, le=65535)
    candidates: str = "candidates/cloudflare_common.txt"
    sample_strategy: Literal["spread", "per-prefix"] = "spread"
    sample_per_cidr: int = Field(default=4, ge=1, le=256)
    per_prefix_len: int = Field(default=24, ge=0, le=128)
    sample_per_prefix: int = Field(default=1, ge=1, le=256)
    limit: int | None = Field(default=None, ge=1, le=5000)
    repeat: int = Field(default=3, ge=1, le=20)
    concurrency: int = Field(default=8, ge=1, le=128)
    connect_timeout: float = Field(default=3.0, gt=0, le=30)
    timeout: float = Field(default=6.0, gt=0, le=120)
    method: Literal["GET", "HEAD"] = "GET"
    http: Literal["auto", "h1", "h2", "h3"] = "h2"
    max_bytes: int = Field(default=4096, ge=0, le=10_000_000)
    ok_status: str = "200"
    top: int = Field(default=15, ge=1, le=100)

    @field_validator("path")
    @classmethod
    def path_starts_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            return f"/{value}"
        return value

    @field_validator("candidates")
    @classmethod
    def candidate_path_is_local(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("candidate path must stay inside the repository")
        return value


class ScanState(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    total: int = 0
    completed: int = 0
    ok: int = 0
    error: str = ""
    run_id: str | None = None
    result_dir: str | None = None
    best_ip: str | None = None
    rows: list[dict[str, object]] = Field(default_factory=list)
    request: ScanRequest


class DefaultsResponse(BaseModel):
    request: ScanRequest
    candidate_files: list[str]
    has_env: bool


@dataclass
class Job:
    state: ScanState
    results: list[object] = field(default_factory=list)


jobs: dict[str, Job] = {}
app = FastAPI(title="CDN IP Probe WebUI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        return {}

    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data


def candidate_files() -> list[str]:
    base = ROOT / "candidates"
    if not base.exists():
        return []
    return sorted(str(path.relative_to(ROOT)) for path in base.glob("*.txt"))


def defaults_from_env() -> ScanRequest:
    env = read_env()
    return ScanRequest(
        host=env.get("CDN_HOST", "cdn.example.com"),
        path=env.get("CDN_PATH", "/cdn-cgi/trace"),
        repeat=int(env.get("REPEAT", "3")),
        concurrency=int(env.get("CONCURRENCY", "8")),
        ok_status=env.get("OK_STATUS", "200"),
        http=env.get("HTTP_VERSION", "h2"),
        limit=int(env["LIMIT"]) if env.get("LIMIT") else None,
    )


def namespace_from_request(req: ScanRequest):
    class Args:
        pass

    args = Args()
    for key, value in req.model_dump().items():
        setattr(args, key, value)
    args.candidates = (ROOT / req.candidates).resolve()
    args.out_dir = RESULTS_DIR.resolve()
    return args


def read_tsv(path: Path, limit: int | None = None) -> list[dict[str, object]]:
    if not path.exists():
        return []

    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")
        for row in reader:
            rows.append(dict(row))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def read_run(run_id: str) -> dict[str, object]:
    run_dir = RESULTS_DIR / run_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="result run not found")

    best_path = run_dir / "best_ip.txt"
    hint_path = run_dir / "connection_hint.json"
    hint = json.loads(hint_path.read_text(encoding="utf-8")) if hint_path.exists() else None
    return {
        "run_id": run_id,
        "summary": read_tsv(run_dir / "summary.tsv"),
        "raw": read_tsv(run_dir / "raw.tsv", limit=500),
        "best_ip": best_path.read_text(encoding="utf-8").strip() if best_path.exists() else None,
        "hint": hint,
        "files": sorted(path.name for path in run_dir.iterdir() if path.is_file()),
    }


async def execute_scan(job: Job) -> None:
    state = job.state
    state.status = "running"
    state.started_at = time.time()

    try:
        args = namespace_from_request(state.request)
        candidates = load_candidates(args)
        if not candidates:
            raise ValueError(f"no candidates loaded from {state.request.candidates}")

        ok_statuses = parse_statuses(state.request.ok_status)
        sem = asyncio.Semaphore(state.request.concurrency)
        tasks = [
            asyncio.create_task(run_probe(candidate, attempt, args, ok_statuses, sem))
            for candidate in candidates
            for attempt in range(1, state.request.repeat + 1)
        ]
        state.total = len(tasks)

        for task in asyncio.as_completed(tasks):
            result = await task
            job.results.append(result)
            state.completed += 1
            if result.ok:
                state.ok += 1

        rows = summarize(candidates, job.results)  # type: ignore[arg-type]
        run_dir = write_outputs(args.out_dir, state.request.host, state.request.port, rows, job.results)  # type: ignore[arg-type]
        state.rows = rows[: state.request.top]
        state.run_id = run_dir.name
        state.result_dir = str(run_dir.relative_to(ROOT))
        state.best_ip = str(rows[0]["ip"]) if rows and float(rows[0]["success_rate"]) > 0 else None
        state.status = "done"
    except (OSError, ValueError) as exc:
        state.status = "failed"
        state.error = str(exc)
    finally:
        state.finished_at = time.time()


@app.get("/api/defaults", response_model=DefaultsResponse)
def get_defaults() -> DefaultsResponse:
    return DefaultsResponse(
        request=defaults_from_env(),
        candidate_files=candidate_files(),
        has_env=(ROOT / ".env").exists(),
    )


@app.post("/api/scans", response_model=ScanState)
async def start_scan(req: ScanRequest) -> ScanState:
    path = (ROOT / req.candidates).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="candidate path must stay inside the repository") from exc
    if not path.exists():
        raise HTTPException(status_code=400, detail="candidate file does not exist")

    scan_id = uuid.uuid4().hex[:12]
    state = ScanState(id=scan_id, status="queued", created_at=time.time(), request=req)
    job = Job(state=state)
    jobs[scan_id] = job
    asyncio.create_task(execute_scan(job))
    return state


@app.get("/api/scans/{scan_id}", response_model=ScanState)
def get_scan(scan_id: str) -> ScanState:
    job = jobs.get(scan_id)
    if job is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return job.state


@app.get("/api/results")
def list_results() -> list[dict[str, object]]:
    if not RESULTS_DIR.exists():
        return []

    items: list[dict[str, object]] = []
    for run_dir in sorted((path for path in RESULTS_DIR.iterdir() if path.is_dir()), reverse=True):
        best_path = run_dir / "best_ip.txt"
        summary = read_tsv(run_dir / "summary.tsv", limit=1)
        items.append(
            {
                "run_id": run_dir.name,
                "best_ip": best_path.read_text(encoding="utf-8").strip()
                if best_path.exists()
                else None,
                "top": summary[0] if summary else None,
            }
        )
    return items


@app.get("/api/results/{run_id}")
def get_result(run_id: str) -> dict[str, object]:
    return read_run(run_id)


@app.get("/api/results/{run_id}/files/{name}")
def download_result_file(run_id: str, name: str) -> FileResponse:
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="bad file name")
    path = RESULTS_DIR / run_id / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
