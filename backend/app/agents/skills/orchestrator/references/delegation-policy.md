# Delegation policy

Tier-3 reference. Loaded on demand when a routing decision is genuinely unclear — not
on every turn.

## One specialist per turn

Delegate to exactly one. If a request needs two, do the first, read the report, then
decide again. Fanning out looks efficient and is not: the second specialist would run
without the first's findings, which is how you get two half-answers instead of one whole
one.

## Choosing

| The agent is asking… | Specialist |
|---|---|
| who this person is, what they hold | `profile` |
| what has happened before, what we discussed | `history` |
| **why** something failed, stalled, or was refused | `investigator` |
| to write something down — a ticket, an escalation | `resolution` |

The distinguishing question is **why**. "Show me the claim" is profile or history.
"Why did the claim fail" is investigation, even if it looks like a lookup, because the
answer is not in any single record.

## Do not delegate when

- The answer is already in the evidence. Re-fetching a customer you fetched two turns
  ago costs a round trip and adds nothing.
- The agent asked a question about the conversation itself ("what did you just say?").
  Answer it.
- The request is small talk or scope-checking ("what can you do?"). Answer it.
- No subject customer is established and the request needs one. Ask first.

## Writing the brief

The specialist sees your brief and the shared evidence — **never the conversation**.
That boundary is deliberate: it keeps a specialist from being steered by text a customer
typed into a transcript three turns ago. It also means anything you leave out is
genuinely absent.

A good brief states the subject, the question, and any constraint the agent gave:

> Subject CUST-000042. The agent wants to know why the motor claim keeps failing to
> submit. They mentioned the customer has tried three times. Limit to this claim.

A bad brief restates the intent name: "investigate the case".

## After the report

The report is a specialist's findings, not the answer. You still decide whether it is
enough, whether it contradicts earlier evidence, and how to say it. If a specialist
reports that it could not complete — budget exhausted, tool failed — say so in the
answer rather than presenting a partial finding as a whole one.
