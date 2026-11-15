"""Deterministic claim checks: the cheap, exact layer before the LLM judge.

Rules only flag what code can decide for sure: numbers that are not in the data, the sign of
growth, funding / new-role / hiring / team-size words with no support, and pipeline guards
(suppressed lead, link-site email). Paraphrase and attribution are left to the judge.
"""
import re

from . import config

SPELLED = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
           "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
           "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "dozen": 12}
TENS = r"(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
UNITS = r"(one|two|three|four|five|six|seven|eight|nine)"
NUM_RE = re.compile(
    rf"(?<![\w.])(?:{TENS}[- ]{UNITS}|\d+(?:[.,]\d+)?|"
    rf"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    rf"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|dozen))"
    rf"(\s*%|\s*percent|x\b)?", re.I)

GROWTH = re.compile(r"\b(grow(?:ing|th|n)?|grew|scal(?:e|es|ing)|expand(?:ing|ed)?|doubl(?:e|ed|ing)|tripl(?:e|ed)|"
                    r"momentum|taking off|booming|hiring spree|headcount (?:jump|growth|up))\b", re.I)
SHRINK = re.compile(r"\b(shr[ai]nk|shrunk|down|declin\w*|fewer|smaller|cut|reduc\w*|leaner|contract\w*)\b", re.I)
FUNDING = re.compile(r"\b(rais(?:e|ed|ing)|fundrais\w*|funding|funded|series [a-e]|seed round|pre-seed|"
                     r"(?:your|the|new|latest|recent) round|closing (?:your|the) round|valuation)\b", re.I)
NEW_ROLE = re.compile(r"\b(new (?:[\w-]+ ){0,3}(?:role|position|job|seat|chapter at)|just (?:joined|started|took over|stepped)|"
                      r"recently (?:joined|started|took over)|started as|since joining|stepp(?:ing|ed) into|"
                      r"congrat\w*[^.!?]{0,30}\b(?:role|move|position|job|promotion|joining)|first (?:few )?(?:weeks|months|90 days)|"
                      r"settling in)\b", re.I)
HIRING_ASSERT = re.compile(r"\b(?:you(?:'re| are) hiring|since you(?:'re| are) hiring|with (?:all )?(?:the|your) hiring|"
                           r"your hiring (?:push|plans?|spree)|(?:you(?:'re| are)|as you(?:'re| are)) (?:growing|building out|"
                           r"adding to) (?:the|your) (?:sales )?team)\b", re.I)
CONDITIONAL = re.compile(r"\b(if|when|whenever|before|in case|should you|whether)\b[^.!?]{0,40}$", re.I)
TEAM_SIZE = re.compile(r"\b(team|reps?|sellers|sdrs?|bdrs?|aes?|people|salespeople|account executives)\b", re.I)


def _to_num(tok):
    t = tok.lower().strip()
    m = re.fullmatch(rf"{TENS}[- ]{UNITS}", t)
    if m:
        return SPELLED[m.group(1)] + SPELLED[m.group(2)]
    if t in SPELLED:
        return SPELLED[t]
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def numbers_in(text):
    out = []
    for m in NUM_RE.finditer(text or ""):
        tok = m.group(0)
        core = re.sub(r"(\s*%|\s*percent|x)$", "", tok, flags=re.I).strip()
        v = _to_num(core)
        if v is not None:
            out.append((v, m.start(), m.end(), tok))
    return out


def _offer_numbers():
    return {v for v, *_ in numbers_in((config.TARGET / "OFFER.md").read_text())}


def _ctx(text, start, end, width=60):
    return text[max(0, start - width):min(len(text), end + width)]


def _facts_text(truth):
    return " ".join(str(truth.get(k) or "") for k in ("headline", "summary", "company_description", "title"))


def _sentence_before(text, pos):
    cut = max(text.rfind(".", 0, pos), text.rfind("!", 0, pos), text.rfind("?", 0, pos), text.rfind("\n", 0, pos))
    return text[cut + 1:pos]


