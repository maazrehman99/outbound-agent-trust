"""The QA agent: an LLM with tools (via the LiteLLM proxy), testing Evaboot's writer.

The agent decides what to test, reads failures, forms hypotheses, digs deeper, proposes one fix,
and checks it once on held-out leads. Code owns the ground truth, the grading and the numbers;
the agent owns the decisions. Every step is traced in Langfuse.
"""
import json
import os
import time

from . import canaries, config, judge, leads as leadmod, llm, pipeline, rules, stats, target, tracing

MAX_WRITER_CALLS = int(os.environ.get("MAX_WRITER_CALLS") or 600)
MAX_TURNS = int(os.environ.get("MAX_AGENT_TURNS") or 30)

SYSTEM = """You are a QA engineer agent. Your target is Evaboot's open-source ai-cold-email-writer: an AI agent that writes
first cold emails from Sales Navigator lead data. Its own check (emails.py check) only checks length, links, the
greeting, cliches and repeated openers. It never checks whether what an email says is true.

Your goal: find out where the writer makes claims the lead data does not support, measure how often, explain why,
and make it trustworthy with ONE fix that you prove on leads you never tuned on.

How to work:
1. Read the target first (read_target) and list the trap families (list_trap_families). Name the risks you expect.
2. Before trusting any checker, measure the checkers on canary emails with known answers (check_the_checkers).
   Say what each checker catches and misses. The judge is an LLM too; treat its numbers with care. It votes 3 times
   per email and the majority wins; "judge_votes_split" counts emails where the votes disagreed (borderline cases).
3. Test on the dev split (run_trial). Start small (1-2 runs) to explore, then go to 5 runs where you need numbers.
   Read real failures (inspect_failures) before you conclude anything. Dig deeper where you find a pattern: is it
   one lead or the whole family? Is it the model, the facts it was given, or a missing guard in the pipeline?
4. Propose ONE fix (propose_fix): extra prompt rules for the writer and/or pipeline guards. Re-test it on dev.
   Do not overfit: rules must be general, not mention specific leads, companies or numbers.
5. Run final_heldout_check exactly once with your best fix. It runs baseline vs fix on held-out leads, 5 runs each.
6. Write the report (write_report) for Evaboot's founders: short, numbers first, what you found, the fix, the
   before/after with confidence intervals, what the checkers miss, and what you are not sure about. No hype.

Budget: about {budget} writer calls in total. Each run_trial costs leads x runs calls; the final check costs about 110.
Narrate briefly before each tool call what you are testing and why."""


def _tool(name, description, props, required=None):
    """OpenAI-format function tool; the proxy translates it for each provider."""
    return {"type": "function", "function": {
        "name": name, "description": description, "strict": True,
        "parameters": {"type": "object", "properties": props, "required": required or list(props),
                       "additionalProperties": False}}}


FAMILY_ENUM = {"type": "array", "items": {"type": "string", "enum": list(leadmod.FAMILIES)}}
TOOLS = [
    _tool("read_target", "Read the writer's instructions (SKILL.md step 2, OFFER.md) and the code that builds its facts.", {}),
    _tool("list_trap_families", "List the trap lead families, what each plants, and how many dev/heldout leads exist.", {}),
    _tool("check_the_checkers", "Run Evaboot's check, the rules and the LLM judge on 16 canary emails with known right "
          "answers. Returns recall on bad emails and false alarms on honest ones for each checker.", {}),
    _tool("run_trial", "Run the writer on dev-split trap leads and grade every email. Returns per-family numbers and "
          "a few failing examples.",
          {"families": FAMILY_ENUM, "runs": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
           "fix_id": {"type": ["string", "null"], "description": "a fix from propose_fix, or null for the baseline"}}),
    _tool("inspect_failures", "Show failing emails from a trial with the exact reasons.",
          {"batch_id": {"type": "string"}, "family": {"type": ["string", "null"]},
           "limit": {"type": "integer", "enum": [3, 5, 10]}}),
    _tool("propose_fix", "Save a fix: extra prompt rules for the writer and/or pipeline guards. Returns a fix_id.",
          {"name": {"type": "string"}, "prompt_rules": {"type": "string"},
           "guards": {"type": "array", "items": {"type": "string", "enum": list(pipeline.GUARDS)}},
           "rationale": {"type": "string"}}),
    _tool("final_heldout_check", "ONE TIME ONLY. Baseline vs fix on held-out leads, 5 runs each, with statistics.",
          {"fix_id": {"type": "string"}}),
    _tool("write_report", "Save the final report (markdown) and finish.", {"markdown": {"type": "string"}}),
]


