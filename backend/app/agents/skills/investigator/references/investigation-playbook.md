# Investigation playbook

Tier-3 reference. The shape of an investigation that reaches an answer inside budget.

## The standard path

Most claim investigations are five calls or fewer:

```
list_claims(customer, status="submission_failed")   → which claim
get_claim(claim_id)                                 → the code and detail
search_kb(code)                                     → the documented remediation
list_interactions(customer, limit=5)                → what they already tried
list_cases(customer, status="open")                 → is this already known
```

If you are past call six, you are not investigating a claim problem — re-read the brief.

## Order matters

**Code before history.** The failure code tells you what to look for in the
interactions. Reading five transcripts first and then discovering the code is
`GATEWAY_TIMEOUT` wastes most of the budget.

**History before recommendation.** The knowledge base tells you the documented fix. The
interactions tell you whether it has already been tried. Recommending the documented fix
to someone on their fourth attempt is the single most common way this goes wrong.

**Case last.** It changes who acts, not what happened.

## Reading the interaction history

You are looking for three things:

1. **How many attempts.** Stated by the customer, visible as repeated contacts.
2. **What advice was already given.** If a colleague already told them to re-photograph
   the document, repeating it is not help.
3. **Whether the story is consistent.** A customer describing a login failure on a claim
   with `DOC_UNREADABLE` may have two separate problems.

## When the evidence disagrees

The record wins on facts; the customer wins on experience.

If the claim shows one submission and the customer says three, both can be true — two
attempts may have failed before creating a claim at all. Report the discrepancy rather
than resolving it silently in either direction.

## When there is nothing to find

A customer with no failed claims is a complete answer. Say what you searched and what
was there — do not widen the search until something turns up. Broadening from "failed
claims" to "all claims" to "all interactions" until something looks relevant is how an
investigation produces a confident answer to a question nobody asked.

## What a finished investigation looks like

- **What failed** — the claim reference and its status.
- **Why** — the code, in plain language, with what the knowledge base says causes it.
- **What they have already tried** — with interaction refs.
- **What to do next** — the documented remediation, or a ticket if remediation has
  already failed.

If you cannot fill the "why" line from evidence, the investigation is not finished, and
saying so is the correct outcome.
