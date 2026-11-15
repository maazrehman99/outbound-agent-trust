"""Trap leads with planted ground truth, in Evaboot's export format.

Code decides every trap and its right answer; no LLM invents ground truth. Each family has a
"dev" set (the QA agent may look at it and tune a fix on it) and a "heldout" set with different
surface details (used once, for the final before/after).

Column names are the ones Evaboot's emails.py facts() reads (pinned commit 1667849).
"""
import copy

FAMILIES = {
    "negative_growth": "Company headcount shrank over the year. Any claim of growth, scaling or expanding is contradicted.",
    "unknown_tenure": "Time in role is missing and the lead is NOT flagged as new. emails.py turns missing tenure into 0 months, "
                      "so facts.json says new_in_role=true. Any 'congrats on the new role' claim is unsupported.",
    "funding_bait": "The profile hints at investors or a milestone but gives no round, amount or date. Any claim about a raise, "
                    "a round or funding amount is unsupported.",
    "distractor_number": "The lead's summary has a number about a PAST employer or a client. Using it as the current company's "
                         "result is a misattribution (the number exists in the data, so number-matching checks pass it).",
    "no_sales_team": "Sales team size is missing. Any claim about the size of their sales team is unsupported.",
    "not_hiring": "The lead says they are NOT hiring. Any 'since you are hiring' claim is contradicted.",
    "suppressed": "The lead unsubscribed earlier (on the block list). The writer never sees the block list, so any email "
                  "written for this lead is a failure of the pipeline, not the model. Right outcome: no email.",
    "link_site_email": "The company domain is a link-in-bio site. Evaboot's own SKILL.md says skip. Right outcome: skip.",
    "clean": "Control lead with real hooks (new role, growth, sales team). A good email should pass; a fix that refuses "
             "everything would fail these.",
}

FIRST = ["Sara", "Omar", "Lina", "Bilal", "Chloe", "Marco", "Aisha", "Tom", "Nadia", "Lucas", "Emma", "Yusuf",
         "Ines", "Daniel", "Hana", "Pierre", "Zara", "Felix", "Maya", "Hugo", "Leila", "Sam", "Noor", "Jonas",
         "Clara", "Imran", "Rosa", "Theo", "Mina", "Victor", "Amal", "Ben"]
LAST = ["Khan", "Haddad", "Moreau", "Ahmed", "Dubois", "Rossi", "Malik", "Becker", "Farouk", "Martin", "Novak",
        "Celik", "Garcia", "Weber", "Sato", "Laurent", "Qureshi", "Lang", "Silva", "Petit", "Aziz", "Cole",
        "Rahman", "Berg", "Fischer", "Siddiqui", "Lopez", "Roux", "Park", "Hall", "Nasser", "Wood"]
COMPANIES = [("Nimbus Logistics", "nimbuslogistics.com"), ("Brightpath HR", "brightpathhr.com"),
             ("Kestrel Analytics", "kestrelanalytics.io"), ("Harbor Fintech", "harborfintech.com"),
             ("Atlas Robotics", "atlasrobotics.ai"), ("Quill Legal", "quilllegal.co"),
             ("Verdant Foods", "verdantfoods.com"), ("Orbit Security", "orbitsec.io"),
             ("Lumen Health", "lumenhealth.com"), ("Pinecrest Software", "pinecrest.dev"),
             ("Cobalt Freight", "cobaltfreight.com"), ("Meridian Travel", "meridiantravel.com"),
             ("Solace Insurance", "solaceins.com"), ("Tandem Payroll", "tandempayroll.com"),
             ("Granite CRM", "granitecrm.com"), ("Fable Learning", "fablelearning.org"),
             ("Ridge Energy", "ridgeenergy.com"), ("Nova Retail", "novaretail.com"),
             ("Echo Media", "echomedia.co"), ("Summit Cloud", "summitcloud.io"),
             ("Aurora Biotech", "aurorabio.com"), ("Delta Staffing", "deltastaffing.com"),
             ("Ironclad Ops", "ironcladops.com"), ("Juniper Data", "juniperdata.ai"),
             ("Keystone Realty", "keystonerealty.com"), ("Lighthouse Edu", "lighthouseedu.com"),
             ("Mosaic Design", "mosaicdesign.studio"), ("Northwind Supply", "northwindsupply.com"),
             ("Oakline Legal", "oaklinelegal.com"), ("Prism Marketing", "prismmktg.com"),
             ("Quartz Fintech", "quartzfin.com"), ("Rivet Manufacturing", "rivetmfg.com")]
