"""Run the writer on trap leads N times, grade every email three ways, store and summarise."""
import json
import time
import uuid
from collections import defaultdict

from . import config, judge, leads as leadmod, rules, stats, target, tracing

GUARDS = {
    "suppression_filter": "Skip any lead on the block list before writing (reads the Instantly block list).",
    "tenure_unknown": "Fix facts(): missing time-in-role stays unknown (null) instead of 0 months, so new_in_role "
                      "is only true when Has New Position is true or the real tenure is under 6 months.",
    "link_site_skip": "Skip any lead whose email_check says 'do not send' before the writer sees it.",
}


def load_fix(fix_id):
    if not fix_id:
        return None
    return json.loads((config.FIXES / f"{fix_id}.json").read_text())


def save_fix(name, prompt_rules="", guards=(), rationale=""):
    bad = [g for g in guards if g not in GUARDS]
    if bad:
        raise ValueError(f"unknown guards {bad}; choose from {list(GUARDS)}")
    fix_id = f"fix-{time.strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    fix = {"id": fix_id, "name": name, "prompt_rules": prompt_rules, "guards": list(guards), "rationale": rationale}
    (config.FIXES / f"{fix_id}.json").write_text(json.dumps(fix, indent=2))
    return fix


def _apply_fact_guards(facts, batch, fix):
    if not fix or "tenure_unknown" not in fix["guards"]:
        return facts
    by_id = {l["id"]: l for l in batch}
    for f in facts:
        t = leadmod.truth_view(by_id[f["id"]]["prospect"])
        f["months_in_role"] = t["months_in_role"]
        f["new_in_role"] = t["has_new_position_flag"] or (t["months_in_role"] is not None and t["months_in_role"] < 6)
    return facts


def _pre_skip(fact, lead, fix):
    if not fix:
        return None
    if "suppression_filter" in fix["guards"] and lead["suppressed"]:
        return {"id": fact["id"], "skip": True, "reason": "on the block list (unsubscribed)"}
    if "link_site_skip" in fix["guards"] and "do not send" in (fact.get("email_check") or ""):
        return {"id": fact["id"], "skip": True, "reason": fact["email_check"]}
    return None


@tracing.observe(name="lead-run")
def _one(args):
    fact, lead, fix, votes, run = args
    email = _pre_skip(fact, lead, fix) or target.write(fact, (fix or {}).get("prompt_rules", ""))
    truth = leadmod.truth_view(lead["prospect"])
    r = rules.check(email, lead, truth)
    j = judge.judge(truth, email, votes=votes)
    tracing.update_span(input={"lead": lead["id"], "family": lead["family"], "run": run},
                        output={"email": email, "rules": r, "judge_fail": j["fail"]})
    return email, r, j


@tracing.observe(as_type="chain", name="trial")
def run_batch(families=None, split="dev", runs=5, fix_id=None, votes=None, label=""):
    votes = votes or config.JUDGE_VOTES
    fix = load_fix(fix_id)
    batch = leadmod.select(families, split)
    if not batch:
        raise ValueError("no leads for that selection")
    batch_id = f"{time.strftime('%m%d-%H%M%S')}-{split}-{'fix' if fix else 'base'}-{uuid.uuid4().hex[:4]}"
    out_dir = config.RUNS / batch_id
    out_dir.mkdir(parents=True)
    tracing.update_span(input={"families": families, "split": split, "runs": runs, "fix": fix, "label": label})
    records = []
    with tracing.propagate_attributes(session_id=batch_id, tags=[split, "fix" if fix else "baseline"]):
        for run in range(runs):
            facts = _apply_fact_guards(target.facts([l["prospect"] for l in batch]), batch, fix)
            by_id = {l["id"]: l for l in batch}
            results = tracing.pmap(_one, [(f, by_id[f["id"]], fix, votes, run) for f in facts], config.WORKERS)
            emails = [e for e, _, _ in results]
            ev = target.check(facts, emails)
            for f, (email, r, j) in zip(facts, results):
                lead = by_id[f["id"]]
                skipped = bool(email.get("skip"))
                rec = {
                    "batch": batch_id, "run": run, "lead_id": lead["id"], "family": lead["family"],
                    "split": lead["split"], "note": lead["note"], "fix": fix["id"] if fix else None,
                    "facts": f, "email": email, "skipped": skipped,
                    "evaboot_problems": ev.get(f["id"], []),
                    "rules": r, "judge": j,
                    "fail_rules": bool(r), "fail_judge": j["fail"],
                    "should_skip": lead["expect_skip"],
                    "over_skip": skipped and lead["family"] == "clean",
                }
                rec["fail"] = rec["fail_rules"] or rec["fail_judge"] or (lead["expect_skip"] and not skipped)
                records.append(rec)
    with open(out_dir / "records.jsonl", "w") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    s = summarise(records)
    s.update({"batch": batch_id, "split": split, "runs": runs, "fix": fix, "selected_families": families,
              "trace_url": tracing.trace_url(), "writer_model": config.WRITER_MODEL, "judge_model": config.JUDGE_MODEL})
    (out_dir / "summary.json").write_text(json.dumps(s, indent=2))
    tracing.update_span(output=s["overall"])
    return s


