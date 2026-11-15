"""CLI.

  python -m trust canary [--no-judge]            measure the checkers on canary emails
  python -m trust trial [--split dev] [--runs 5] [--families a,b] [--fix FIX_ID]
  python -m trust fix --name N [--rules FILE] [--guards g1,g2]
  python -m trust compare --fix FIX_ID [--split heldout] [--runs 5]
  python -m trust agent                           the QA agent decides what to test
  python -m trust label BATCH_ID [--n 60]         hand-label judge claims (you are the ground truth)
  python -m trust agreement                       judge vs your labels: recall, true-negative rate, kappa
"""
import argparse
import json
import random
import sys

from . import config, judge, llm, pipeline, stats, tracing

LABELS_FILE = config.DATA / "labels.jsonl"


def _print(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def cmd_canary(a):
    from .agent import run_canaries
    out = run_canaries(use_judge=not a.no_judge)
    for name, c in out["checkers"].items():
        print(f"\n{name}\n  caught bad emails:  {c['caught_bad']}\n  false alarms:       {c['false_alarms_on_honest']}")
        for m in c["missed"]:
            print(f"    missed: {m}")
        for m in c["false_alarms"]:
            print(f"    false alarm: {m}")


def cmd_trial(a):
    fams = a.families.split(",") if a.families else None
    s = pipeline.run_batch(fams, a.split, a.runs, a.fix)
    _print({"batch": s["batch"], "overall": s["overall"], "families": s["families"], "trace": s["trace_url"]})
    for ex in pipeline.examples(s["batch"], limit=3):
        print("\n---", ex["family"], ex["note"], "| evaboot check:", ex["evaboot_check"])
        print("Subject:", ex["subject"]); print(ex["body"]); print("WHY:", *ex["why_failed"], sep="\n  ")


def cmd_fix(a):
    rules_text = open(a.rules).read() if a.rules else ""
    _print(pipeline.save_fix(a.name, rules_text, [g for g in (a.guards or "").split(",") if g], a.rationale or ""))


def cmd_compare(a):
    from .agent import compare
    _print(compare(None, a.fix, a.split, a.runs))


def cmd_agent(a):
    from .agent import Agent
    path = Agent().run()
    print("\nreport:", path)


def cmd_label(a):
    recs = pipeline.load(a.batch)
    claims = []
    for r in recs:
        for i, c in enumerate(r["judge"]["claims"]):
            if c["type"] in ("generic", "conditional"):
                continue
            claims.append((r, i, c))
    flagged = [x for x in claims if x[2]["label"] in ("contradicted", "not_in_source")]
    rest = [x for x in claims if x not in flagged]
    rnd = random.Random(1)
    rnd.shuffle(flagged); rnd.shuffle(rest)
    pick = flagged[:a.n // 2] + rest[:a.n - min(len(flagged), a.n // 2)]
    rnd.shuffle(pick)
    done = set()
    if LABELS_FILE.exists():
        done = {(l["batch"], l["lead_id"], l["run"], l["idx"]) for l in map(json.loads, open(LABELS_FILE))}
    from .leads import select, truth_view
    by_id = {l["id"]: l for l in select()}
    keys = {"s": "supported", "c": "contradicted", "n": "not_in_source", "x": "not_a_claim"}
    print("Label each claim yourself, WITHOUT looking at the judge. s=supported c=contradicted n=not_in_source "
          "x=not a claim, q=quit\n")
    for r, i, c in pick:
        k = (r["batch"], r["lead_id"], r["run"], i)
        if k in done:
            continue
        print("=" * 80)
        print(json.dumps(truth_view(by_id[r["lead_id"]]["prospect"]), indent=1, ensure_ascii=False))
        print("\nSubject:", r["email"].get("subject")); print(r["email"].get("body"))
        print(f"\nCLAIM: \"{c['span']}\"  ->  {c['claim']}")
        ans = input("your label [s/c/n/x/q]: ").strip().lower()
        if ans == "q":
            break
        if ans not in keys:
            continue
        with open(LABELS_FILE, "a") as fh:
            fh.write(json.dumps({"batch": r["batch"], "lead_id": r["lead_id"], "run": r["run"], "idx": i,
                                 "span": c["span"], "human": keys[ans], "judge": c["label"]}) + "\n")


def cmd_agreement(a):
    labels = [json.loads(l) for l in open(LABELS_FILE)]
    bad = lambda x: x in ("contradicted", "not_in_source")
    h = [bad(l["human"]) for l in labels]
    j = [bad(l["judge"]) for l in labels]
    tp = sum(x and y for x, y in zip(h, j)); fn = sum(x and not y for x, y in zip(h, j))
    tn = sum((not x) and (not y) for x, y in zip(h, j)); fp = sum((not x) and y for x, y in zip(h, j))
    print(f"labels: {len(labels)}  (you marked {sum(h)} unsupported)")
    print(f"judge catches unsupported claims (recall): {stats.rate(tp, tp + fn)}")
    print(f"judge passes supported claims (true-negative rate): {stats.rate(tn, tn + fp)}")
    print(f"Cohen's kappa (unsupported vs ok): {stats.cohen_kappa(h, j):.2f}")
    print(f"exact 4-way label agreement: {stats.rate(sum(l['human'] == l['judge'] for l in labels), len(labels))}")
    if sum(h) < 15:
        print("note: fewer than 15 unsupported labels; the recall interval is wide. Label more.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("canary"); p.add_argument("--no-judge", action="store_true")
    p = sub.add_parser("trial"); p.add_argument("--split", default="dev"); p.add_argument("--runs", type=int, default=5)
    p.add_argument("--families"); p.add_argument("--fix")
    p = sub.add_parser("fix"); p.add_argument("--name", required=True); p.add_argument("--rules")
    p.add_argument("--guards"); p.add_argument("--rationale")
    p = sub.add_parser("compare"); p.add_argument("--fix", required=True); p.add_argument("--split", default="heldout")
    p.add_argument("--runs", type=int, default=5)
    sub.add_parser("agent")
    p = sub.add_parser("label"); p.add_argument("batch"); p.add_argument("--n", type=int, default=60)
    sub.add_parser("agreement")
    a = ap.parse_args()
    needs_key = a.cmd in ("trial", "compare", "agent") or (a.cmd == "canary" and not a.no_judge)
    if needs_key and not config.MOCK:
        ok, names = llm.proxy_up()
        if not ok:
            sys.exit(f"LiteLLM proxy not reachable at {config.LLM_BASE_URL} (or missing the writer/judge/agent "
                     f"aliases; found {sorted(names) or 'none'}). Start it in another terminal: scripts/proxy.sh "
                     "(needs your personal provider key in .env). Or run with TRUST_MOCK=1 for an offline dry run.")
    try:
        globals()["cmd_" + a.cmd](a)
    finally:
        tracing.flush()


if __name__ == "__main__":
    main()
