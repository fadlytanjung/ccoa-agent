# 02 — Research

> **Status:** Approved
> **Gathered:** 2026-08-21
> **Method:** live AWS account queries, PyPI metadata, vendor documentation. Every
> figure below was checked; nothing here is quoted from memory.

This document is the evidence base for the design decisions in the rest of `docs/`.
When a later spec asserts a price, a model ID, or a version, it is because of something
recorded here.

---

## 1. AWS environment survey

The target account was surveyed before design. The deploying principal holds
administrator-equivalent permissions in the target account.
Default region: `ap-southeast-1` (Singapore).

The account is effectively **green-field** in this region:

| Resource | Finding | Consequence |
|---|---|---|
| VPCs | Only the default `vpc-0xxxxxxxxxxxxxxxx` (`172.31.0.0/16`) | We build our own VPC; `10.0.0.0/16` avoids any overlap |
| ECS clusters | None | No naming collisions |
| NAT gateways | None running | No inherited spend; `terraform destroy` returns to $0 |

`terraform destroy` therefore genuinely returns the account to its prior state, which
is what makes the ephemeral posture in [ADR-004](adr/ADR-004-ephemeral-infrastructure.md)
safe to rely on.

### 1.1 Local toolchain gaps

Checked on the workstation that will run `terraform apply`:

| Tool | Installed | Required action |
|---|---|---|
| `terraform` | **not installed** | Install **≥1.11** before [08](08-infrastructure.md) can be executed. 1.11 is the floor, not 1.9: native S3 state locking (`use_lockfile`) landed in 1.10 and deprecated `dynamodb_table` in 1.11, which is what lets this project avoid DynamoDB entirely ([18](18-aws-access-and-manual-steps.md) §4) |
| `aws` CLI | 2.27.43 | Lacks the `s3vectors` command — only matters if S3 Vectors is adopted ([13](13-vector-search.md)) |
| `boto3` | 1.39.4 | No `s3vectors` client; same caveat |
| `docker` | 29.6.2 | OK |
| `node` / `npm` | 22.16.0 / 10.9.2 | OK |
| `python3` | 3.12.11 | OK — matches the backend target |
| `uv` | 0.8.0 | OK |
| `gh` | 2.82.1 | OK — used for CI/CD setup |

---

## 2. Amazon Bedrock — evaluated and rejected

Bedrock was the first-choice LLM path (VPC-private, IAM-authenticated, no API key to
manage). It was rejected for this build. The evidence:

### 2.1 Model access is not granted

```
$ aws bedrock get-foundation-model-availability \
    --region ap-southeast-1 --model-id anthropic.claude-sonnet-5
{
    "modelId": "anthropic.claude-sonnet-5",
    "agreementAvailability": { "status": "NOT_AVAILABLE" },
    "authorizationStatus": "NOT_AUTHORIZED",
    "entitlementAvailability": "AVAILABLE",
    "regionAvailability": "AVAILABLE"
}
```

The same result returns for every Anthropic model tested, including
`anthropic.claude-3-5-sonnet-20241022-v2:0`. Invocation confirms it:

```
$ converse(modelId="global.anthropic.claude-sonnet-5")
ValidationException: Operation not allowed
```

This is **fixable without the console** — the installed CLI exposes
`create-foundation-model-agreement`, `put-use-case-for-model-access`, and
`list-foundation-model-agreement-offers`. It was **not executed**, because accepting a
model agreement is accepting a vendor EULA on the account owner's behalf.

### 2.2 Only global inference profiles for current models

Models listed in `ap-southeast-1` and their available inference profiles:

| Model | `apac.*` profile | `global.*` profile |
|---|---|---|
| Claude Sonnet 5, Opus 5, Fable 5, Haiku 4.5, Sonnet 4.6, Opus 4.6/4.7/4.8 | ✗ | ✓ |
| Claude Sonnet 4, Claude 3.5 Sonnet, Claude 3 Haiku | ✓ | partial |

Current-generation models are reachable **only** through `global.*` profiles, which
may route inference outside APAC. For an application the requirements describe as handling
*sensitive customer information*, that is a genuine residency concern; the alternative
is pinning to Claude Sonnet 4 via `apac.*` and accepting weaker tool-calling.

### 2.3 Embeddings are Cohere-only in this region