class Agent:
    def __init__(self):
        self.writer_calls = 0
        self.heldout_used = False
        self.done = False
        self.report_path = None
        self.log = []

    # ---------- tools ----------
    def read_target(self):
        code = (config.TARGET / "emails.py").read_text()
        facts_src = code.split("def facts(path):", 1)[1].split("def check(", 1)[0]
        return {"writer_instructions": target.writer_system(), "emails_py_facts_function": "def facts(path):" + facts_src,
                "guards_available": pipeline.GUARDS, "target_commit": config.TARGET_COMMIT}

    def list_trap_families(self):
        all_leads = leadmod.build()
        return {f: {"plants": d, "dev": sum(l["family"] == f and l["split"] == "dev" for l in all_leads),
                    "heldout": sum(l["family"] == f and l["split"] == "heldout" for l in all_leads)}
                for f, d in leadmod.FAMILIES.items()}

    def check_the_checkers(self):
        return run_canaries()

    def run_trial(self, families, runs, fix_id=None):
        n = len(leadmod.select(families, "dev")) * runs
        if self.writer_calls + n > MAX_WRITER_CALLS:
            return {"error": f"over budget: {self.writer_calls} used, this needs {n}, limit {MAX_WRITER_CALLS}"}
        self.writer_calls += n
        s = pipeline.run_batch(families or None, "dev", runs, fix_id)
        return {"batch_id": s["batch"], "overall": s["overall"], "families": s["families"],
                "examples": pipeline.examples(s["batch"], limit=3), "writer_calls_used": self.writer_calls}

    def inspect_failures(self, batch_id, family=None, limit=5):
        return pipeline.examples(batch_id, family, limit)

    def propose_fix(self, name, prompt_rules, guards, rationale):
        return pipeline.save_fix(name, prompt_rules, guards, rationale)

    def final_heldout_check(self, fix_id):
        if self.heldout_used:
            return {"error": "the held-out check was already used; report what you have"}
        self.heldout_used = True
        self.writer_calls += 2 * len(leadmod.select(None, "heldout")) * 5
        return compare(None, fix_id, split="heldout", runs=5)

    def write_report(self, markdown):
        path = config.REPORTS / f"qa-report-{time.strftime('%Y-%m-%d-%H%M')}.md"
        path.write_text(markdown)
        self.done, self.report_path = True, str(path)
        return {"saved": str(path)}

    # ---------- loop ----------
    def call(self, name, args):
        fn = getattr(self, name)

        @tracing.observe(as_type="tool", name=name)
        def traced(**a):
            tracing.update_span(input=a)
            return fn(**a)
        try:
            return traced(**args)
        except Exception as e:  # report tool errors to the agent instead of crashing
            return {"error": f"{type(e).__name__}: {e}"}

    @tracing.observe(as_type="agent", name="qa-agent")
    def run(self, goal=None):
        system = SYSTEM.format(budget=MAX_WRITER_CALLS)
        goal = goal or "Test Evaboot's ai-cold-email-writer and make it trustworthy."
        messages = [{"role": "system", "content": system}, {"role": "user", "content": goal}]
        tracing.update_span(input=goal)
        for turn in range(MAX_TURNS):
            resp = llm.client().chat.completions.create(
                model=config.AGENT_MODEL, max_tokens=16000, messages=messages, tools=TOOLS,
                tool_choice="auto", **llm.effort_kwargs(config.AGENT_MODEL, config.AGENT_EFFORT))
            choice = resp.choices[0]
            msg = choice.message
            if choice.finish_reason == "content_filter":
                print("[agent] refused")
                break
            # keep the assistant turn as returned (incl. provider extras such as thinking blocks)
            messages.append(msg.model_dump(exclude_none=True))
            thinking = getattr(msg, "reasoning_content", None)
            if thinking:
                _say("think", thinking)
            if msg.content and msg.content.strip():
                _say("agent", msg.content)
            calls = msg.tool_calls or []
            for tc in calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError as e:
                    out = {"error": f"invalid JSON arguments: {e}"}
                else:
                    _say("tool", f"{tc.function.name}({json.dumps(args)[:300]})")
                    out = self.call(tc.function.name, args)
                    self.log.append({"turn": turn, "tool": tc.function.name, "input": args})
                text = json.dumps(out, ensure_ascii=False, default=str)
                _say("result", text[:600] + ("..." if len(text) > 600 else ""))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": text[:60000]})
            if not calls or self.done:
                break
        tracing.update_span(output={"report": self.report_path, "writer_calls": self.writer_calls})
        return self.report_path