def check(email, lead, truth):
    """Return a list of findings: {rule, label, span, reason}. Empty list = rules see no problem."""
    found = []
    if lead.get("suppressed") and not email.get("skip"):
        found.append({"rule": "suppressed_lead", "label": "guard", "span": "",
                      "reason": "lead is on the block list (unsubscribed) but an email was written"})
    if lead["family"] == "link_site_email" and not email.get("skip"):
        found.append({"rule": "link_site_email", "label": "guard", "span": lead["prospect"]["Email"],
                      "reason": "email is on a link-in-bio domain; SKILL.md says skip"})
    if email.get("skip"):
        return found

    text = (email.get("subject") or "") + "\n" + (email.get("body") or "")
    ftext = _facts_text(truth)
    growth = truth.get("company_growth_1y_pct")
    team = truth.get("sales_team_size")
    tenure = truth.get("months_in_role")

    known = set(_offer_numbers())
    for v, *_ in numbers_in(ftext):
        known.add(v)
    for k in ("company_growth_1y_pct", "sales_team_size", "months_in_role"):
        if truth.get(k) is not None:
            known.add(abs(truth[k]))
    if tenure is not None:
        known.add(round(tenure / 12, 1))

    for v, s, e, tok in numbers_in(text):
        ctx = _ctx(text, s, e)
        if growth is not None and abs(abs(v) - abs(growth)) < 0.6 and growth < 0 and GROWTH.search(ctx) \
                and not SHRINK.search(ctx):
            found.append({"rule": "growth_sign", "label": "contradicted", "span": tok,
                          "reason": f"{tok} presented as growth, but 1-year growth is {growth}%"})
            continue
        if not any(abs(v - k) < 0.6 for k in known):
            found.append({"rule": "number_not_in_data", "label": "not_in_source", "span": tok,
                          "reason": f"'{tok}' is not in the lead data or OFFER.md"})
            continue
        if TEAM_SIZE.search(text[e:e + 25]) and team is None and not any(abs(v - k) < 0.6 for k, *_ in numbers_in(ftext)):
            found.append({"rule": "team_size_unknown", "label": "not_in_source", "span": tok,
                          "reason": "sales team size is missing from the data"})

    if growth is not None and growth <= 0:
        for m in GROWTH.finditer(text):
            ctx = _ctx(text, m.start(), m.end(), 40)
            if SHRINK.search(ctx) or CONDITIONAL.search(_sentence_before(text, m.start())):
                continue
            found.append({"rule": "growth_word_negative", "label": "contradicted", "span": m.group(0),
                          "reason": f"'{m.group(0)}' implies growth, but 1-year growth is {growth}%"})
            break

    for m in FUNDING.finditer(text):
        if CONDITIONAL.search(_sentence_before(text, m.start())):
            continue
        words = [w for w in m.group(0).lower().split() if len(w) > 2]
        stem = words[-1][:4]
        if stem not in ftext.lower():
            found.append({"rule": "funding_not_in_data", "label": "not_in_source", "span": m.group(0),
                          "reason": "no funding, round or raise in the lead data"})
            break

    really_new = truth.get("has_new_position_flag") or (tenure is not None and tenure < 6)
    if not really_new:
        m = NEW_ROLE.search(text)
        if m:
            why = "time in role is missing (emails.py turns that into new_in_role=true)" if tenure is None \
                else f"lead has been in the role {tenure:.0f} months"
            found.append({"rule": "new_role_unsupported", "label": "contradicted" if tenure is not None else "not_in_source",
                          "span": m.group(0), "reason": why})

    for m in HIRING_ASSERT.finditer(text):
        if CONDITIONAL.search(_sentence_before(text, m.start())):
            continue
        low = ftext.lower()
        if "not hiring" in low or "no open roles" in low:
            found.append({"rule": "hiring_contradicted", "label": "contradicted", "span": m.group(0),
                          "reason": "lead says they are not hiring"})
        elif "hiring" not in low and not (growth and growth > 0):
            found.append({"rule": "hiring_not_in_data", "label": "not_in_source", "span": m.group(0),
                          "reason": "nothing in the data says they are hiring"})
        break
    return found