```
$ aws bedrock list-foundation-models --region ap-southeast-1 \
    --query 'modelSummaries[?contains(outputModalities, `EMBEDDING`)]'
cohere.embed-v4:0, cohere.embed-english-v3, cohere.embed-multilingual-v3
```

No Amazon Titan embedding models. A Bedrock-based vector design would mix an Anthropic
generation model with a Cohere embedding model, and both would need separate access
grants.

### 2.4 Decision

**Gemini Developer API instead of Bedrock.** Recorded in
[ADR-001](adr/ADR-001-llm-provider.md). The Bedrock path stays documented so the
swap is a configuration change rather than a redesign — the LLM is reached through a
single adapter module ([05](05-langgraph-orchestration.md) §Model binding).

The cost of this choice is honest and worth stating: the backend now needs **egress to
the public internet**, which forces a NAT gateway into the network design ([09](09-networking.md) §5).
Bedrock via a VPC interface endpoint would have kept all traffic inside AWS.

---

## 3. Google Gemini

### 3.1 Model IDs

**Re-verified 2026-08-22** against `GET /v1beta/models` on the live API key, which is
stronger evidence than the documentation page: it lists what this account can actually
call.

| Role | Model ID | Stability |
|---|---|---|
| **Default agent model** | `gemini-3.5-flash` | Stable |
| Cheaper alternative | `gemini-3.5-flash-lite` | Stable |
| Previous default | `gemini-3.6-flash` | Stable |
| Newest flash | `gemini-3.7-flash` | Stable |
| Literal "Gemini 3 Flash" | `gemini-3-flash-preview` | **Preview only** |
| **Embeddings** | `gemini-embedding-001` | Stable |
| Newer embeddings | `gemini-embedding-2` | Stable |

`gemini-3.5-flash` is the default. *(Amended 2026-08-22 — the default was
`gemini-3.6-flash`; changed to reduce per-token cost.)* Within one family, an earlier
minor version is cheaper, and the flash tier already has the tool-calling strength this
graph depends on.

Two findings worth recording, because both shape the choice:

- **There is no stable `gemini-3-flash`.** The only listed ID is
  `gemini-3-flash-preview`. Preview IDs are avoided throughout — a preview can be
  withdrawn without notice, and a broken demo is worse than a slightly weaker model.
  So "Gemini 3 Flash" resolves to `gemini-3.5-flash` in practice.
- **`gemini-3.5-flash-lite` is cheaper still**, and is a one-variable change
  (`GEMINI_MODEL`). It is not the default because the lite tier is measurably weaker at
  multi-step tool selection, which is the whole investigation loop
  ([05](05-langgraph-orchestration.md) §3.5). Worth revisiting once real traces exist.

> **Prices remain `[UNVERIFIED]`.** Model *availability* and *stability* were confirmed
> from the live API; per-token rates were not, and the relative ordering above is
> inferred from Google's tier naming rather than measured. The backend records token
> usage per run so spend is measured, not predicted — [16](16-cost-model.md) §3.6.

> Published per-token prices for the 3.x family vary across secondary sources and were
> **not** independently confirmable from Google's own pricing page during this survey.
> The cost model in [16](16-cost-model.md) therefore treats LLM spend as a measured
> quantity — the backend records token usage per run — rather than a predicted one.
> Marked `[UNVERIFIED]` there.

### 3.2 Integration library

`langchain-google-genai` **4.3.4**. From version 4.0.0 the package moved onto the
consolidated `google-genai` SDK. `ChatGoogleGenerativeAI.bind_tools()` provides the
tool-calling surface LangGraph's `ToolNode` expects, and the same class can target
either the Developer API or Vertex AI — which is the escape hatch if residency
requirements later force the workload into GCP's Singapore region.

### 3.3 Consequence for the network design

The Gemini Developer API is reached at a public Google endpoint. Backend tasks sit in
private subnets, so they require NAT egress. Because the destination is a large,
shifting set of Google IP ranges, an IP allowlist is not practical; egress restriction
options and their costs are analysed in [09](09-networking.md) §5.

---

## 4. LangGraph

### 4.1 Pinned versions

Resolved from PyPI on 2026-08-21:

| Package | Version | Requires |
|---|---|---|
| `langgraph` | 1.2.11 | Python ≥3.10 |
| `langgraph-checkpoint-sqlite` | 3.1.1 | Python ≥3.10 |
| `langgraph-cli` | 0.4.31 | Python ≥3.10 |
| `langchain-core` | 1.6.0 | Python ≥3.10 |
| `langchain-google-genai` | 4.3.4 | Python ≥3.10 |
| `google-genai` | 2.19.0 | Python ≥3.10 |
| `fastapi` | 0.141.1 | Python ≥3.10 |
| `sqlite-vec` | 0.1.9 | — |

### 4.2 Security — two chained CVEs

Two 2026 vulnerabilities chain into remote code execution through the checkpointer:

| CVE | Component | Nature |
|---|---|---|
| CVE-2025-67644 | SQLite checkpointer | SQL injection |
| CVE-2026-28277 | Checkpoint deserialisation | Unsafe `msgpack` deserialisation |

Together they mean a compromised checkpoint database can execute code in the backend
process. Three mitigations are **mandatory**, not advisory, and are enforced in
[10](10-security.md):

1. `langgraph >= 1.0.10` — we pin **1.2.11**.
2. `langgraph-checkpoint-sqlite >= 3.0.1` — we pin **3.1.1**.
3. `LANGGRAPH_STRICT_MSGPACK=true` in every environment that constructs a
   checkpointer, or an explicit `allowed_msgpack_modules` allowlist.

This is directly relevant here because the checkpoint database is a **file**, not a
private in-process store — any principal that can write that file can reach the
deserialiser.

> **Amended 2026-08-22.** This section originally reasoned about the file living on a
> shared EFS volume. [ADR-005](adr/ADR-005-runtime-and-persistence.md) removed EFS: both
> databases are now local container files replicated to S3 by Litestream
> ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)). That **narrows** the attack surface
> — the file is reachable only from inside the one task that owns it, and the S3 replica
> is not a mount — but it does not remove the requirement. All three mitigations above
> remain mandatory, because the deserialiser still runs against a file that a compromised
> process could rewrite.