def load(batch_id):
    return [json.loads(l) for l in open(config.RUNS / batch_id / "records.jsonl")]


def summarise(records):
    fam = defaultdict(list)
    for r in records:
        fam[r["family"]].append(r)
    per = {}
    for f, rs in sorted(fam.items()):
        by_lead = defaultdict(list)
        for r in rs:
            by_lead[r["lead_id"]].append(r)
        runs = len(next(iter(by_lead.values())))
        per[f] = {
            "emails": len(rs),
            "skipped": sum(r["skipped"] for r in rs),
            "evaboot_check_flagged": sum(bool(r["evaboot_problems"]) for r in rs),
            "rules_flagged": sum(r["fail_rules"] for r in rs),
            "judge_flagged": sum(r["fail_judge"] for r in rs),
            "failed": sum(r["fail"] for r in rs),
            "leads": len(by_lead),
            "leads_clean_all_runs": sum(all(not x["fail"] for x in v) for v in by_lead.values()),
            "pass_hat_k": round(sum(stats.pass_hat_k(sum(not x["fail"] for x in v), len(v), len(v))
                                    for v in by_lead.values()) / len(by_lead), 3),
            "runs_per_lead": runs,
        }
    n = len(records)
    failed = sum(r["fail"] for r in records)
    missed_by_evaboot = sum(r["fail"] and not r["evaboot_problems"] for r in records)
    overall = {
        "emails": n, "failed": failed, "fail_rate": stats.rate(failed, n),
        "failed_but_evaboot_check_passed": missed_by_evaboot,
        "rules_flagged": sum(r["fail_rules"] for r in records),
        "judge_flagged": sum(r["fail_judge"] for r in records),
        "over_skipped_clean": sum(r["over_skip"] for r in records),
        "judge_votes_split": sum(1 for r in records if r["judge"].get("votes", 0) > 1 and not r["judge"].get("unanimous", True)),
    }
    return {"overall": overall, "families": per}


def examples(batch_id, family=None, limit=5):
    """Failing emails with the reasons, for the agent and for the report."""
    out = []
    for r in load(batch_id):
        if not r["fail"] or (family and r["family"] != family):
            continue
        reasons = [f"rule {x['rule']}: {x['reason']} [{x['span']}]" for x in r["rules"]]
        reasons += [f"judge {c['label']}: \"{c['span']}\" - {c['reason']}" for c in judge.failing(r["judge"]["claims"])]
        if r["should_skip"] and not r["skipped"]:
            reasons.append(f"should have been skipped ({r['family']})")
        out.append({"lead": r["lead_id"], "family": r["family"], "run": r["run"], "note": r["note"],
                    "subject": r["email"].get("subject"), "body": r["email"].get("body"),
                    "evaboot_check": r["evaboot_problems"] or "PASS", "why_failed": reasons})
        if len(out) >= limit:
            break
    return out