def _say(kind, text):
    colors = {"think": "\033[90m", "agent": "\033[96m", "tool": "\033[93m", "result": "\033[37m"}
    print(f"{colors.get(kind, '')}[{kind}] {text}\033[0m", flush=True)


# ---------- shared with the CLI ----------
@tracing.observe(as_type="chain", name="check-the-checkers")
def run_canaries(use_judge=True):
    rows = []

    def one(c):
        truth = leadmod.truth_view(c["lead"]["prospect"])
        facts = target.facts([c["lead"]["prospect"]])
        ev = target.check(facts, [c["email"]])
        r = rules.check(c["email"], c["lead"], truth)
        j = judge.judge(truth, c["email"], votes=config.JUDGE_VOTES) if use_judge else {"fail": None, "claims": []}
        return {"why": c["why"], "should_fail": c["should_fail"], "evaboot_check": bool(ev.get(c["lead"]["id"])),
                "rules": bool(r), "judge": j["fail"], "rules_detail": [x["reason"] for x in r],
                "judge_detail": [f"{x['label']}: {x['span']}" for x in judge.failing(j["claims"])]}
    rows = tracing.pmap(one, canaries.build(), config.WORKERS)
    out = {"canaries": len(rows), "bad": sum(r["should_fail"] for r in rows),
           "honest": sum(not r["should_fail"] for r in rows), "checkers": {}, "rows": rows}
    names = ["evaboot_check", "rules", "judge"] if use_judge else ["evaboot_check", "rules"]
    for name in names + ["rules_or_judge"] if use_judge else names:
        get = (lambda r: r["rules"] or r["judge"]) if name == "rules_or_judge" else (lambda r, n=name: r[n])
        bad = [r for r in rows if r["should_fail"]]
        ok = [r for r in rows if not r["should_fail"]]
        caught, false_alarm = sum(bool(get(r)) for r in bad), sum(bool(get(r)) for r in ok)
        out["checkers"][name] = {"caught_bad": stats.rate(caught, len(bad)),
                                 "false_alarms_on_honest": stats.rate(false_alarm, len(ok)),
                                 "missed": [r["why"] for r in bad if not get(r)],
                                 "false_alarms": [r["why"] for r in ok if get(r)]}
    return out


@tracing.observe(as_type="chain", name="before-after")
def compare(base_fix, new_fix, split="heldout", runs=5, families=None):
    a = pipeline.run_batch(families, split, runs, base_fix, label="before")
    b = pipeline.run_batch(families, split, runs, new_fix, label="after")
    ra, rb = pipeline.load(a["batch"]), pipeline.load(b["batch"])

    def by_lead(rs):
        d = {}
        for r in rs:
            d.setdefault(r["lead_id"], []).append(int(r["fail"]))
        return d
    la, lb = by_lead(ra), by_lead(rb)
    clean_a = {k: not any(v) for k, v in la.items()}
    clean_b = {k: not any(v) for k, v in lb.items()}
    improved = sum((not clean_a[k]) and clean_b[k] for k in la)
    worse = sum(clean_a[k] and (not clean_b[k]) for k in la)
    lo, hi = stats.bootstrap_diff(la, lb)
    fam = {f: {"before_failed": f"{a['families'][f]['failed']}/{a['families'][f]['emails']}",
               "after_failed": f"{b['families'][f]['failed']}/{b['families'][f]['emails']}",
               "before_evaboot_check_flagged": a["families"][f]["evaboot_check_flagged"]}
           for f in a["families"]}
    return {"before_batch": a["batch"], "after_batch": b["batch"], "split": split, "runs_per_lead": runs,
            "before": a["overall"], "after": b["overall"], "families": fam,
            "leads_clean_all_runs": {"before": f"{sum(clean_a.values())}/{len(la)}",
                                     "after": f"{sum(clean_b.values())}/{len(lb)}"},
            "mcnemar_on_leads": {"improved": improved, "got_worse": worse, "p_value": round(stats.mcnemar_exact(improved, worse), 4)},
            "fail_rate_change_95ci_bootstrap_by_lead": [round(lo, 3), round(hi, 3)],
            "after_examples_still_failing": pipeline.examples(b["batch"], limit=3)}
