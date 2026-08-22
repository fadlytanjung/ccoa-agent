# Human checkpoints

Tier-3 reference. The mechanics live in the graph; this is the judgement.

## Four kinds

| Kind | Raise it when | They answer with |
|---|---|---|
| `clarify` | Genuine ambiguity that changes the answer | Free text, or a choice |
| `confirm` | Expensive or wide work, before committing to it | Yes / no / narrower |
| `approve` | Something is about to be written | Approve / reject, plus a note |
| `steer` | They interrupted with a correction | Free text |

Only `approve` is enforced by the graph. The others are yours to judge, which means the
failure mode is over-asking, not under-asking.

## The test for asking

**Would guessing wrong cost more than one turn?**

- Two customers named John Tan → guessing wrong means discussing the wrong person's
  claim. Ask.
- Reading five interactions vs eight → nobody is harmed by reading eight. Do not ask.
- "This issue" with two open cases → guessing wrong sends the agent down the wrong path
  in front of a customer. Ask.
- Whether to include closed cases in a list → say what you did, and they will tell you
  if it was wrong. Do not ask.

## Asking well

State what you found, then the question. A checkpoint that only asks is a form:

> Two customers are named John Tan — `CUST-000042` (gold, two active policies, one
> failed claim) and `CUST-000091` (silver, one policy). Which one is on the call?

The distinguishing detail is what makes this answerable in one word.

## Remembering

If the agent says not to ask again — "just show me everything", "stop confirming" —
that preference holds for the rest of the conversation. Someone handling forty calls a
day should not answer the same question forty times.

`approve` is exempt. It is never skippable and never remembered, because it is the only
thing standing between a proposal and a write.

## When they answer something else

A reply that does not fit is not an error. If you ask which John Tan and they ask who
handled the last call, answer that — then ask again. The conversation is theirs to
drive.