Source: [Check Point Research — *From SQLi to RCE: Exploiting LangGraph's Checkpointer*](https://research.checkpoint.com/2026/from-sqli-to-rce-exploiting-langgraphs-checkpointer/).

### 4.3 `langgraph dev` and the checkpointer

`langgraph dev` (from `langgraph-cli[inmem]`) runs an in-memory Agent Server on
`127.0.0.1:2024` and opens LangGraph Studio at
`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`.

The decisive detail for our design, from LangChain's persistence documentation:

> "When using the Agent Server, you do not need to implement or configure checkpointers
> or stores manually. The server handles persistence infrastructure behind the scenes."

So the graph **must not** hard-wire a checkpointer: under Studio the server supplies
one, under FastAPI we supply `AsyncSqliteSaver`, and under test we supply
`MemorySaver`. This is the origin of the `build_graph(checkpointer=None)` rule in
[00](00-constitution.md) §7, and the full mechanism is specified in
[14](14-local-dev.md).

### 4.4 Human-in-the-loop API

Confirmed current import path for LangGraph 1.x:

```python
from langgraph.types import interrupt, Command
```

`interrupt()` durably pauses a run; `Command(resume=...)` continues it. Durability is
supplied by the checkpointer, which is why REQ-091 (state survives restart) and
REQ-015 (human-in-the-loop) are the same underlying mechanism.

---

## 5. Datastore constraints

### 5.1 SQLite on EFS — evaluated and rejected

EFS was the original persistence path: a network filesystem mounted into the Fargate
task, so the database outlives the container. Two constraints were verified, and both
were load-bearing enough to reject it:

- **WAL mode is unusable over NFS.** SQLite's WAL requires a shared-memory `-shm` file
  accessed via `mmap`, which NFS does not support. The database would have had to run
  `journal_mode = TRUNCATE` (or `DELETE`) with a generous `busy_timeout` — measurably
  slower, and it forecloses Litestream, which requires WAL.
- **Single writer only.** Concurrent writers over NFS risk corruption, pinning the
  backend service to one task.

> **Amended 2026-08-22.** EFS is **not used**. Both databases are local container files
> replicated to S3 by Litestream and restored on boot
> ([ADR-005](adr/ADR-005-runtime-and-persistence.md), [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)).
> The findings above are why: a local filesystem makes `journal_mode = WAL` valid, and
> WAL is precisely what Litestream replicates. The single-writer bound survives the
> change — but now because Litestream corrupts with more than one writer, not because of
> NFS. `max_capacity = 1` is unchanged and still a correctness constraint.

These are not defects to hide; they are the reason [15](15-datastore-options.md)
exists and why DynamoDB is documented as the scale-out path.

### 5.2 Amazon S3 Vectors

Considered for the nice-to-have vector store. Generally available since December 2025,
expanded to 17 further regions in March 2026, up to 2 billion vectors per index.
Published rates: **$0.06/GB-month** storage and **$0.20/GB** PUT, with query charges
per API call plus a $/TB component. Query latency is around 100 ms for
frequently-queried indexes.

It is the cheapest managed vector option by a wide margin. It is **not** adopted for
this build, for two reasons: the local `aws` CLI and `boto3` are both too old to expose
the `s3vectors` client (§1.1), and it would add a second datastore for a nice-to-have.
`sqlite-vec` in the existing volume costs nothing and behaves identically on a laptop
and in AWS. Reasoning in [13](13-vector-search.md).

---

## 6. Verified AWS pricing — `ap-southeast-1`

Queried from the AWS Pricing API (`us-east-1` endpoint, `location = Asia Pacific (Singapore)`)
on 2026-08-21. These are on-demand list rates in USD, exclusive of tax.

| Resource | Rate | Notes |
|---|---|---|
| Fargate vCPU (**ARM/Graviton**) | **$0.04045** / vCPU-hour | `APS1-Fargate-ARM-vCPU-Hours` |
| Fargate memory (**ARM/Graviton**) | **$0.00442** / GB-hour | `APS1-Fargate-ARM-GB-Hours` |
| Fargate vCPU (x86) | $0.05056 / vCPU-hour | `APS1-Fargate-vCPU-Hours` |
| Fargate memory (x86) | $0.00553 / GB-hour | `APS1-Fargate-GB-Hours` |
| NAT Gateway | **$0.059** / hour | `APS1-NatGateway-Hours`, plus per-GB processing |
| Application Load Balancer | **$0.0252** / hour | `LoadBalancing:Application` |
| ALB capacity units | $0.008 / LCU-hour | Negligible at demo traffic |
| EFS Standard storage | $0.36 / GB-month | `APS1-TimedStorage-ByteHrs` |

Two findings that changed the design:

1. **ARM64 Fargate is ~20% cheaper than x86** on both vCPU and memory. Both a Python
   backend and an nginx frontend build cleanly for `linux/arm64`, so
   [08](08-infrastructure.md) specifies `ARM64` task architecture. This is free money.
2. **NAT Gateway in Singapore is $0.059/hour**, appreciably higher than the
   us-east-1 rate often quoted from memory. At $1.42/day it is the single largest
   line item in the demo footprint, which is what justifies the ephemeral posture
   rather than an always-on environment.

Full build-up in [16](16-cost-model.md).

---

## 7. Open items

| Item | Owner | Blocking |
|---|---|---|
| Gemini API key to be supplied and stored in Secrets Manager | Account owner | Backend integration |
| Install Terraform **≥1.11** on the deploying workstation | The engineer holding `ccoa-bootstrap` ([18](18-aws-access-and-manual-steps.md)) | `terraform apply` |
| Confirm Gemini per-token pricing from Google's official pricing page | — | Accuracy of [16](16-cost-model.md) only |
| Decide whether to enable Bedrock model access for the documented fallback | Account owner | Nothing — fallback is optional |

---

## Sources

- [Check Point Research — From SQLi to RCE: Exploiting LangGraph's Checkpointer](https://research.checkpoint.com/2026/from-sqli-to-rce-exploiting-langgraphs-checkpointer/)
- [LangGraph persistence — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Run a local server — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/local-server)
- [ChatGoogleGenerativeAI integration — Docs by LangChain](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai)
- [Gemini API models — Google AI for Developers](https://ai.google.dev/gemini-api/docs/models)
- [Amazon S3 Vectors is now generally available](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-s3-vectors-generally-available/)
- [Amazon S3 Vectors expands to 17 additional AWS Regions](https://aws.amazon.com/about-aws/whats-new/2026/03/s3-vectors-expands-17-regions)
- [Working with S3 Vectors and vector buckets — AWS documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html)
- [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/)
- [langgraph-checkpoint-sqlite — PyPI](https://pypi.org/project/langgraph-checkpoint-sqlite)
