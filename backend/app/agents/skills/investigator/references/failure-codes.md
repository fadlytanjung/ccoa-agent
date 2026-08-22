# Claim failure codes

Tier-3 reference. Read this when you encounter a code you cannot interpret from the
knowledge-base article alone.

A claim in `submission_failed` carries **exactly one** code, set by the validation
service at the point of rejection. `failure_detail` sometimes names the specific field
or document.

| Code | What actually happened | Whose problem |
|---|---|---|
| `DOC_MISSING` | No document reached us for a submission that requires one | Customer-side, usually an abandoned upload |
| `DOC_UNREADABLE` | A document arrived but text extraction failed | Customer-side, but often our capture guidance |
| `POLICY_LAPSED` | The incident date falls outside the policy's effective period | Depends — check for a failed renewal payment |
| `DUPLICATE` | A submission matching an existing one was rejected | Usually a retry after a timeout, so arguably ours |
| `VALIDATION_ERROR` | A required field is missing or inconsistent | Customer-side; `failure_detail` names the field |
| `GATEWAY_TIMEOUT` | The upstream assessment gateway did not respond | **Ours.** Never present this as a customer error |
| `LIMIT_EXCEEDED` | The amount exceeds the remaining benefit limit | Neither — a policy fact |

## Distinctions that matter

**`DOC_MISSING` vs `DOC_UNREADABLE`.** Missing means nothing arrived; unreadable means
something did. The advice is different, and telling a customer to re-upload a document
they never successfully uploaded wastes their time.

**`DUPLICATE` is usually our fault.** A customer who submitted once, saw a timeout, and
submitted again did what any reasonable person would. Find the original reference and
give it to them rather than explaining deduplication.

**`POLICY_LAPSED` needs one more check.** If the lapse followed a renewal payment we
failed to collect or failed to notify on, the coverage gap is a billing problem, not a
claims one. Look for a billing case or a failed payment in the same period before
telling someone they were uninsured.

**`submission_failed` is not `rejected`.** A failed submission never reached assessment.
A rejected claim was assessed and declined, has a stated reason, and has an appeal
route. Conflating them tells a customer their claim was refused when it was never
actually looked at.

## Attempt counts

`failure_detail` sometimes records how many attempts have failed, and prior interactions
always show it. Three or more failed attempts changes the recommendation from "try
again with better guidance" to "raise a ticket" — at that point the guidance has already
been given and has not worked.
