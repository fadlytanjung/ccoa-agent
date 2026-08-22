# 10 — Security

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-056, REQ-060–065, REQ-094
> **Depends on:** [09 — Networking](09-networking.md), [06 — Backend API](06-backend-api.md)

## 1. Purpose

The requirements ask for security to be **documented and justified**. Sections below map onto
its six areas:

| Requirement area | Section | Requirement |
|---|---|---|
| Authentication | §2 | REQ-060 |
| Authorization | §3 | REQ-061 |
| Secrets management | §4 | REQ-062 |
| Service-to-service communication | §5 | REQ-063 |
| Access controls | §6 | REQ-064 |
| Auditability | §7 | REQ-065 |

### 1.1 Threat model in one paragraph

An **internal** tool used by contact-centre employees over authenticated sessions,
reading customer PII and able to create tickets and escalate cases. The adversaries
worth designing against are: an unauthenticated party who finds the URL; an
authenticated agent attempting an action above their role; a prompt-injection payload
embedded in customer-supplied text that the model reads; and a leaked credential. Not
in scope: nation-state actors, physical access, or AWS control-plane compromise.

---

## §2 Authentication  *(REQ-060)*

**Amazon Cognito User Pool**, OIDC Authorization Code with PKCE.

| Aspect | Decision |
|---|---|
| Identity provider | Cognito User Pool (`ap-southeast-1`) |
| Flow | Authorization Code + PKCE — public client, **no client secret** |
| Token transport | `Authorization: Bearer <access token>` |
| Client storage | **In memory only** — never `localStorage` or `sessionStorage` |
| Validation | In the backend, per request, against the pool's JWKS (RS256), cached 1 h |
| Checks | Signature, `iss`, `aud`/`client_id`, `token_use == "access"`, `exp`, `nbf` |
| Password policy | ≥12 characters, upper + lower + digit + symbol |
| MFA | Available; optional for demo users |
| Session | Access token 1 h, refresh 30 d, silent renew before expiry |

**Why Cognito rather than a custom login:** storing password hashes, implementing
reset flows, and rate-limiting credential stuffing are all solved problems that are
easy to get subtly wrong. The managed service also gives group claims for free, which
§3 builds on directly.

**Why validate in the application rather than at the ALB.** ALB's
`authenticate-cognito` action is built for server-rendered apps: its redirect flow is
awkward for XHR and SSE, and it moves an authorisation-relevant decision into
infrastructure where it cannot be unit-tested. Validating in FastAPI keeps the check
testable offline and keeps identity and authorisation in the same layer.

**Failure is closed.** If the JWKS cannot be refreshed after the cache expires,
requests are rejected. Availability is never traded for authentication.

---

## §3 Authorization  *(REQ-061)*

Two layers, both mandatory.

### 3.1 Application — role-based, on Cognito groups

| Group | May do | May not do |
|---|---|---|
| `agent` | All reads; propose and approve **ticket creation** | Escalate cases |
| `supervisor` | Everything `agent` can, plus approve **case escalation** | — |

```python
REQUIRED_GROUP: dict[str, str] = {
    "create_ticket": "agent",
    "escalate_case": "supervisor",
}
```

Four properties make this more than a decorator:

1. **Checked at `commit`, on the resuming actor.** An approval is authorised by whoever
   approved it, not by whoever proposed it ([05](05-langgraph-orchestration.md) §3.7).
2. **Mutating tools are never bound to the model.** They are unreachable except through
   the interrupt gate — the capability is absent from the model's tool list, not merely
   discouraged by a prompt.
3. **Denials are audited.** A `403` writes `outcome='denied'` before returning.
4. **The frontend's checks are cosmetic.** Hiding a button is UX; the backend decides.

Thread ownership is enforced separately: a thread belongs to its creator's `sub`, and
another user's thread returns `404` rather than `403`, so the response does not confirm
existence.

### 3.1a Nobody signs themselves up  *(REQ-061)*

`AllowAdminCreateUserOnly = true` on the user pool. Users are **provisioned**; there is no
self-registration, no sign-up link, and no public route to an account.

