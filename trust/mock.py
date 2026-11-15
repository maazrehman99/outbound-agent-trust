"""Offline stand-ins (TRUST_MOCK=1) so the whole pipeline can be tested with no API key.
The mock writer makes the kinds of mistakes we test for, some of the time."""
import random

from . import rules


def mock_write(fact):
    rnd = random.Random()
    first = fact["first_name"]
    g = fact.get("company_growth_1y_pct")
    if "do not send" in (fact.get("email_check") or "") and rnd.random() < 0.5:
        return {"id": fact["id"], "skip": True, "reason": fact["email_check"]}
    if fact.get("new_in_role"):
        hook, para = "new role", f"Congrats on the new role at {fact['company']}."
    elif g is not None and rnd.random() < 0.7:
        hook, para = "growth", f"Saw {fact['company']} at {abs(g):g}% growth in a year, impressive momentum."
    elif rnd.random() < 0.3:
        hook, para = "funding", f"Congrats on the recent raise at {fact['company']}."
    else:
        hook, para = "headline", f"Your headline says {fact['headline']}, which caught my eye."
    body = (f"Hi {first},\n\n{para} Building prospect lists by hand slows any sales team down.\n\n"
            "Evaboot exports a LinkedIn Sales Navigator search to a clean spreadsheet with verified emails, "
            "so your team gets lists in minutes instead of copy-paste and sees fewer bounces.\n\nWorth a look?")
    return {"id": fact["id"], "hook": hook, "subject": f"lists for {fact['company'].lower()}", "body": body}


def mock_judge(truth, email):
    fake_lead = {"family": "x", "prospect": {}, "suppressed": False}
    found = rules.check(email, fake_lead, truth)
    claims = [{"span": f["span"], "claim": f["reason"], "type": "lead_fact", "label": f["label"],
               "evidence_field": None, "reason": f["reason"]} for f in found if f["label"] != "guard"]
    return {"claims": claims, "fail": bool(claims), "votes": 1, "unanimous": True}
