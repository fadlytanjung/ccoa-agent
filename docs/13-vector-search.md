# 13 — Vector search

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-021, REQ-022 (quality), REQ-031
> **Depends on:** [04 — Data model](04-data-model.md), [12 — Seed data](12-seed-data.md)

## 1. Purpose

Semantic retrieval over interaction transcripts and knowledge-base articles. This is the
**nice-to-have**: it improves *"summarize previous interactions"* and *"help me
investigate"*, and it must not compromise anything that is required
([00](00-constitution.md) §10).

## 2. Scope

**In scope:** store choice, embedding model, schema, indexing, query path, graceful
degradation, alternatives with costs.

**Out of scope:** the tools that call it ([05](05-langgraph-orchestration.md) §3.8),
seed generation ([12](12-seed-data.md)).

---

## 3. Design

### 3.1 Store — `sqlite-vec`

Vectors live in **the same SQLite file as the business data**, via the `sqlite-vec`
extension (`0.1.9`).

| Property | Consequence |
|---|---|
| Infrastructure added | **None** |
| Cost | **$0** |
| Replication | Free — Litestream already replicates the file ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)) |
| Local parity | Byte-identical behaviour on a laptop and in AWS |
| Joins | Vector hits join to `interaction` in one query, no second round trip |
| Scale ceiling | Brute-force scan; fine to ~10⁵ vectors, wrong beyond that |

At ~640 interactions plus 40 KB articles, a brute-force scan over ~700 vectors is
sub-millisecond. Every managed alternative would add a service, a credential, a network
hop, and a second thing that can be down — to search a corpus that fits in RAM.

The scale ceiling is real and stated: this choice is correct **because** the corpus is
small, and would be wrong at a million vectors.

### 3.2 Embeddings

`gemini-embedding-001` ([02](02-research.md) §3.1), the same provider as generation — no
second credential, no second SDK.

