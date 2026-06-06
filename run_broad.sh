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
  --candidates candidates/xiu2_cloudflare_ipv4.txt \
  --sample-strategy per-prefix \
  --per-prefix-len "${PER_PREFIX_LEN:-24}" \
  --sample-per-prefix "${SAMPLE_PER_PREFIX:-1}" \
  --limit "${LIMIT:-300}" \
  --repeat "${REPEAT:-5}" \
  --concurrency "${CONCURRENCY:-16}" \
  --http "${HTTP_VERSION:-h2}" \
  --ok-status "${OK_STATUS:-200}"
