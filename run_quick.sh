#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${CDN_HOST:?set CDN_HOST or create .env from .env.example}"
CDN_PATH="${CDN_PATH:-/cdn-cgi/trace}"

python ./probe_cdn_ips.py \
  --host "$CDN_HOST" \
  --path "$CDN_PATH" \
  --candidates candidates/cloudflare_common.txt \
  --repeat "${REPEAT:-3}" \
  --concurrency "${CONCURRENCY:-8}" \
  --http "${HTTP_VERSION:-h2}" \
  --ok-status "${OK_STATUS:-200}"
