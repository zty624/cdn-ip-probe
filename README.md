# CDN IP Probe

A small local probe for comparing CDN edge IP candidates for one hostname.

The probe keeps the request hostname unchanged while forcing the TCP connection
to a candidate IP. This is useful when you want to compare edge reachability and
latency without changing the hostname used for TLS SNI or HTTP Host.

## Repository Map

- `probe_cdn_ips.py`: CLI and core probe logic.
- `webui/server.py`: local FastAPI API for scan jobs and saved results.
- `webui/frontend/`: Vue/Vite dashboard.
- `candidates/`: public or example candidate IP lists.
- `results/`: generated scan outputs; only `results/.gitkeep` is tracked.
- `tests/`: unit tests for probe helper behavior.
- `docs/`: maintenance notes and WebUI summaries.

## Setup

Private targets live in `.env`, which is ignored by git.

```bash
cp .env.example .env
$EDITOR .env
```

Minimum config:

```bash
CDN_HOST=cdn.example.com
CDN_PATH=/cdn-cgi/trace
```

## Run

Quick probe:

```bash
./run_quick.sh
```

Broader candidate scan:

```bash
./run_broad.sh
```

WebUI:

```bash
uv sync
cd webui/frontend && npm install && cd ../..
./run_webui.sh
```

Use `WEBUI_PORT` or `VITE_PORT` when the default ports are already occupied:

```bash
WEBUI_PORT=8783 VITE_PORT=5173 ./run_webui.sh
```

Open:

```text
http://127.0.0.1:5173
```

## Verify

Run the local checks before committing behavior changes:

```bash
uv run ruff check .
uv run python -m unittest discover -s tests -v
uv run python -m compileall probe_cdn_ips.py webui/server.py
cd webui/frontend && npm run build
```

Results are written under:

```text
results/YYYYMMDD-HHMMSS/
```

If more than one run writes in the same second, later runs use suffixed
directories such as `results/YYYYMMDD-HHMMSS-02/`.

Useful files:

- `summary.tsv`: ranked summary
- `raw.tsv`: per-attempt curl timings
- `best_ip.txt`: top candidate from that run
- `best_resolve.txt`: `host:port:ip` tuple for reproducing with curl
- `connection_hint.json`: generic connection fields to copy into a client config

## Manual Examples

Small seed list:

```bash
python ./probe_cdn_ips.py \
  --host cdn.example.com \
  --path /cdn-cgi/trace \
  --candidates candidates/cloudflare_common.txt \
  --repeat 3 \
  --concurrency 8 \
  --http h2 \
  --ok-status 200
```

Broader `/24` sampling:

```bash
python ./probe_cdn_ips.py \
  --host cdn.example.com \
  --path /cdn-cgi/trace \
  --candidates candidates/xiu2_cloudflare_ipv4.txt \
  --sample-strategy per-prefix \
  --per-prefix-len 24 \
  --sample-per-prefix 1 \
  --limit 300 \
  --repeat 2 \
  --concurrency 8
```

Custom candidate list:

```bash
python ./probe_cdn_ips.py \
  --host cdn.example.com \
  --candidates candidates/manual.example.txt \
  --repeat 5
```

## Notes

- The probe clears common proxy environment variables and passes `--noproxy '*'`
  to curl so local proxy settings do not distort direct measurements.
- Keep `repeat`, `concurrency`, and `limit` modest. This is for edge comparison,
  not load testing.
- `cloudflare_ipv4.txt` is based on Cloudflare's published IP ranges.
- `xiu2_cloudflare_ipv4.txt` is based on the default IPv4 seed list from
  XIU2/CloudflareSpeedTest.

## WebUI API

The WebUI starts a local FastAPI server on `127.0.0.1:${WEBUI_PORT:-8765}` and
a Vite dev server on `127.0.0.1:${VITE_PORT:-5173}`. The Vite proxy reads the
same `WEBUI_PORT`, so changing the backend port keeps `/api` requests aligned.

Main endpoints:

- `GET /api/defaults`: load `.env` defaults and candidate files
- `POST /api/scans`: start a scan
- `GET /api/scans/{id}`: poll scan status
- `GET /api/results`: list previous runs
- `GET /api/results/{run_id}`: load summary, raw rows, and connection hint
