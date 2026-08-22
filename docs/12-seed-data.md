# 12 — Seed data

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-030–034, REQ-020–023, REQ-034
> **Depends on:** [04 — Data model](04-data-model.md), [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)

## 1. Purpose

How the synthetic corpus is generated: volumes, realism, determinism, and the planted
scenarios that make the reference prompts work verbatim. Also defines the **seed
version**, which namespaces the Litestream S3 prefix.

## 2. Scope

**In scope:** volumes, generator design, determinism, planted scenarios, realism rules,
build-time generation, seed versioning, verification.

**Out of scope:** schema ([04](04-data-model.md)), embeddings ([13](13-vector-search.md)),
datastore choice ([15](15-datastore-options.md)).

---

## 3. Design

### 3.1 Volumes

The requirements ask for at least 100 records. Customers are the anchor at **120**;
everything else follows from realistic ratios.

Counts below are **exact**, not approximate — the generator is deterministic, so
`SEED = 20260821` produces these numbers every time. `tests/unit/test_seed.py` asserts
them, which is how a change to a ratio becomes a visible decision rather than a drift.

| Entity | Count | Ratio |
|---|---|---|
| `customer` | **120** | — |
| `policy` | 213 | 1–3 per customer |
| `claim` | 173 | 0–3 per policy holder, ~15% of customers have none |
| `interaction` | **608** | 3–12 per customer, long-tailed |
| `case` | 89 | ~1 per 7 interactions |
| `ticket` | 145 | 0–3 per case, some standalone |
| `case_event` | 309 | 2–5 per case |
| `ticket_event` | 353 | 1–4 per ticket |
| `kb_article` | 40 | Covers every `failure_code` |
| **Total rows** | **2,050** | |

Interactions dominate deliberately: the reference scenarios are *review previous
interactions* and *investigate an issue*, and both are only meaningful against a
history with enough noise that finding the signal is real work.

Total on-disk size is roughly **8–12 MB**, which is what makes in-container SQLite and
S3 replication cheap ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)).

### 3.2 Determinism

**The same seed produces byte-identical data.** This is not a nicety — it is what makes
grounding tests assertable, demos repeatable, and the S3 restore-versus-seed rule
(§3.6) coherent.

```python
SEED = 20260821
rng = random.Random(SEED)     # one instance, threaded through every choice
```

Rules that keep it deterministic:

- **No `datetime.now()` anywhere in generation.** Timestamps are offsets from a fixed
  `EPOCH = 2026-08-21T00:00:00Z`. A generator that used wall-clock time would produce a
  different corpus on every build and break the seed-version contract.
- **No unseeded `uuid4()`.** All identifiers are sequential and derived (§3.3).
- **No global `random`.** A single `random.Random(SEED)` instance is passed through the
  generator, so nothing else in the process — a test, a library — can perturb the
  sequence by drawing from the shared global RNG.
- **Ordered iteration.** Dictionaries are iterated in insertion order; sets are sorted
  before use.
- **No `Faker`.** *(Amended 2026-08-22 — this originally specified `Faker("en_SG")`.)*
  Faker is deterministic for a **pinned version only**: its locale providers change
  between releases, so a routine dependency bump would silently alter the corpus and
  trip the `SEED_VERSION` digest check (§3.6) with no code change to point at. Names,
  streets, and cities are now fixed pools in `app/seed/content.py` — auditable, diffable,
  and immune to an upstream data change. It also keeps a dependency out of the image
  build. The cost is a smaller variety of surnames, which for a 120-row corpus reads as
  more realistic rather than less.

CI asserts determinism by generating twice and comparing SHA-256 of the sorted row
dump. A non-deterministic generator fails the build.

### 3.3 Identifiers

Sequential, not random, so they are stable across runs and readable in a demo:

```
CUST-000001 … CUST-000120
POL-00000001 … , CLM-00000001 … , INT-00000001 … ,
CASE-000001 … , TKT-000001 … , KB-0001 …
```