Cognito's default is the opposite, and leaving it alone is the kind of omission that reads
as fine until it is not: the hosted UI is on a public domain by construction, so a pool at
its defaults lets anyone who finds that URL create a working account. In this application
an account is not just read access to synthetic records — **every account can spend the
project's model quota**, which makes an open pool a billing exposure as much as a data one.

Three things follow, and each is checkable:

| Property | How it is held |
|---|---|
| No self-registration | `AllowAdminCreateUserOnly=true`, set on create **and re-applied on every run** of `scripts/aws-cognito.sh`, so a pool that drifted is corrected rather than merely reported |
| No account without a group | An account in no group authenticates and is then refused by `require_agent` — a `403` on every route ([06](06-backend-api.md) §3.3) |
| No public route to the app | The ALB is internal and reachable only as a CloudFront VPC origin ([09](09-networking.md)); CloudFront serves the SPA, and the SPA is useless without a token |

`./scripts/aws-cognito.sh --status` reports the first and lists every account that exists.
Adding a tester is a deliberate act: `--add-user someone@example.test [--group supervisor]`.

The alternative — application-managed users with passwords in the project's own database —
was considered and declined. It would mean owning password hashing, credential storage,
reset flows, lockout, and session revocation, all of which Cognito already does and none of
which this project would do better. See [ADR-008](adr/ADR-008-provisioned-identity.md).

### 3.2 Infrastructure — IAM least privilege

Four roles, each scoped to named resources. No `"Resource": "*"` outside AWS-managed
policies.

| Role | Permits | Notably excludes |
|---|---|---|
| `backend-execution` | Pull the backend ECR image; write to its log group; read **the one** Gemini secret ARN | Any other secret |
| `backend-task` | Nothing — the database is local and secrets are injected by the execution role | Every AWS API |
| `frontend-execution` | Pull the frontend image; write to its log group | Secrets Manager entirely |
| `frontend-task` | Nothing | Everything |

The frontend task role has **no permissions at all** — it serves static files and needs
none. Giving it an empty policy rather than omitting the role makes that a stated
intention rather than an accident.

The CI role is separate and described in [11](11-cicd.md).

---

## §4 Secrets management  *(REQ-062)*

One secret exists: the Gemini API key.

| Aspect | Decision |
|---|---|
| Store | AWS Secrets Manager, `ccoa/${environment}/gemini-api-key` |
| Injection | ECS `secrets` block → environment variable at task start |
| Value provisioning | Set **out of band** via `aws secretsmanager put-secret-value` |
| In Terraform | The secret *resource* is managed; its **value never is** |
| In code | `SecretStr`, so it cannot be printed or serialised accidentally |
| Local development | `backend/.env`, git-ignored, `.env.example` documents the shape |
| Rotation | Manual — update the secret, restart the service |

**Why the value is not a Terraform variable.** Terraform writes variable values into
state in plaintext. A key passed as `-var` would sit readable in the S3 state bucket
forever, including in every historical version. Managing the container and setting the
contents separately is the only way to keep the key out of state.

**Where the key must never appear:** git, Terraform state, image layers, task-definition
plaintext `environment`, CloudWatch Logs, error responses, the OpenAPI schema,
frontend bundles.

Guards backing that up:
- `.gitignore` covers `.env`, `*.pem`, `*.key`, `credentials.json`.
- Secret scanning runs in CI on every push ([11](11-cicd.md)).
- `SecretStr` renders as `**********` in any repr, log, or traceback.
- The `secrets` (not `environment`) ECS block keeps the value out of `terraform show`
  and the ECS console.

Cognito IDs, the model name, and the ALB DNS name are **configuration, not secrets** —
they are non-sensitive and are surfaced through `/api/v1/meta`.

---

## §5 Service-to-service communication  *(REQ-063)*