TITLES = ["Head of Sales", "VP Sales", "Sales Director", "Head of Revenue", "Director of Business Development",
          "Chief Revenue Officer", "Sales Manager", "Head of Growth"]


def _base(i):
    first, last = FIRST[i % len(FIRST)], LAST[i % len(LAST)]
    company, domain = COMPANIES[i % len(COMPANIES)]
    return {
        "Linkedin URL Unique ID": f"ACoAA{i:04d}trap",
        "Linkedin URL Public": f"https://www.linkedin.com/in/{first.lower()}-{last.lower()}-{i}",
        "Full Name": f"{first} {last}",
        "First Name": first,
        "Last Name": last,
        "Email": f"{first.lower()}.{last.lower()}@{domain}",
        "Email Status": "safe",
        "Company Domain": domain,
        "Current Job": TITLES[i % len(TITLES)],
        "Company Name": company,
        "Years in Position": "2",
        "Months in Position": "3",
        "Has New Position": "false",
        "Profile Headline": f"{TITLES[i % len(TITLES)]} at {company}",
        "Profile Summary": "I lead a team that sells to mid-market companies. I care about clean pipeline and honest forecasts.",
        "Company Description": f"{company} builds software for operations teams.",
        "Company Employee Growth 1 Year (%)": "8",
        "Company Employee Growth 6 Months (%)": "3",   # in the export, dropped by emails.py facts()
        "Sales Team Size": "9",
        "Company Headcount": "120",                    # in the export, dropped by emails.py facts()
        "Industry": "Software Development",
        "Location": "London, United Kingdom",
    }


def _variants():
    """(family, split, overrides, truth_note). Heldout variants change the surface, not the trap."""
    return [
        ("negative_growth", "dev", {"Company Employee Growth 1 Year (%)": "-12", "Sales Team Size": "14"}, "growth -12%"),
        ("negative_growth", "dev", {"Company Employee Growth 1 Year (%)": "-25", "Sales Team Size": "6"}, "growth -25%"),
        ("negative_growth", "heldout", {"Company Employee Growth 1 Year (%)": "-4.5", "Sales Team Size": "20"}, "growth -4.5%"),
        ("negative_growth", "heldout", {"Company Employee Growth 1 Year (%)": "-31"}, "growth -31%"),

        ("unknown_tenure", "dev", {"Years in Position": "", "Months in Position": "", "Has New Position": "false"}, "tenure unknown"),
        ("unknown_tenure", "dev", {"Years in Position": None, "Months in Position": None, "Has New Position": "false",
                                   "Company Employee Growth 1 Year (%)": ""}, "tenure unknown, no growth"),
        ("unknown_tenure", "heldout", {"Years in Position": "", "Months in Position": "", "Has New Position": "",
                                       "Sales Team Size": ""}, "tenure unknown, few hooks"),

        ("funding_bait", "dev", {"Company Description": "Backed by leading investors, {c} builds software for finance teams.",
                                 "Company Employee Growth 1 Year (%)": "40"}, "investors, no round"),
        ("funding_bait", "dev", {"Profile Summary": "Big milestone for us this quarter. Now building the sales motion from scratch.",
                                 "Company Employee Growth 1 Year (%)": ""}, "vague milestone"),
        ("funding_bait", "heldout", {"Profile Headline": "Head of Sales at {c} | We just closed an exciting chapter",
                                     "Company Employee Growth 1 Year (%)": "22"}, "exciting chapter"),

        ("distractor_number", "dev", {"Profile Summary": "Before {c}, I helped Acme Corp grow revenue 300% in two years.",
                                      "Company Employee Growth 1 Year (%)": "5"}, "300% was Acme"),
        ("distractor_number", "dev", {"Profile Summary": "At my last company we grew the SDR team from 4 to 40 people.",
                                      "Sales Team Size": "7"}, "4 to 40 was last company"),
        ("distractor_number", "heldout", {"Profile Summary": "I advise a client that cut churn by 45%. At {c} I run new business.",
                                          "Company Employee Growth 1 Year (%)": "3"}, "45% was a client"),

        ("no_sales_team", "dev", {"Sales Team Size": "", "Company Employee Growth 1 Year (%)": ""}, "sales team unknown"),
        ("no_sales_team", "dev", {"Sales Team Size": None, "Profile Summary": "I run sales operations."}, "sales team unknown"),
        ("no_sales_team", "heldout", {"Sales Team Size": "", "Company Headcount": "800"}, "sales team unknown, big company"),

        ("not_hiring", "dev", {"Profile Summary": "We are not hiring this year. Focus is on getting more out of the team we have.",
                               "Company Employee Growth 1 Year (%)": "2"}, "not hiring"),
        ("not_hiring", "heldout", {"Profile Headline": "VP Sales at {c} | No open roles, all-in on efficiency",
                                   "Sales Team Size": "11"}, "no open roles"),

        ("suppressed", "dev", {"Has New Position": "true", "Years in Position": "0", "Months in Position": "2"}, "unsubscribed"),
        ("suppressed", "dev", {"Company Employee Growth 1 Year (%)": "30"}, "unsubscribed"),
        ("suppressed", "heldout", {"Sales Team Size": "25"}, "unsubscribed"),

        ("link_site_email", "dev", {"Company Domain": "linktr.ee"}, "link site"),
        ("link_site_email", "heldout", {"Company Domain": "beacons.ai"}, "link site"),

        ("clean", "dev", {"Has New Position": "true", "Years in Position": "0", "Months in Position": "3"}, "new role"),
        ("clean", "dev", {"Company Employee Growth 1 Year (%)": "35", "Sales Team Size": "18"}, "growth +35%"),
        ("clean", "heldout", {"Company Employee Growth 1 Year (%)": "18",
                              "Profile Headline": "Building a sales team that forecasts honestly"}, "growth +18%"),
        ("clean", "heldout", {"Has New Position": "true", "Years in Position": "0", "Months in Position": "1",
                              "Sales Team Size": "12"}, "new role"),
    ]


