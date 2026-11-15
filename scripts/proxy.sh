#!/usr/bin/env bash
# Start your own LiteLLM proxy on localhost:4000 with the keys from .env. Leave it running in its own terminal.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
exec .venv/bin/litellm --config litellm/config.yaml --host 127.0.0.1 --port "${LITELLM_PORT:-4000}"
