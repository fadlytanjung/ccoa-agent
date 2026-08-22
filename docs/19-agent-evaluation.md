# 19 — Agent evaluation

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-071, REQ-090, REQ-097
> **Depends on:** [05 — LangGraph orchestration](05-langgraph-orchestration.md), [12 — Seed data](12-seed-data.md), [14 — Local development](14-local-dev.md)

## 1. Purpose

How agent quality is measured repeatably, rather than by a person typing the reference
prompts and reading the answers.

The manual approach found three real bugs during the backend build — and that is the
argument against it, not for it. Every one was found by chance, none of them would have
been noticed by the unit suite, and none of them would be caught again if they came back.
Manual checking does not accumulate.

## 2. Scope

**In scope:** what an eval is and how it differs from a test, the framework choice, the
dataset, the harness, the two metric families, thresholds, cost, and when they run.

**Out of scope:** unit and graph tests ([05](05-langgraph-orchestration.md) §3.12),
interactive debugging ([14](14-local-dev.md)), pipeline stages ([11](11-cicd.md)).

---

## 3. Design

### 3.1 Evals are not tests

They answer different questions and must not share a runner.

| | `tests/` | `evals/` |
|---|---|---|
| Question | Is the graph wired correctly? | Is the agent any good? |
| Model | Stubbed, scripted | **Real Gemini** |
| Determinism | Total | Statistical |
| Cost | Nothing | Model calls, and judge calls |
| Speed | ~4 s | ~3.5 minutes |
| Runs | Every commit; blocks merge | On demand, and before a release |
| A failure means | The code is broken | The agent got worse — or the expectation was wrong |