Live ticket creation continues the sequence from the seeded maximum, so a ticket created
during a session is visibly the next number rather than an outlier.

### 3.4 Planted scenarios

The reference prompts must work **exactly as written**, with no rephrasing. That
requires planting specific records rather than hoping the generator produces something
suitable.

| Prompt | Requires | Planted |
|---|---|---|
| *"Show me the details for customer John Tan."* | A customer named John Tan | `CUST-000042` — **John Tan**, gold tier, 2 active policies |
| *"Summarize previous interactions for customer John Tan."* | A history worth summarising | 7 interactions across voice, chat, email, spanning 90 days, mixed sentiment |
| *"Customer reports a failed claim submission. Help me investigate."* | A failed claim with a diagnosable cause | `CLM-00000117` — status `submission_failed`, `failure_code = DOC_UNREADABLE`, 3 attempts |
| *"Create a support ticket for this issue."* | An open case with no ticket yet | `CASE-000008` — `claim_issue`, high, `investigating`, **zero tickets** |

**A second John Tan is planted deliberately.** `CUST-000091` is also named John Tan —
silver tier, different policies, no failed claim. This is not noise: it forces the
`clarify` human-checkpoint path ([05](05-langgraph-orchestration.md) §3.7) on the very
first reference prompt, so disambiguation is demonstrated rather than described. The
richer customer is the one an agent would want, but the system must **ask**, not guess.

The investigation chain is planted end to end so the multi-step workflow has something
real to find:

```
CUST-000042  John Tan
  └── POL-00000073  motor, active
        └── CLM-00000117  submission_failed / DOC_UNREADABLE
              └── CASE-000008  claim_issue, high, investigating, no ticket
                    ├── INT-00000391  chat  "upload keeps failing"
                    ├── INT-00000402  voice "third attempt, still rejected"
                    └── INT-00000418  email "sending photos instead"
KB-0031  "Resolving DOC_UNREADABLE claim upload failures"
```

An investigation that follows the evidence reaches `KB-0031` and can propose a grounded
remediation — which is the difference between an agent that summarises and one that
helps.

### 3.5 Realism rules

Uniform random data makes an assistant look good for the wrong reasons. These rules
introduce the structure a real corpus has:

| Rule | Why |
|---|---|
| Interaction volume is **long-tailed** — most customers 3–4, a few 12+ | Exercises the `confirm` checkpoint on wide reads |
| Sentiment correlates with claim status — failed claims skew negative | Summaries have something to detect |
| Interactions **cluster in time** around case activity | Chronology carries signal |
| ~15% of customers have **zero** claims | "Not found" is a correct answer that must be exercised |
| Transcripts are **capped at ~2 KB** | Keeps context and file size bounded ([04](04-data-model.md) §6) |
| `failure_code` distribution is **skewed**, not uniform | `DOC_UNREADABLE` and `DOC_MISSING` dominate, as in reality |
| Every `failure_code` has a matching KB article | Investigation always has a reachable answer |
| ~8% of cases are `escalated` | The supervisor path has existing examples |
| Handler names drawn from a **fixed pool of 12** | Looks like a real team, not 640 strangers |

Transcripts are template-composed from channel-appropriate fragments, not LLM-generated
— generation must be offline, deterministic, and free.

### 3.6 Seed version and the S3 prefix

The corpus has a **version**, and it is load-bearing
([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) §1a):

```python
SEED_VERSION = "v3"    # bump whenever generated data changes
```

`SEED_VERSION` namespaces the Litestream replica prefix:

```
s3://ccoa-dev-data/litestream/v3/app.db
s3://ccoa-dev-data/litestream/v3/checkpoints.db
```

**Bump it whenever generation changes** — volumes, planted records, realism rules, or
`SEED`. Without the bump, a task booting after a reseed restores the *previous*
generation from S3 and silently discards the new corpus.

CI enforces this: if the generated corpus digest changes but `SEED_VERSION` does not,
the build fails. That converts a silent data-loss bug into a build error.