| Setting | Value |
|---|---|
| Model | `gemini-embedding-001` |
| Dimensions | **768** (truncated from the model's native output) |
| Task type | `RETRIEVAL_DOCUMENT` when indexing, `RETRIEVAL_QUERY` when searching |
| Distance | Cosine |
| Normalisation | L2 at write time, so cosine reduces to a dot product |

**768 rather than the full dimensionality** because recall at this corpus size is
indistinguishable while storage and scan cost drop proportionally. `sqlite-vec` stores
`float32`, so 700 vectors × 768 dims × 4 bytes ≈ **2 MB** — negligible against the ~10 MB
database.

Asymmetric task types matter: embedding a short query with `RETRIEVAL_QUERY` and a long
transcript with `RETRIEVAL_DOCUMENT` measurably beats using one type for both.

### 3.3 Schema

Applied by Alembic revision `0002_vector_tables`, only when vector search is enabled:

```sql
CREATE VIRTUAL TABLE vec_interaction USING vec0(
    interaction_id TEXT PRIMARY KEY,
    embedding      FLOAT[768]
);

CREATE VIRTUAL TABLE vec_kb USING vec0(
    article_id TEXT PRIMARY KEY,
    embedding  FLOAT[768]
);

-- provenance, so a model or dimension change is detectable
CREATE TABLE vec_meta (
    table_name  TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    dimensions  INTEGER NOT NULL,
    indexed_at  TEXT NOT NULL,
    row_count   INTEGER NOT NULL
);
```

`vec_meta` exists so a mismatch between the configured embedding model and the one that
produced the index is **detected at boot** rather than silently returning nonsense
similarity scores.

### 3.4 Indexing

Embeddings are generated **at image build time**, alongside the seed
([12](12-seed-data.md) §3.7):

```
app.seed  →  rows written
          →  embed interaction.summary  (not the full transcript)
          →  embed kb_article.title + body
          →  write vec_* tables + vec_meta
```

| Decision | Rationale |
|---|---|
| Build time, not boot | Cold start is already 45–75 s; embedding 700 documents would add minutes |
| Embed `summary`, not `transcript` | Summaries are denser and cheaper; a 2 KB transcript dilutes the signal |
| Batched requests | ~700 documents in batches of 100 |
| **Requires a Gemini key at build time** | The one real cost of this choice — §5 |

That last row is the awkward part: the build now needs an API key, which CI does not
otherwise have ([11](11-cicd.md) §3.4). Handled in §3.6.

### 3.5 Query path

```python
def search_interactions(customer_id: str, query: str, limit: int = 5) -> list[Hit]:
    qv = embed(query, task_type="RETRIEVAL_QUERY")
    return db.execute("""
        SELECT i.interaction_id, i.summary, i.occurred_at, v.distance
        FROM vec_interaction v
        JOIN interaction i ON i.interaction_id = v.interaction_id
        WHERE v.embedding MATCH ? AND k = ?
          AND i.customer_id = ?
        ORDER BY v.distance
    """, (serialize(qv), limit, customer_id)).fetchall()
```

Two properties worth naming:

- **Always scoped to a customer.** There is no cross-customer semantic search. A query
  cannot surface another customer's transcript, by construction rather than by filter
  discipline.
- **Results are evidence like any other.** Hits are appended to `state.evidence` with
  their `ref`, so a semantically-retrieved fact is cited the same way a directly-fetched
  one is ([05](05-langgraph-orchestration.md) §3.2).

### 3.6 Graceful degradation

Vector search is **optional at every layer**, and the system is fully functional without
it:

```
enable_vector_search = false  →  search_interactions() falls back to
                                 LIKE-based keyword search over summary + subject
```

| Condition | Behaviour |
|---|---|
| Flag off | Keyword search; the answer says recall may be reduced |
| `sqlite-vec` fails to load | Logged once at boot, flag forced off, keyword search |
| `vec_meta` model mismatch | Flag forced off — a stale index is worse than none |
| Embedding call fails at query time | That query degrades to keyword; the run continues |
| **No Gemini key at build time** | Images build **without** vector tables; flag defaults off |

The last row resolves §3.4's awkwardness. CI has no LLM credentials by design, so the
default CI build produces a **keyword-only image** that passes every required test. A
separate, manually-triggered workflow with a build-time key produces the
vector-enabled image. The nice-to-have therefore cannot block the required path — which
is exactly what [00](00-constitution.md) §10 demands.

### 3.7 Where it actually helps

| Scenario | Keyword | Semantic |
|---|---|---|
| *"summarize previous interactions"* | Fine — retrieval is by customer, not by query | No advantage |
| *"has this customer complained about billing before?"* | Misses "overcharged", "wrong amount" | **Clear win** |
| *"find similar past cases"* | Needs exact shared vocabulary | **Clear win** |
| `search_kb("DOC_UNREADABLE")` | Fine — the code is a literal token | No advantage |
| *"the upload keeps getting rejected"* → KB | Reaches the right article, but ranked below a near-miss on `DOC_MISSING` | **Clear win** |

The honest summary: semantic search matters for **investigation**, not for lookup or
review. That is why it is a nice-to-have rather than a requirement — and why the
fallback is genuinely acceptable rather than a fig leaf.

### 3.8 Alternatives considered

| Option | Cost (`ap-southeast-1`) | Verdict |
|---|---|---|
| **`sqlite-vec`** *(chosen)* | **$0** | No infrastructure; replicated for free; local parity |
| Amazon S3 Vectors | $0.06/GB-mo storage, $0.20/GB PUT | Cheapest *managed* option, GA since Dec 2025. Rejected: local `aws` CLI and `boto3` are too old to expose the client ([02](02-research.md) §5.2), and it adds a second datastore for a nice-to-have |
| OpenSearch Serverless | **min 2 OCU ≈ $0.48/hr ≈ $350/mo** | Disproportionate by two orders of magnitude for 700 vectors |
| Aurora Serverless v2 + `pgvector` | ~$43/mo minimum | Would also replace the primary datastore — out of scope ([ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) §1a) |
| Pinecone / Weaviate Cloud | Free tier available | A third-party dependency and credential outside AWS, for a nice-to-have |
| FAISS in-process | $0 | Comparable to `sqlite-vec` but needs separate persistence — `sqlite-vec` gets replication free |

S3 Vectors is the one worth revisiting: it is genuinely cheap and would scale far past
this corpus. The blocker is tooling age, not the service.

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| `sqlite-vec` in the primary database | Any managed vector store | Zero infrastructure, zero cost, free replication, identical locally and in AWS |
| 768 dimensions | Full native dimensionality | Indistinguishable recall at this size; proportionally less storage and scan |
| Embed summaries | Embed transcripts | Denser signal, lower cost, smaller index |
| Build-time indexing | Runtime indexing | Cold start is already long; embedding at boot would add minutes |
| Customer-scoped queries only | Global search with a filter | Cross-customer leakage becomes impossible rather than merely prevented |
| Two build variants | Require a key in CI | Keeps the nice-to-have from blocking the required path |
| `vec_meta` provenance | Trust the index | A model change would otherwise silently degrade relevance |
| Asymmetric task types | One type for both | Measurably better retrieval, no extra cost |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| `sqlite-vec` unavailable | Load check at boot | Logged once, flag off, keyword search |
| Model/dimension mismatch | `vec_meta` check at boot | Flag off — stale index is worse than none |
| Embedding call fails at query | Exception in the adapter | That query degrades; run continues |
| Embedding rate-limited at build | 429 during build | Batches retry with backoff; build fails if exhausted |
| No Gemini key at build | Absent env var | Vector tables omitted; keyword-only image (§3.6) |
| Index stale relative to rows | `vec_meta.row_count` vs `COUNT(*)` | Warning at boot; stale entries are simply not returned |
| Query returns nothing | Empty result | Not an error — "no similar interactions" is a valid answer |

## 6. Open questions

1. **Should KB search be semantic by default even when interaction search is not?**
   KB is 40 documents; embedding them costs almost nothing and the *"upload keeps getting
   rejected"* → `DOC_UNREADABLE` mapping is the single highest-value hop in the
   investigation flow.
2. **Hybrid ranking** (reciprocal-rank fusion over keyword + vector) would beat either
   alone, at the cost of a second query and tuning. Probably not worth it at 700 vectors.
3. **Re-embedding on ticket creation.** Tickets created at runtime are not indexed, so a
   later semantic search will not find them. Acceptable for a session; worth stating in
   the tool description so the model does not over-claim.
4. **Revisit S3 Vectors** once the local toolchain is updated — it is the natural path
   if this corpus ever grows past what a brute-force scan handles.