The last row is why they are separated. A failing test is unambiguous. A failing eval
needs a person to ask *which of the agent and the expectation is wrong* — and during the
first run of this suite, the answer was the expectation twice out of three
([§6](#6-what-the-first-run-found)). Putting that judgement call in the merge path would
teach everyone to ignore it.

This is the same boundary [14](14-local-dev.md) §3.4 draws between `langgraph dev` and
FastAPI: **graph quality is a separate question from product correctness.** Evals are
the automated form of the Studio question.

### 3.2 Framework — DeepEval

[DeepEval](https://deepeval.com) `4.1.10`. It provides the test-case model, the metric
protocol, `assert_test`, a pytest integration, and — decisively — a **native Gemini
judge** (`deepeval.models.GeminiModel`), so scoring uses the key this project already
has rather than requiring a second provider.

Custom metrics subclass its `BaseMetric`, so deterministic and judged checks share one
runner, one report format, and one threshold vocabulary.

What is used from it, after reading the documentation properly rather than reaching for
the first thing that worked:

| Capability | Used for |
|---|---|
| `GEval` | Per-case quality rubrics (§3.5) |
| `ConversationalTestCase` / `Turn` | Multi-turn scoring — the cases *are* conversations (§3.11) |
| `KnowledgeRetentionMetric`, `RoleAdherenceMetric`, `ConversationCompletenessMetric` | Whether it remembers, stays in role, and finishes |
| `RoleViolationMetric`, `MisuseMetric` | Being talked out of its role or its domain |
| `ArgumentCorrectnessMetric` | Whether tool *arguments* made sense, not just tool names |
| `TaskCompletionMetric`, `StepEfficiencyMetric` | The execution path (§3.12) |
| LangGraph `CallbackHandler` + `@observe` | Native tracing, so the path metrics have something to read |
| `BaseMetric` | The deterministic family (§3.5) |

Deliberately **not** used, each for a reason recorded where the decision lives:
`ToolCorrectnessMetric` (builds an OpenAI judge for a set comparison),
`PIILeakageMetric` (§3.11), and DeepEval's telemetry, which is opted out of in
`evals/conftest.py` because this project keeps third-party egress opt-in.

> **On "Hermes":** an agent-evaluation framework by that name could not be found. The
> `hermes` package on PyPI is a workflow for publishing research software with rich
> metadata, unrelated to LLM evaluation. If a different tool was meant, the swap is
> contained: the harness (§3.4) produces a plain `Trace`, and only `evals/metrics.py`
> knows about DeepEval.

Also considered: **Ragas** (retrieval-focused; this system is not RAG-shaped), **promptfoo**
(a Node CLI — a second toolchain), and **LangSmith evaluators** (good, but binds the eval
suite to a hosted service that [10](10-security.md) §6 keeps optional).

### 3.3 The dataset

`backend/evals/dataset.yaml` — 11 cases, in YAML for the same reason prompts are
([17](17-agent-skills.md) §3.1): an expectation about agent behaviour is a specification,
and it should be reviewable as prose.

Every case runs against the **planted** seed records ([12](12-seed-data.md) §3.4). That
is what makes an eval a measurement: the corpus is byte-identical on every run, so a
score that moves means the *agent* moved.

A case is a scripted conversation plus expectations:

```yaml
- name: lookup_ambiguous_name_asks
  conversation:
    - message: "Show me the details for customer John Tan."
  expect:
    tools: [search_customer]
    forbidden_tools: [get_customer]
    interrupt_kind: clarify
    interrupt_contains: ["CUST-000042", "CUST-000091"]
    writes: none
  rubric:
    criteria: >
      The question must make the two customers distinguishable in one glance...
    threshold: 0.7
```

Coverage:

| Area | Cases |
|---|---|
| The four reference prompts (REQ-020–023) | 6 |
| Authorisation on resume | 1 |
| Honesty — absent records, no invention | 1 |
| Guard — rejects injection, does not over-block | 2 |
| Rejection and non-writing paths | 2 |

`forbidden_tools` and `must_not_mention` carry more weight than they look. The
disambiguation guarantee is not "it asked a question" — it is that **`get_customer` was
never called** while two customers matched. Negative assertions are where agent
regressions actually show up.

### 3.4 The harness

`evals/harness.py` runs a case and returns a `Trace`: the answer, citations, evidence
refs, every tool call with its arguments, the pending checkpoint, what was written, the
audit rows, and the model-call count.

Three details do real work:

- **Tool calls are recorded by wrapping the toolbox**, not reconstructed from evidence.
  A tool that returns nothing — a search with no matches — produces no evidence, and
  "did it even look?" is exactly what an eval needs to answer.
- **Model calls are counted.** One case asserts `max_model_calls: 0`: the guard must
  reject an injection attempt *before* spending a call, and there is no other way to
  observe that from outside.
- **Each case gets its own copy of the corpus.** One eval approves a ticket; without
  isolation the next one sees it and its expectations shift underneath it.

### 3.5 Two metric families

| | Deterministic | Judged |
|---|---|---|
| Implementation | Pure functions of the `Trace` | `GEval` against a rubric |
| Cost | None | One judge call per case |
| Variance | None | Real (§6) |
| Threshold | 1.0 — a fact is true or not | 0.7–0.8 |
| Gate? | **Yes** | Advisory |

**Most of what is worth asserting about an agent is deterministic**, and reaching for a
judge to answer a question with a definite answer is a mistake — it costs money, adds
variance, and makes a guarantee probabilistic.

| Metric | Asserts |
|---|---|
| `expected_tools` | The tools the case requires were called |
| `forbidden_tools` | The tools it must not use were not |
| `checkpoint` | The turn ended on the right kind of human checkpoint |
| `grounding` | Every identifier in the answer was actually shown — REQ-090 |
| `content` | Required and forbidden substrings |
| `writes` | What was persisted, **and** that an audit row agrees |
| `model_calls` | Bounds on model invocations |

`grounding` is the one that must never be delegated to a judge. Whether a claim
reference appeared in the evidence is a fact, and asking a model to assess it would make
the system's central honesty guarantee probabilistic.

Judged metrics cover what is genuinely a matter of degree: is this summary useful to
someone about to take a call, is this ticket actionable by a stranger. Two rubrics also
encode bugs found by hand — *do not narrate your own process* and *do not re-ask a
settled question* — so those regressions are now caught automatically.

#### On `ToolCorrectnessMetric`

DeepEval ships one, and this suite does not use it: its constructor builds an **OpenAI**
judge to phrase its explanation, so a set comparison ends up demanding a second
provider's API key. The comparison is four lines. `evals/metrics.py` implements it
directly and says why in a comment, so nobody re-adds it.

### 3.6 Grounding, precisely

The naive definition — every identifier in the answer must be an evidence `ref` — is
wrong, and scored honest answers as hallucinations on the first run.

An interaction record *contains* its case id. An answer that mentions that case is
grounded: the model was shown it. But the case was never fetched in its own right, so
there is no `case:` ref for it.

So there are two different checks, and both are needed:

| Check | Question |
|---|---|
| `grounded` | Was every identifier in the answer **shown** to the model — as a ref, or inside a record? |
| `must_cite` | Does the answer **point at** these specific records? |

The first catches invention. The second catches an answer that is technically true but
does not show its working.

### 3.7 Running them

```bash
uv sync --group evals                      # deepeval is not in the default dev install

uv run pytest evals -m "eval and not judged"   # deterministic — 11 checks, no judge calls
uv run pytest evals -m judged                  # rubric + conversational + safety — 13 checks
uv run pytest evals                            # the first three layers — 26 checks, ~7 min

# The trajectory layer runs separately, and must (§3.11)
CCOA_EVAL_TRAJECTORY=1 uv run deepeval test run evals/test_trajectory.py

uv run pytest evals -k investigation           # one case, while iterating on a skill
```

They **skip**, not fail, without `GEMINI_API_KEY`, so a contributor without a key can
still run everything else. The dataset's own validity is checked by a test that needs no
key — an eval suite that only validates itself when someone has credentials is one that
breaks silently.

### 3.8 The judge, and a provider incompatibility

DeepEval ships a native `GeminiModel`. It works for `GEval` and **fails for everything
added in §3.11 and §3.12**: those metrics build a response schema containing a mapping,
which serialises with `additionalProperties`, and the Gemini API rejects the field:

```
400 INVALID_ARGUMENT — Unknown name "additional_properties" at
'generation_config.response_schema'
```

That is a provider incompatibility in DeepEval's Gemini path, not a defect in the metrics
or the agent. Every affected metric failed identically and immediately.

`evals/judge.py` takes DeepEval's own **non-native** path instead: given a custom
`DeepEvalBaseLLM`, metrics stop asking the provider for schema-constrained output and
parse JSON from the response — and their prompts already ask for JSON, because that path
is supported. The adapter deliberately does not accept a `schema` keyword, so the base
class tries it, gets a `TypeError`, and falls through to plain text.

The cost is real: without provider-enforced schemas, a malformed judge response becomes a
parse error rather than being impossible. In practice that surfaces as a metric error,
not a silent wrong score.

### 3.9 Which model the evals run on

Two knobs:

| Variable | Default | What it affects |
|---|---|---|
| `CCOA_EVAL_MODEL` | `gemini-3.5-flash` — **the shipped model** | The agent **under test** |
| `CCOA_EVAL_JUDGE_MODEL` | `gemini-3.5-flash-lite` | The model doing the **scoring** |

**The agent runs on what ships**, so a passing eval is evidence about the deployed
system. The judge does not have to match — it scores, it is not under test, and it is
called dozens of times per pass, so `-lite` there is a straight saving.

An earlier version defaulted the agent to `gemini-2.5-flash` to relieve quota pressure.
That was abandoned on evidence: `gemini-2.5-flash` is **being withdrawn for
newly-created projects** and returns, intermittently,

```
404 — This model models/gemini-2.5-flash is no longer available to new users.
Please update your code to use models/gemini-3.6-flash
```

*Intermittently* is the disqualifying part — it answered a direct call and 404'd a
preflight seconds later on the same key. A model you evaluate against has to be at least
as reliable as the thing being evaluated.

Neither knob solves a spending cap (§3.10) — that is project-wide and indifferent to
which model is called.

### 3.10 Cost and cadence

Layers 1–3 are 26 checks over 11 cases in about seven minutes; the trajectory layer adds
3 more and roughly four minutes. Within one session a judged case and its deterministic
counterpart score the *same cached trace* rather than replaying the conversation, which
is most of why the combined run is not the sum of its parts.

DeepEval reports cost when it runs the suite itself: two trajectory metrics on one case
came to **$0.086**. At `gemini-3.5-flash` prices a full pass is small change, but it is
not free, and it is slow enough that nobody would tolerate it on every push.

| When | What runs | Why |
|---|---|---|
| Every commit (CI) | `tests/` only | Fast, free, deterministic |
| Every commit (CI) | Dataset validity | Catches a malformed dataset without a key |
| Before a release, on demand | Layers 1–3, then trajectory | The question is "is the agent good", asked when it matters |
| After changing a `SKILL.md` | The affected cases | Prompt changes are exactly what evals exist to catch |

**Expect to run out of quota, and read the error before believing the verdict.** A full
pass is dozens of graph runs plus dozens of judge calls. When the project's allowance is
gone, every case fails with `429 RESOURCE_EXHAUSTED`, the agent degrades exactly as
designed, and the report reads "never called search_customer" and "expected checkpoint
approve, got none" — indistinguishable from a catastrophic regression.

The specific failure seen here was **not** per-minute rate limiting, which is the
natural assumption and the wrong one:

```
429 RESOURCE_EXHAUSTED — Your project has exceeded its monthly spending cap.
Please go to AI Studio at https://ai.studio/spend to manage ...
```

A **project-wide spending cap**, which is why changing model does not help: the same call
fails identically on `gemini-2.5-flash` and `gemini-3.5-flash`. It is lifted in AI
Studio, not worked around in code.

`evals/conftest.py` makes one cheap call before the suite and **skips with the provider's
own message** when it fails, so this reads as a billing problem rather than as thirty
agent regressions.

**Evals do not gate merges.** A judged metric that flakes and blocks a PR trains people
to skip it, which is worse than not having it. The deterministic half is stable enough to
gate and may become a release gate once it has run long enough to trust.

---

### 3.11 Multi-turn and disclosure

Every case here is a conversation, and the first version of this suite collapsed each one
into a single input/output pair. That threw away the part carrying the most risk:
whether the assistant still knows which customer it is discussing three turns later is
not visible in the last answer.

So traces are also scored as `ConversationalTestCase`s:

| Metric | Question |
|---|---|
| `KnowledgeRetentionMetric` | Does it still know what it was told earlier? |
| `RoleAdherenceMetric` | Is it still a contact-centre operations assistant? |
| `ConversationCompletenessMetric` | Did the conversation actually finish the job? |

Knowledge retention is the one that earns its cost: re-asking a question the human
already answered is a retention failure, and it is precisely the defect that previously
only got caught by a person noticing it.

#### Three metrics that had to be scoped or dropped

More interesting than the ones that worked. Each is a mismatch between a metric's
premise and this system, not a defect in either — and each was found by running it.

**`PIILeakageMetric` — dropped.** Its premise is that personal data in the output is a
violation. False here: an internal assistant returning a customer's name, tier, and
policies *to an authenticated support agent* is doing its job. It flagged the customer's
own name, and the initials of staff who handled prior calls, as "critical exposure of
PII". Every case failed. A safety layer that is always red is one people learn to skip.

Replaced with a `disclosure` GEval encoding what this project *actually* forbids: do not
volunteer a date of birth, home address, or full phone number unless asked. That is the
rule in the profile skill and docs/04 §3.8, and no off-the-shelf metric expresses it.

**`ArgumentCorrectnessMetric` — scoped to single-turn cases.** It sees the input and the
tool calls, and nothing in between. On a multi-turn run this agent legitimately passes
arguments learned from earlier *tool results* — `DOC_UNREADABLE` came from reading the
claim — and the metric scores them as hallucinated because they are absent from the
input it was handed. Meaningful on a single-turn case; a permanent red light otherwise.

**`ConversationCompletenessMetric` — removed from the authorisation case.** It measures
whether the user's intentions were satisfied. When an agent without the supervisor group
tries to escalate, the correct outcome is that they are *deliberately not*. It scored
that refusal 0.5 and called it a failure to complete the request — the metric working
exactly as designed, against a case it cannot express.

### 3.12 Trajectory — judging the path

The other layers judge what the agent said and what it changed. This one judges **how it
got there**, which is the closest thing to what a person does reading a run by hand.

It is also the layer that most directly reduces hand-written expectations:
`TaskCompletionMetric` infers the task from the trace rather than being told what to
look for, so it needs no `must_mention` list.

Tracing comes from DeepEval's native LangGraph integration — `CallbackHandler` passed in
the graph config, inside an `@observe`-decorated call that establishes the trace scope.

**It runs in its own session, and that is enforced:**

```bash
CCOA_EVAL_TRAJECTORY=1 uv run deepeval test run evals/test_trajectory.py
```

Two reasons, both found by doing it wrong first:

- Trajectory metrics need an active trace, established by `deepeval test run`. Under
  bare `pytest` they raise "No active trace found" — a clear error, not a silent pass.
- Collecting them puts the **whole pytest session** into trace scope, which breaks the
  other layers. One combined command produced **24 failures, none of them real**. The
  cases are now skipped unless `CCOA_EVAL_TRAJECTORY=1` is set, so it cannot recur by
  accident.

#### `StepEfficiencyMetric` is not in the gate

Finely balanced, and worth recording rather than quietly dropping.

It earned genuine credit: reading its rationale led to two real defects — every
`read_reference` call failing, and `search_kb` repeating with reworded queries (§6.1).

It also scored a run **0.0** with *"the agent repeatedly called redundant tools and
failed"* against a run that made exactly **one** tool call, had zero failures, and could
not have been more efficient. That is a fabricated rationale, and it is the second such
verdict this suite has caught.

It cannot simply be demoted to a non-gating diagnostic either. Being a trajectory metric
it needs the trace, so it must go through `assert_test`; catching the exception then
produces a DeepEval report reading "1 passed, 5 failed" while every test passes, which is
worse than either option.

So it is **run by hand** when agent efficiency is the question — add it to the metric
list in `evals/test_trajectory.py`, read the reason, and **verify the claim against the
trace before acting on it.** Twice now that verification has been the difference between
a real fix and chasing a phantom.

### 3.13 End to end, through the API

Every layer above drives `build_graph` directly. Two more drive the **product** — a real
FastAPI app, real routes, real SSE framing, a real checkpointer on disk:

| | `tests/api/test_end_to_end.py` | `evals/test_end_to_end.py` |
|---|---|---|
| Model | Scripted | Real |
| Cost | None | Model calls |
| Runs | Every commit | Opt-in |
| Answers | Is the product wired together? | Does a real model behave in that wiring? |

They walk the same path: four reference prompts, one thread, two human checkpoints, a
ticket written at the end, and the ticket then read back through `GET /tickets/{id}`.

The seam they cover was genuinely uncovered. `tests/api/` proved the transport against a
stub; `evals/` proved the agent without the transport. Neither would notice an answer
that never reaches the `message` event, an interrupt that resolves in-process but not
across a closed stream, or an approval that writes on resume but is invisible to a later
`GET /state`. Those are wiring bugs, and they live exactly between the two.

Three properties are asserted here and nowhere else:

- **The stream closes on an interrupt and the question survives it** — the durability
  claim behind REQ-091, checked through HTTP rather than in-process.
- **What the human approved is byte-for-byte what was written**, compared across the SSE
  payload and the database row.
- **Threads do not leak into each other.** Two conversations, one subject customer
  established in the first, and the second still empty.

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| Evals separate from tests | One suite | Different question, different cost, different meaning of failure |
| DeepEval | Ragas, promptfoo, LangSmith | Native Gemini judge, custom-metric protocol, pytest integration, no second toolchain |
| Dataset in YAML | Python assertions | An expectation is a specification; it should read as prose in a diff |
| Deterministic metrics do the heavy lifting | Judge everything | Facts have definite answers; a judge would make them probabilistic and cost money |
| Own tool metric | DeepEval's `ToolCorrectnessMetric` | Theirs builds an OpenAI judge to explain a set comparison |
| Judged metrics advisory | Gate on them | A flaky gate is a gate people learn to bypass |
| A custom Gemini judge, not DeepEval's `GeminiModel` | The native model | The native path cannot run the conversational, safety, or agentic metrics against Gemini at all — see below |
| Trajectory layer isolated behind a flag | One command for everything | Sharing a session broke the other layers and produced 24 unreal failures |
| Metrics scoped or dropped where their premise fails | Lower the threshold until it passes | Tuning a threshold to hide a mismatch keeps the red light *and* loses the signal |
| Evals default to `gemini-2.5-flash` | Always the shipped model | Cheaper per pass while iterating; run the shipped model before a release (§3.9) |
| A stubbed end-to-end walk *and* a live one | Only the live one | The wiring question is answerable for free and belongs in the merge gate (§3.13) |
| Preflight, then skip | Let the suite fail | An exhausted quota otherwise reports as thirty agent regressions |
| Agent evaluated on the shipped model | A cheaper model | A pass should be evidence about what deploys; only the judge is downgraded |
| `TaskCompletionMetric` gates, `StepEfficiencyMetric` does not | Both, or neither | One is reliable here and one has twice invented its rationale (§3.12) |
| Real model, real corpus | Stubbed model | A stub tells you the graph is wired, which `tests/` already covers |
| Per-case corpus copy | Shared database | One case writes a ticket; the next would see it |
| Gemini judges Gemini | A different provider as judge | More independent, but a second key and a second bill. Revisit if scores look generous |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| No API key | Fixture check | Skips with a reason, does not fail |
| Quota exhausted | `429 RESOURCE_EXHAUSTED` on the preflight | **Not a regression.** The preflight skips with the provider's message |
| Model withdrawn for the project | `404 ... no longer available to new users` | Change `CCOA_EVAL_MODEL`; check availability before assuming quota |
| Streaming tests fail after the first | "bound to a different event loop" | `sse_starlette` caches a global event; the conftests reset it |
| Judge cannot parse a response | Metric error, not a score | The cost of the non-native judge path (§3.8) |
| Trajectory tests collected with the rest | Bulk failures across unrelated cases | Prevented by the opt-in flag (§3.9) |
| A judged metric flakes | Score near the threshold | Advisory; re-run and read the reason before acting |
| The judge is simply wrong | Its reason contradicts the trace | It happened on the first run (§6). Read the trace, not the verdict |
| An expectation is wrong, not the agent | A deterministic metric fails on reasonable behaviour | Fix the dataset — and say so in the diff |
| Corpus changed underneath the evals | Many cases fail at once | Check `SEED_VERSION`; planted records are the contract |
| Model deprecated | Every case errors | Change `GEMINI_MODEL`, re-baseline the scores |
| An eval leaves data behind | The next case fails oddly | Per-case isolation prevents this; a shared fixture would reintroduce it |

## 6. What the first run found

Recorded because it is the honest measure of whether this suite is worth having.

| Finding | Verdict |
|---|---|
| `interaction_review` scored as a hallucination for citing a case id it *was* shown | **The metric was wrong** — grounding was too strict (§3.6) |
| `investigation` failed for not calling `get_claim` | **The expectation was wrong** — `list_claims` already returns the failure code, so skipping the second fetch is efficient, not incomplete |
| `lookup_ambiguous` judged as "empty output" | **The harness was wrong** — a turn that ends on a checkpoint has no answer; the rubric must judge the *question asked* |
| `investigation` judged "severely truncated" | **The judge was wrong.** The answer was complete at 1,399 characters and ended cleanly. Verified by dumping the raw content blocks |

Two of four were mistakes in the eval, not the agent. That is the normal shape of a first
eval run, and the reason judged metrics are advisory: **the suite's own claims need
verifying before they are trusted**, and one row above is a standing reminder that an LLM
judge states a wrong verdict with exactly the same confidence as a right one.

### 6.1 What the trajectory layer found

*(Layers 1–4 and the trajectory layer now pass in full against the shipped model:
**29 checks green**, trajectory **3/3**.)*

Adding §3.11 and §3.12 was worth it for one result. `StepEfficiencyMetric` scored the
investigation **0.25** and said why:

> The agent performed multiple redundant and failed tool calls, including searching the
> knowledge base repeatedly for the same article and attempting to read a reference
> document with an incorrect skill parameter.

Both halves were real, and neither was visible to any other layer — the deterministic
checks passed, the answer was correct, and a person reading the output would have seen
nothing wrong:

| Defect | Fix |
|---|---|
| **Every `read_reference` call failed.** The model was asked to name its own skill and sometimes named the wrong one; the call errored and burned an iteration | The graph knows which specialist is running, so the argument was removed from the schema and injected. It also narrowed a boundary: a tool taking a skill name is a tool that can be pointed at another skill's files |
| The same failure survived the first fix | The binding was corrected in `bind_tools_for`, but the investigator **executes tool calls through its own loop**, not the bound `StructuredTool`. Injecting in one place and not the other left it broken while the binding tested fine in isolation |
| `search_kb` ran three times with reworded queries | A per-tool call cap. Deduplicating identical calls was not enough — the thrash was *rephrased* repeats, which look like progress |

After the fixes: **zero failed tool calls**, `search_kb` down to two, and the investigator
spends the freed iteration on `get_case` instead. Trajectory pass rate went from 0/3 to
2/3, the remaining failure being the multi-turn mismatch described in §3.12.

This is the clearest answer to whether the framework earns its place. Three defects, one
of them a genuine boundary weakness, none of them findable by reading answers.

## 7. Open questions

1. **How many runs before a threshold means anything?** Thresholds are currently a
   considered guess. They should be set from the observed distribution over a dozen runs,
   not from intuition.
2. **Should the deterministic half gate merges?** It is stable and fast enough. It is not
   free, and it needs a key in CI — which means a repository secret the pipeline does not
   otherwise need ([11](11-cicd.md) §3.1).
3. **Adversarial cases.** The dataset has one injection attempt. A serious suite would
   have a dozen, including transcript-borne injection — text a *customer* wrote that the
   agent later reads.
4. **Per-skill attribution.** A failure currently names a case, not the skill that caused
   it. Since skills are versioned and digest-logged ([17](17-agent-skills.md) §3.7),
   correlating a score change with a prompt change is a small step and would make
   regressions self-diagnosing.
