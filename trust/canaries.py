"""Canary emails: hand-written emails with a known right verdict, to measure the CHECKERS
(Evaboot's check, the rules, the judge) before trusting them on real writer output.
Several come from the out-of-distribution cases posted on outbound-agent-scorecard PR #3."""
from . import leads as leadmod

OFFER = ("Evaboot exports a LinkedIn Sales Navigator search to a clean spreadsheet with verified emails, "
         "so your team gets prospect lists in minutes instead of copy-paste, with fewer bounces.")


def _lead(family, nth=0, split=None):
    return [l for l in leadmod.build() if l["family"] == family and (not split or l["split"] == split)][nth]


def _email(first, para, ask="Worth a look?"):
    return f"Hi {first},\n\n{para}\n\n{OFFER}\n\n{ask}"


def build():
    c = []

    def add(family, nth, subject, para, should_fail, why):
        lead = _lead(family, nth)
        first, co = lead["prospect"]["First Name"], lead["prospect"]["Company Name"]
        para = para.replace("{co}", co)
        subject = subject.replace("{co}", co.split()[0].lower())
        c.append({"lead": lead, "email": {"id": lead["id"], "hook": "x", "subject": subject,
                                          "body": _email(first, para)},
                  "should_fail": should_fail, "why": why})

    # invented or wrong claims (should fail)
    add("negative_growth", 0, "12% growth at {co}", "Congrats on 12% growth at {co} this year.", True,
        "growth is -12: sign flipped")
    add("negative_growth", 1, "scaling the team", "With {co} growing fast, your reps need lists faster.", True,
        "growth is -25 but 'growing fast'")
    add("unknown_tenure", 0, "new role", "Congrats on stepping into the new role at the company.", True,
        "tenure unknown; facts() wrongly says new_in_role")
    add("funding_bait", 0, "after the raise", "Congrats on the raise - closing your round must free up budget for outbound.",
        True, "no round in the data")
    add("funding_bait", 1, "series a momentum", "Big milestone this quarter - congrats on the Series A.", True,
        "milestone is not a Series A")
    add("distractor_number", 0, "300% growth", "Growing revenue 300% at your company is rare.", True,
        "300% was Acme Corp, a past employer")
    add("distractor_number", 1, "your 40-person sdr team", "Running a 40-person SDR team means lists never stop.", True,
        "40 was the last company; sales team is 7")
    add("no_sales_team", 0, "twenty-five reps", "Keeping twenty-five reps fed with fresh leads is a full-time job.", True,
        "sales team size unknown; spelled-out number")
    add("not_hiring", 0, "hiring sdrs", "Since you're hiring SDRs, they will need clean lists from day one.", True,
        "lead says not hiring")
    add("clean", 1, "lists for {co}", "With 120 customers on {co}, prospecting must be busy.", True,
        "120 customers invented (120 is headcount)")

    # honest emails (should pass)
    add("negative_growth", 0, "lists for a leaner team", "Running sales with a team that shrank 12% in a year means "
        "every rep's hours count.", False, "honest about -12%")
    add("clean", 0, "new role at {co}", "Congrats on the new role at {co}.", False,
        "has_new_position true, 3 months")
    add("clean", 1, "35% in a year", "{co} grew headcount 35% in a year, and your sales team is 18 people.", False,
        "both numbers in data")
    add("no_sales_team", 0, "before your next campaign", "Before you launch your next campaign, clean lists save the "
        "first week.", False, "honest generic 'launch your next campaign' (PR #3 false alarm)")
    add("funding_bait", 0, "if you are hiring sdrs", "If you are hiring SDRs this quarter, they will need lists on day "
        "one.", False, "conditional hiring (PR #3 false alarm)")
    add("distractor_number", 0, "after acme", "Helping Acme Corp grow revenue 300% before joining your current team is a "
        "strong story.", False, "300% correctly attributed to Acme")
    return c
