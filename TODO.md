# TODO

This file is the local driver for small, measurable repo work. Keep each item
verifiable with a command, file diff, or browser smoke.

## 2026-06-15 Repo Organization

- [x] Add unit tests for candidate expansion, status parsing, and same-second
  result output collisions.
- [x] Document the repository map, ignored artifact boundary, and verification
  commands.
- [x] Update `.gitignore` for common local test, cache, build, and log outputs.
- [ ] Add a single local check command or script that runs Python checks and
  frontend build together.
- [ ] Add browser-level WebUI smoke coverage for theme toggle, `/api` proxy
  alignment, and page-level horizontal overflow.
- [ ] Decide whether scan request defaults should live in a checked-in config
  file instead of only `.env` plus server defaults.

## Maintenance Rules

- Keep private probe targets in `.env`; only `.env.example` belongs in git.
- Keep generated scan outputs under `results/`; only `results/.gitkeep` belongs
  in git.
- After a visible WebUI behavior change, update `docs/webui.md` and run a
  desktop/mobile browser smoke.
- After a probe behavior change, add or update a unit test under `tests/`.
