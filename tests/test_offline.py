"""Offline tests: no API key needed."""
import json
import os

os.environ["TRUST_MOCK"] = "1"
import tempfile  # noqa: E402
os.environ["TRUST_OUT_DIR"] = tempfile.mkdtemp(prefix="trust-test-")

from trust import canaries, leads, pipeline, rules, stats, target  # noqa: E402
from trust.agent import TOOLS, run_canaries  # noqa: E402


def test_evaboot_facts_bug_missing_tenure_becomes_new_in_role():
    lead = leads.select(["unknown_tenure"], "dev")[0]
    f = target.facts([lead["prospect"]])[0]
    assert f["months_in_role"] == 0 and f["new_in_role"] is True      # their bug, as shipped
    t = leads.truth_view(lead["prospect"])
    assert t["months_in_role"] is None and t["has_new_position_flag"] is False


def test_evaboot_check_passes_every_canary():
    for c in canaries.build():
        facts = target.facts([c["lead"]["prospect"]])
        assert target.check(facts, [c["email"]])[c["lead"]["id"]] == [], c["why"]


def test_rules_on_canaries():
    expected_miss = {"300% was Acme Corp, a past employer", "40 was the last company; sales team is 7"}
    for c in canaries.build():
        got = bool(rules.check(c["email"], c["lead"], leads.truth_view(c["lead"]["prospect"])))
        if c["why"] in expected_miss:
            assert not got, c["why"]          # attribution needs the judge, by design
        else:
            assert got == c["should_fail"], c["why"]


def test_spelled_and_signed_numbers():
    assert [n[0] for n in rules.numbers_in("twenty-five reps and 12% growth")] == [25, 12]


def test_suppressed_lead_with_email_fails_and_skip_passes():
    lead = leads.select(["suppressed"], "dev")[0]
    t = leads.truth_view(lead["prospect"])
    assert rules.check({"id": lead["id"], "subject": "x", "body": "Hi"}, lead, t)[0]["rule"] == "suppressed_lead"
    assert rules.check({"id": lead["id"], "skip": True, "reason": "x"}, lead, t) == []


def test_every_family_has_dev_and_heldout():
    for f in leads.FAMILIES:
        assert leads.select([f], "dev") and leads.select([f], "heldout"), f


def test_stats():
    lo, hi = stats.wilson(9, 10)
    assert 0.59 < lo < 0.61 and 0.98 < hi < 0.99
    assert stats.pass_hat_k(5, 5, 5) == 1 and stats.pass_hat_k(4, 5, 5) == 0
    assert stats.mcnemar_exact(4, 0) == 0.125
    assert abs(stats.cohen_kappa([1, 1, 0, 0], [1, 0, 0, 0]) - 0.5) < 1e-9


def test_tool_schemas_are_strict_objects():
    for t in TOOLS:
        assert t["type"] == "function"
        s = t["function"]["parameters"]
        assert s["type"] == "object" and s["additionalProperties"] is False
        assert set(s["required"]) == set(s["properties"])
    json.dumps(TOOLS)


def test_mock_trial_and_canaries_run():
    s = pipeline.run_batch(["negative_growth", "suppressed", "clean"], "dev", 2)
    assert s["overall"]["emails"] == 12 and "negative_growth" in s["families"]
    assert run_canaries(use_judge=False)["checkers"]["evaboot_check"]["caught_bad"].startswith("0/")
