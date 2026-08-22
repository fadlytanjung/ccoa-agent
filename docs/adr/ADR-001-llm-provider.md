# ADR-001 — Google Gemini rather than Amazon Bedrock

> **Status:** Accepted
> **Date:** 2026-08-21
> **Related:** [02 — Research](../02-research.md) §2–3, [09 — Networking](../09-networking.md) §5.2

## Context

The application must be deployed on AWS, so Amazon Bedrock was the first-choice model
provider: VPC-private via an interface endpoint, IAM-authenticated, no API key to
manage, and no internet egress. That would have been the strongest posture for a system
handling sensitive customer information (REQ-056).

Three findings, all verified against the live account, made it unworkable.

## Findings

**1. Model access is not granted.** Every Anthropic model in `ap-southeast-1` returns:

```
authorizationStatus: NOT_AUTHORIZED
agreementAvailability: { status: NOT_AVAILABLE }
```

Invocation confirms it — `ValidationException: Operation not allowed`. This is fixable
without the console (`create-foundation-model-agreement`, `put-use-case-for-model-access`
are both available in the installed CLI), but doing so **accepts a vendor EULA on the
account owner's behalf**, which is not a decision to make unilaterally.

**2. Current models are global-routed only.** In `ap-southeast-1`, `apac.*` inference
profiles stop at Claude Sonnet 4; Sonnet 5, Opus 5, and Haiku 4.5 exist only as
`global.*` profiles, which may route inference outside APAC. For an application the
requirements describe as handling sensitive customer information, that is a genuine
residency concern — the alternative being an older model with weaker tool-calling.

**3. Embeddings are Cohere-only in-region.** No Titan embedding models are available, so
a Bedrock design would pair an Anthropic generation model with a Cohere embedding model,
needing two separate access grants.

## Decision

**Use the Google Gemini Developer API.** `gemini-3.5-flash` for generation,
`gemini-embedding-001` for embeddings ([02](../02-research.md) §3.1). Both stable, both
from one provider, one credential.

The model is reached through a single adapter module (`services/llm.py`), so switching
providers is a change to one file rather than a redesign.

## Consequences

**Good**
- No blocked dependency — the system can be built and run today.
- Strong tool-calling at low cost; `langchain-google-genai` integrates directly with
  LangGraph's `ToolNode`.
- One provider for generation and embeddings.
- `ChatGoogleGenerativeAI` can target Vertex AI instead, which is the escape hatch if
  residency requirements later force the workload into GCP `asia-southeast1`.

**Bad — and this is the real cost**
- **The backend now requires public internet egress**, which forces NAT into the network
  design ([09](../09-networking.md) §5.2). Bedrock behind a VPC endpoint would have meant
  *zero* internet egress and no NAT at all.
- Interaction transcripts leave the VPC to a third party. Acceptable **only** because
  every record is synthetic ([12](../12-seed-data.md)).
- An API key to store and rotate, where Bedrock would have used IAM.

**Revisit if:** model access is granted and an `apac.*` profile exists for a
current-generation model. That flips the network design favourably — endpoints
everywhere, NAT deleted, no internet egress ([09](../09-networking.md) §6.5).
