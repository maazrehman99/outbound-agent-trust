"""Drive Evaboot's ai-cold-email-writer as it ships.

- facts: their own `emails.py facts` turns the export into facts.json (bugs included).
- write: Claude gets their SKILL.md step 2 and OFFER.md as instructions and one lead's facts, and
  returns their emails.json entry shape. In the real product the user's coding agent does this step;
  here it is one API call per lead on the model their n8n workflow pins.
- check: their own `emails.py check` on the batch, as the baseline.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from . import config, llm, tracing

EMAILS_PY = config.TARGET / "emails.py"


class EmailOut(BaseModel):
    id: str
    skip: bool = Field(description="true if this lead should be skipped")
    reason: Optional[str] = Field(default=None, description="why skipped; null when not skipped")
    hook: Optional[str] = Field(default=None, description="the fact the email rests on, in a few words")
    subject: Optional[str] = None
    body: Optional[str] = None


def _run(args):
    # -I: isolated mode, so nothing from the vendored folder is imported implicitly.
    return subprocess.run([sys.executable, "-I", str(EMAILS_PY), *args], capture_output=True, text=True)


def facts(prospects):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "export.json"
        p.write_text(json.dumps({"prospects": prospects}))
        r = _run(["facts", str(p)])
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def check(facts_list, emails):
    """Their check on a batch. Returns {lead_id: [problems]} plus batch-level problems under '_batch'."""
    with tempfile.TemporaryDirectory() as d:
        fp, ep = Path(d) / "facts.json", Path(d) / "emails.json"
        fp.write_text(json.dumps(facts_list))
        ep.write_text(json.dumps(emails))
        r = _run(["check", str(fp), str(ep)])
    by_name = {f["name"]: f["id"] for f in facts_list}
    out = {f["id"]: [] for f in facts_list}
    out["_batch"] = []
    for line in r.stdout.splitlines():
        if not line.startswith("FAIL "):
            continue
        msg = line[5:]
        name = msg.split(":", 1)[0]
        if name in by_name:
            out[by_name[name]].append(msg)
        elif msg.startswith("no email for "):
            n = msg[len("no email for "):]
            out.setdefault(by_name.get(n, "_batch"), []).append(msg)
        else:
            out["_batch"].append(msg)
    return out


def _skill_step2():
    text = (config.TARGET / "skills" / "ai-cold-emails" / "SKILL.md").read_text()
    rules = text.split("## Rules", 1)[1].split("## Step 0", 1)[0]
    step2 = text.split("## Step 2: write the emails", 1)[1].split("## Step 3", 1)[0]
    step2 = re.sub(r"```bash.*?```", "", step2, flags=re.S)
    return "## Rules\n" + rules.strip() + "\n\n## Step 2: write the emails\n" + step2.strip()


def writer_system(extra_rules=""):
    offer = (config.TARGET / "OFFER.md").read_text()
    s = ("You are the AI cold email agent from the ai-cold-email-writer repo. Follow these instructions "
         "exactly. You are given ONE lead from queue/facts.json; return that lead's queue/emails.json entry.\n\n"
         + _skill_step2() + "\n\n# OFFER.md\n\n" + offer)
    if extra_rules:
        s += "\n\n# Extra rules (added by the fix under test)\n\n" + extra_rules.strip()
    return s


@tracing.observe(as_type="agent", name="evaboot-writer")
def write(fact, extra_rules=""):
    if config.MOCK:
        from .mock import mock_write
        return mock_write(fact)
    out, _ = llm.structured(model=config.WRITER_MODEL, system=writer_system(extra_rules),
                            user="Lead from queue/facts.json:\n" + json.dumps(fact, indent=2, ensure_ascii=False),
                            schema=EmailOut, effort=config.WRITER_EFFORT, max_tokens=8000, label="writer")
    e = out.model_dump()
    e["id"] = fact["id"]
    if e["skip"]:
        return {"id": e["id"], "skip": True, "reason": e.get("reason") or ""}
    return {k: e.get(k) or "" for k in ("id", "hook", "subject", "body")}
