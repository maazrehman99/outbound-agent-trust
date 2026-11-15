# One lead, start to finish

A real record from the agent's run on 2026-11-07 (dev batch `1107-012048-dev-base-9e7d`, run 0, and the fix batch
`1107-012841-dev-fix-fd3e`). The lead is synthetic, in the Evaboot export format.

## 1. The lead (trap: time in role is empty)

| Field | Value |
|---|---|
| Full Name | Chloe Dubois |
| Current Job | Director of Business Development |
| Company Name | Atlas Robotics |
| **Years in Position** | **(empty)** |
| **Months in Position** | **(empty)** |
| Has New Position | false |
| Profile Summary | I lead a team that sells to mid-market companies. I care about clean pipeline and honest forecasts. |
| Company Employee Growth 1 Year (%) | 8 |
| Sales Team Size | 9 |

**Right answer (known by code):** nobody knows how long Chloe has been in her role. Don't call it new.

## 2. What `emails.py facts()` passes to the writer

| Field | Value |
|---|---|
| months_in_role | **0** |
| new_in_role | **true** |

Empty tenure becomes 0 months, and 0 < 6, so the writer is told Chloe is new.

## 3. The email the writer wrote

> **Subject:** building your pipeline at atlas robotics?
>
> Hi Chloe,
>
> **Congrats on the Director role at Atlas Robotics.** Leading a team that sells to mid-market means your pipeline needs to be clean from the start.
>
> Evaboot exports LinkedIn Sales Navigator searches to spreadsheets with verified professional emails. Your team gets clean lists in minutes instead of manual copy-paste, and fewer bounces.
>
> Worth a look?

## 4. The three checkers

| Checker | Result |
|---|---|
| Evaboot `emails.py check` (shape: length, links, greeting, clichés) | **PASS**, 0 problems |
| Rules | **FAIL**: "Congrats on the Director role", time in role is missing |
| Claim judge (3 votes) | **FAIL**, see below |

The judge's claims:

| Claim | Label |
|---|---|
| The lead is new to their Director role. | ❌ not in source |
| The lead leads a team that sells to mid-market companies. | ✅ supported |
| Evaboot exports Sales Navigator searches to spreadsheets with verified emails. | ✅ supported |
| The product gives clean lists in minutes, with fewer bounces. | ✅ supported |
| The lead is building their pipeline at Atlas Robotics. | not a claim |
| The lead needs a clean pipeline. | not a claim |

**Verdict (decided in code):** one unsupported claim, so the email fails.

## 5. After the fix (missing tenure stays unknown + truth rules)

`facts()` now passes `months_in_role: null`, `new_in_role: false`. Same lead, new email:

> **Subject:** clean pipeline and honest forecasts
>
> Hi Chloe,
>
> I saw in your profile that you care about clean pipeline and honest forecasts. Leading a team that sells to mid-market companies, you probably know that list quality matters.
>
> Evaboot exports any LinkedIn Sales Navigator search to a clean spreadsheet with verified professional emails. Your team gets clean prospect lists in minutes instead of manual copy-paste, with fewer bounces.
>
> Worth a look?

**Verdict:** pass. Every claim comes from Chloe's data.