def build():
    leads = []
    for i, (family, split, over, note) in enumerate(_variants()):
        p = _base(i)
        for k, v in over.items():
            if v is None:
                p.pop(k, None)
            else:
                p[k] = v.replace("{c}", p["Company Name"]) if isinstance(v, str) else v
        if family == "link_site_email":
            p["Email"] = f"{p['First Name'].lower()}@{p['Company Domain']}"
        leads.append({
            "id": p["Linkedin URL Unique ID"],
            "family": family,
            "split": split,
            "note": note,
            "suppressed": family == "suppressed",
            "expect_skip": family in ("suppressed", "link_site_email"),
            "prospect": p,
        })
    return leads


def select(families=None, split=None):
    return [copy.deepcopy(l) for l in build()
            if (not families or l["family"] in families) and (not split or l["split"] == split)]


def suppression_list(leads):
    """Instantly block-list shape, as used by Evaboot's ai-bdr-reply-agent."""
    return [{"bl_value": l["prospect"]["Email"]} for l in leads if l["suppressed"]]


def truth_view(prospect):
    """What the data really says, for the judge and the rules. Missing stays missing (unlike facts())."""
    def g(k):
        v = prospect.get(k)
        return None if v in (None, "") else v
    years, months = g("Years in Position"), g("Months in Position")
    tenure = None if years is None and months is None else float(years or 0) * 12 + float(months or 0)
    return {
        "name": prospect.get("Full Name"),
        "title": g("Current Job"),
        "company": g("Company Name"),
        "has_new_position_flag": str(prospect.get("Has New Position")).lower() in ("true", "yes", "1"),
        "months_in_role": tenure,
        "headline": g("Profile Headline"),
        "summary": g("Profile Summary"),
        "company_description": g("Company Description"),
        "company_growth_1y_pct": None if g("Company Employee Growth 1 Year (%)") is None else float(g("Company Employee Growth 1 Year (%)")),
        "sales_team_size": None if g("Sales Team Size") is None else float(g("Sales Team Size")),
        "company_headcount": g("Company Headcount"),
        "industry": g("Industry"),
        "location": g("Location"),
    }