### 3.7 Generation and loading

Seeding happens at **image build time**, not at container start:

```dockerfile
# Schema first: app.seed inserts rows and cannot create tables.
RUN DATABASE_URL="sqlite+pysqlite:////data/app.db" uv run alembic upgrade head && \
    uv run python -m app.seed --output /data/app.db --reset
```

`app.seed` refuses to run against a database with no `alembic_version` table, so the
ordering is enforced rather than remembered.

| Property | Consequence |
|---|---|
| Corpus is in the image | Cold start does no generation work — matters at ~45–75 s already |
| Same commit → same data | Reproducible demos and assertable tests |
| No runtime seed dependency | `Faker` is a build-time dependency only |
| Image grows ~10 MB | Irrelevant against the Python base layer |

`app.seed` is also runnable locally (`uv run python -m app.seed --reset`) for iterating
on the corpus without a rebuild.

**Seeding is not migration.** Alembic owns the schema; `app.seed` owns the rows
([04](04-data-model.md) §3.7). A migration that inserted business data would make schema
version and corpus version impossible to reason about separately — which is exactly the
confusion §3.6 exists to prevent.

### 3.8 Verification

| Check | Assertion |
|---|---|
| Determinism | Two runs produce identical digests |
| Volume | ≥100 customers; ≥500 interactions |
| Referential integrity | `PRAGMA foreign_key_check` returns empty |
| Planted scenarios | Each of the four reference prompts resolves to its planted records |
| Ambiguity | `search_customer("John Tan")` returns **exactly 2** |
| KB coverage | Every `failure_code` has ≥1 article |
| Seed version | Digest change without a `SEED_VERSION` bump fails the build |
| Size | `app.db` under 20 MB |

The ambiguity assertion is the one most likely to be broken by accident — someone
"fixing" duplicate names would remove the disambiguation demo without realising it. The
test names that intent explicitly.

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| Build-time generation | Seed on first boot | Cold start is already 45–75 s; generation would add to it. Also makes the image self-contained and reproducible |
| Fixed seed, sequential IDs | Random per run | Grounding tests and demos need stable identifiers |
| Template transcripts | LLM-generated | Must be offline, deterministic, and free at build time |
| Two customers named John Tan | One unambiguous match | Forces the disambiguation path on the very first prompt — demonstrated, not described |
| Long-tailed distributions | Uniform random | Uniform data hides the retrieval and summarisation problems the system exists to solve |
| 120 customers | 100 exactly | Comfortably clears the stated minimum with room for the ~15% zero-claim cohort |
| `SEED_VERSION` in the S3 prefix | Single prefix | Prevents a reseed being silently discarded on boot ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) §1a) |
| Fixed name and address pools | `Faker("en_SG")` | Faker is deterministic only for a pinned version; a dependency bump would silently change the corpus (§3.2) |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| Generator becomes non-deterministic | Double-run digest test | Build fails |
| Corpus changes without a `SEED_VERSION` bump | Digest-vs-version test | Build fails — before it could discard data in production |
| Planted scenario drifts | Scenario tests | Build fails; the reference prompts would otherwise break silently |
| FK violation | `foreign_key_check` | Build fails |
| Transcript bloat | Size assertion | Build fails |
| Reseed with a stale S3 generation | §3.6 prefix namespacing | Prevented by construction |

## 6. Open questions

1. **Should the corpus include a customer with no interactions at all?** It would
   exercise the empty-history path. Currently every customer has ≥3.
2. **Multi-language transcripts.** `preferred_lang` exists in the schema
   ([04](04-data-model.md)) but all transcripts are English. Populating a few non-English
   ones would test summarisation but adds no requirement coverage.
3. **Should ticket numbering continue from the seed, or start a fresh range for
   runtime-created tickets?** Continuing is more realistic; a distinct range would make
   assistant-created tickets obvious in a demo. Leaning: continue, since `created_via`
   already records provenance.
