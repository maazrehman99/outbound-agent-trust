"""Paths, models and env loading. One place to change anything."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TARGET = ROOT / "vendor" / "ai-cold-email-writer"   # Evaboot's repo, pinned commit
TARGET_COMMIT = "1667849a14d13a409d28d9ef3ee85b7018bf7d3d"
_OUT = Path(os.environ["TRUST_OUT_DIR"]) if os.environ.get("TRUST_OUT_DIR") else ROOT   # tests write elsewhere
RUNS = _OUT / "runs"
FIXES = _OUT / "fixes"
REPORTS = _OUT / "reports"
DATA = ROOT / "data"

# All model calls go through a LiteLLM proxy (OpenAI-compatible). The code asks for aliases;
# litellm/config.yaml maps each alias to a provider and model, so nothing here is provider-specific.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or "http://127.0.0.1:4000"
LLM_API_KEY = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LLM_API_KEY") or ""
WRITER_MODEL = os.environ.get("WRITER_MODEL") or "writer"
JUDGE_MODEL = os.environ.get("JUDGE_MODEL") or "judge"
AGENT_MODEL = os.environ.get("AGENT_MODEL") or "agent"

WRITER_EFFORT = os.environ.get("WRITER_EFFORT") or "medium"
JUDGE_EFFORT = os.environ.get("JUDGE_EFFORT") or "medium"
AGENT_EFFORT = os.environ.get("AGENT_EFFORT") or "high"

# Models that need native adaptive thinking (Claude 5.x). Comma-separated substrings of the model name.
ADAPTIVE_HINTS = [h.strip() for h in (os.environ.get("ADAPTIVE_HINTS") or "opus-5,sonnet-5,fable-5,haiku-5").split(",")]

# The judge disagrees with itself on borderline claims; a majority of 3 votes per email is the default.
JUDGE_VOTES = int(os.environ.get("JUDGE_VOTES") or 3)

MOCK = os.environ.get("TRUST_MOCK") == "1"   # offline mode: no API calls, canned writer + judge
WORKERS = int(os.environ.get("TRUST_WORKERS") or 6)

for d in (RUNS, FIXES, REPORTS, DATA):
    d.mkdir(exist_ok=True)
