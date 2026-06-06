# WebUI Summary

## Scope

- Added a local Vue WebUI for configuring and launching CDN IP scans.
- Added a FastAPI wrapper that reuses the existing probe functions instead of duplicating scan logic.
- Kept scan outputs compatible with the CLI layout under `results/YYYYMMDD-HHMMSS/`.

## Verification Targets

- Python syntax and style: `uv run ruff check .`
- Backend import/API smoke: `uv run python -m compileall probe_cdn_ips.py webui/server.py`
- Frontend build: `cd webui/frontend && npm run build`

## Files

- `webui/server.py`: local API, scan jobs, result readers, frontend static mount.
- `webui/frontend/src/App.vue`: Vue scan dashboard.
- `run_webui.sh`: starts the API and Vite dev server.
- `pyproject.toml`: Python dependencies and Ruff config.