| Path | Transport | Authentication | Authorisation |
|---|---|---|---|
| ALB → task | HTTP, VPC-internal | Network position | Task SG allows the ALB SG only |
| Task → database | n/a — local container file | Process ownership | Filesystem permissions; no network path exists |
| Task → Secrets Manager | HTTPS via **interface VPC endpoint** — never leaves the VPC | SigV4 (execution role) | Resource policy on the named secret ARNs |
| Task → ECR | HTTPS | SigV4 (execution role) | Repository policy |
| Task → CloudWatch Logs | HTTPS | SigV4 (execution role) | Log-group scoped |
| Task → Gemini | HTTPS/TLS 1.3 | API key | Google-side quota |
| Task → Cognito JWKS | HTTPS | None (public keys) | Response signature-verified |

**There is no service-to-service call between our own two services.** The frontend is
a static file server; the SPA calls the API from the browser through the ALB. This
removes an entire class of internal-authentication problem by construction rather than
by control ([09](09-networking.md) §2).

**The ALB-to-task hop is plaintext**, and that is a considered decision rather than an
omission — reasoning in [09](09-networking.md) §4.3.

### 5.1 Prompt injection

Customer transcripts are attacker-influenced text that the model reads. Mitigations:

- **The model cannot mutate anything.** Write tools are not in its tool list, so no
  injected instruction can reach a write path ([05](05-langgraph-orchestration.md) §3.8).
- **`guard` runs before the model** on user input — length caps, control-character
  stripping, known jailbreak markers.
- **Retrieved content is delimited and labelled untrusted** in the prompt; the system
  prompt states that content inside evidence blocks is data, never instruction.
- **Grounding is checked**, so an injected claim that is not in evidence is
  uncited — and CI asserts that answers cite only real refs
  ([05](05-langgraph-orchestration.md) §3.12).

The honest limit: prompt injection is not solved, only bounded. The bound here is that
its worst outcome is a *wrong answer shown to a trained agent alongside the source
records*, not an unauthorised write.

---

## §6 Access controls  *(REQ-064)*

| Layer | Control |
|---|---|
| Network | Private subnets, no public IPs, SG-to-SG rules ([09](09-networking.md) §3) |
| Identity | Cognito JWT required on every `/api/*` route |
| Role | Cognito group claims gate mutating actions |
| Resource | Thread ownership by `sub`; `404` on mismatch |
| AWS IAM | Four least-privilege roles; no `Resource: "*"` |
| Filesystem | Database is a local container file; no shared filesystem to scope |
| Data | Synthetic data only; PII never logged |
| CI/CD | GitHub OIDC, no static AWS keys; environment protection on deploy |

### 6.1 Dependency and supply-chain controls  *(REQ-094)*

Two published CVEs chain into RCE through the LangGraph SQLite checkpointer
([02](02-research.md) §4.2). The checkpoint database is now a **process-local file**
rather than a file on shared network storage, which materially narrows that exposure —
but the version pins and the strict-msgpack flag remain first-order controls, not
advisory hygiene:

| Control | Value | Enforced where |
|---|---|---|
| `langgraph` | `1.2.11` (≥1.0.10) | `pyproject.toml`, lockfile |
| `langgraph-checkpoint-sqlite` | `3.1.1` (≥3.0.1) | `pyproject.toml`, lockfile |
| `LANGGRAPH_STRICT_MSGPACK` | `true` | Task definition + local `.env` |
| Database location | Container-local `/data`, not shared storage | [ADR-005](adr/ADR-005-runtime-and-persistence.md) §3 |
| Litestream binary | Pinned by version **and SHA-256** in the Dockerfile | Third-party supply-chain surface — [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) |
| Replication bucket | SSE-S3, versioned, public access blocked, task-role scoped to one prefix | [08](08-infrastructure.md) §3.2 |
| Container user | Non-root, owns `/data` only | `Dockerfile` |

Plus, in CI: `pip-audit` and `npm audit` on every build, Trivy image scanning with a
build-failing threshold at HIGH, ECR scan-on-push, and Dependabot for updates.

---

## §7 Auditability  *(REQ-065)*

### 7.1 The audit log

