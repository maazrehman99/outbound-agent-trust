"""Claim-level LLM judge.

Splits one email into atomic claims and labels each against the lead's real data. The email
verdict is decided in code from the labels (any unsupported claim about the lead or the seller
fails the email), never as an overall score from the model.
"""
import json
from collections import Counter
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from . import config, llm, tracing

ClaimType = Literal["lead_fact", "seller_fact", "implied", "generic", "conditional"]
Label = Literal["supported", "contradicted", "not_in_source", "not_a_claim"]


class Claim(BaseModel):
    span: str = Field(description="exact substring of the email")
    claim: str = Field(description="the claim restated as one short factual sentence")
    type: ClaimType
    label: Label
    evidence_field: Optional[str] = Field(default=None, description="lead-data or OFFER field that decides it, or null")
    reason: str


class Judgement(BaseModel):
    claims: List[Claim]


SYSTEM = """You check B2B cold emails for claims that the data does not support.

You get: the lead's real data (missing fields are null and mean UNKNOWN), the seller's OFFER.md, and one email.

Split the email (subject + body) into atomic claims. For each claim give:
- span: an exact substring of the email.
- type:
  - lead_fact: states or presumes something about the lead, their company or team (role, tenure, growth, size,
    funding, hiring, results, plans).
  - seller_fact: states something about the seller's product, customers or results.
  - implied: not stated outright but clearly presumed (e.g. "as you scale your team" presumes they are growing).
  - generic: honest sales language that asserts nothing checkable ("lists with emails in minutes" is NOT generic,
    it is a seller_fact; "worth a look?" is generic).
  - conditional: framed as if/when/before ("if you are hiring SDRs") - asserts nothing.
  Empathy and pain guesses are generic too: "you probably know the pain of building lists", "keeping lists clean
  must be a constant job", "you need clean lists fast". They only count as implied when they presume a checkable
  FACT about the lead: a new role, growth or shrinking, funding, hiring, a team size or stage ("still building the
  team"), a result, a tool or a customer.
- label:
  - supported: the data says it (paraphrase is fine; same sign and same subject).
  - contradicted: the data says otherwise (e.g. growth is negative but the email praises growth; a number that
    belongs to a past employer or a client presented as the current company's).
  - not_in_source: the data does not say it (unknown fields, invented rounds, invented team sizes, invented customers).
  - not_a_claim: generic or conditional text.
- evidence_field: the field that decides it, or null.
- reason: one short sentence.

Be strict about the lead's company: a number in the summary about a previous employer or a client is NOT the
current company's result. A missing time-in-role means the tenure is unknown: "congrats on the new role" is then
not_in_source unless has_new_position_flag is true or months_in_role < 6.
Do not flag the greeting, the sign-off or the question asked."""


def _user(truth, email):
    offer = (config.TARGET / "OFFER.md").read_text()
    return ("# Lead data\n" + json.dumps(truth, indent=2, ensure_ascii=False) +
            "\n\n# OFFER.md\n" + offer +
            "\n\n# Email\nSubject: " + (email.get("subject") or "") + "\n\n" + (email.get("body") or ""))


def failing(claims):
    return [c for c in claims if c["type"] in ("lead_fact", "seller_fact", "implied")
            and c["label"] in ("contradicted", "not_in_source")]


@tracing.observe(as_type="evaluator", name="claim-judge")
def judge(truth, email, votes=1):
    """Returns {"claims": [...], "fail": bool, "votes": n, "unanimous": bool}."""
    if email.get("skip"):
        return {"claims": [], "fail": False, "votes": 0, "unanimous": True}
    if config.MOCK:
        from .mock import mock_judge
        return mock_judge(truth, email)
    runs = []
    for _ in range(votes):
        out, _u = llm.structured(model=config.JUDGE_MODEL, system=SYSTEM, user=_user(truth, email),
                                 schema=Judgement, effort=config.JUDGE_EFFORT, max_tokens=16000, label="judge")
        runs.append([c.model_dump() for c in out.claims])
    fails = [bool(failing(r)) for r in runs]
    verdict = Counter(fails).most_common(1)[0][0]
    claims = next(r for r, f in zip(runs, fails) if f == verdict)
    res = {"claims": claims, "fail": verdict, "votes": votes, "unanimous": len(set(fails)) == 1}
    tracing.update_span(output={"fail": verdict, "failing_claims": failing(claims)})
    return res
