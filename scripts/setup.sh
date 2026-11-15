#!/usr/bin/env bash
# Clone Evaboot's writer at the exact commit this project tests, and install dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."
COMMIT=1667849a14d13a409d28d9ef3ee85b7018bf7d3d
if [ ! -d vendor/ai-cold-email-writer ]; then
  mkdir -p vendor && git clone -q https://github.com/evaboot-labs/ai-cold-email-writer.git vendor/ai-cold-email-writer
fi
git -C vendor/ai-cold-email-writer checkout -q "$COMMIT"
[ -d .venv ] || uv venv -q .venv
uv pip install -q --python .venv/bin/python -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "ready: put your personal ANTHROPIC_API_KEY (and a LITELLM_MASTER_KEY) in .env, run scripts/proxy.sh in one terminal, then: .venv/bin/python -m trust canary"