Every mutating tool call writes exactly one `audit_log` row **inside the same
transaction as the mutation** ([04](04-data-model.md) §3.4). An approved-but-unlogged
write is not representable in the code path.

| Column | Example |
|---|---|
| `trace_id` | `01J8XQ2R7B4K…` |
| `thread_id` | `th_01J8XQ…` |
| `actor_sub` / `actor_email` / `actor_groups` | Cognito `sub`, email, `["agent"]` |
| `action` | `create_ticket` |
| `target_type` / `target_id` | `ticket` / `TKT-000123` |
| `outcome` | `allowed` \| `denied` \| `failed` |
| `detail` | Approval note; denial reason |
| `occurred_at` | ISO-8601 UTC |

Denials and failures are recorded, not only successes — an audit log containing only
successes cannot answer "did anyone try?".

### 7.2 Correlation

One `trace_id` is minted at the HTTP edge, threaded through the graph config, attached
to every log line and every audit row, and returned in the `X-Trace-Id` header and in
error bodies. Given a `trace_id` from a user's screenshot, the full path is
reconstructible: request → intent → tools called → approval → write.

### 7.3 Logging discipline

| Logged | Never logged |
|---|---|
| `trace_id`, `thread_id`, actor `sub` | Message content |
| Node name, tool name, duration, outcome | Customer name, email, phone, address |
| Entity IDs (`CUST-…`, `TKT-…`) | Transcripts or summaries |
| Token usage, model ID | The Gemini API key |
| Errors and status codes | Full request or response bodies |

Actor `sub` is logged rather than email: it identifies the user for correlation without
putting an email address in a log stream.

### 7.4 Platform-level audit

| Source | Records | Retention |
|---|---|---|
| CloudWatch Logs | Application logs, both services | 7 days |
| CloudTrail | AWS API calls (account default) | 90 days |
| ECS deployment events | Task lifecycle | AWS default |
| GitHub Actions | Who deployed what, when, from which commit | Repository history |
| Cognito | Sign-in events | Pool default |

Application audit lives in `audit_log`, not CloudWatch — it must be queryable and
joinable against business data, and it must survive independently of log retention.

---

## 8. Known limitations

Stated plainly rather than left for someone else to find.

| # | Limitation | Impact | Would be fixed by |
|---|---|---|---|
| 1 | **No TLS certificate yet** — the ALB may serve HTTP | Bearer tokens could cross the internet in the clear. **Blocking for a real demo** | Owned domain + ACM, or CloudFront ([08](08-infrastructure.md) §6) |
| 2 | Transcripts leave the VPC to a third-party API | Acceptable only because data is synthetic | Bedrock + VPC endpoint, or Vertex AI + PSC |
| 3 | Coarse egress control (port 443 to anywhere) | Limited exfiltration resistance | Network Firewall FQDN allowlist (~$0.395/hr) |
| 4 | No WAF | No rate limiting or managed rules | ~$0.0075/hr + per-request |
| 5 | Manual secret rotation | Long-lived key | Secrets Manager rotation Lambda |
| 6 | Prompt injection bounded, not solved | Possible wrong answer, never an unauthorised write | Ongoing; §5.1 |
| 7 | No MFA enforcement on demo users | Weaker account security | Cognito policy change |
| 8 | ALB → task plaintext | Single VPC-internal hop | End-to-end TLS with per-task certificates |
| 9 | Audit log has no integrity protection | A database writer could alter history; replication copies the alteration | S3 Object Lock on an append-only export |

Items 1 and 2 are the ones that matter. The rest are cost decisions appropriate to an
ephemeral demo on synthetic data.

## 9. Open questions

1. **Resolve TLS before any demo with a real login.** Limitation 1 is not acceptable
   for a system whose security story rests on Bearer tokens.
2. **Enforce MFA on the `supervisor` group?** Cheap, and it makes the privilege
   distinction more than nominal.
3. **Export `audit_log` to S3 with Object Lock at teardown?** It would make the audit
   trail survive `terraform destroy`, which is arguably what an audit trail is for.
