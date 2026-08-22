# 17 — Agent skills and prompt assets

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-095, REQ-096, REQ-097
> **Depends on:** [05 — LangGraph orchestration](05-langgraph-orchestration.md)

## 1. Purpose

Defines where agent behaviour actually lives. **No prompt text, routing policy, or
output format is hardcoded in Python.** Every agent is defined by a versioned skill
directory — a `SKILL.md` with YAML frontmatter, optional reference documents, and
optional output templates — loaded and validated at boot.

## 2. Scope

**In scope:** skill directory layout, frontmatter schema, progressive disclosure,
templates, the registry and its validation, versioning, hot reload, the no-hardcoded-
prompts rule and how it is enforced.

**Out of scope:** the graph that consumes skills ([05](05-langgraph-orchestration.md)),
the model binding, tool implementations.

---

## 3. Design

### 3.1 Why prompts are not code

A prompt is a behavioural specification that changes far more often than the code
around it. Embedded as string literals it becomes invisible: unreviewable in a diff of
any size, impossible to version independently, untestable in isolation, and it forces a
rebuild and redeploy for a wording change. Externalising it buys four things:

| Property | Consequence |
|---|---|
| **Reviewable** | A behaviour change is a diff in a Markdown file, not buried in a `.py` |
| **Versioned** | Each skill carries a semantic version, logged per run, so an output regression is attributable to a prompt change |
| **Progressive** | The orchestrator loads one-line descriptions; full instructions load only when a specialist actually runs |
| **Testable** | A skill can be linted, token-counted, and snapshot-tested without importing the graph |

### 3.2 Layout

```
backend/app/agents/
├── registry.py                     loads, validates, caches
├── schema.py                       Pydantic model for the frontmatter
└── skills/
    ├── orchestrator/
    │   ├── SKILL.md
    │   └── references/
    │       ├── delegation-policy.md
    │       └── human-checkpoints.md
    ├── profile/
    │   └── SKILL.md
    ├── history/
    │   ├── SKILL.md
    │   └── templates/
    │       └── interaction-summary.md.j2
    ├── investigator/
    │   ├── SKILL.md
    │   └── references/
    │       ├── failure-codes.md
    │       └── investigation-playbook.md
    └── resolution/
        ├── SKILL.md
        └── templates/
            ├── ticket-draft.md.j2
            └── escalation-brief.md.j2
```

One directory per agent. The directory name is the skill's identity and must match the
frontmatter `name`.

### 3.3 `SKILL.md` format

```markdown
---
name: investigator
version: 1.3.0
description: >
  Investigates why a claim failed, stalled, or was rejected. Correlates claim
  status, failure codes, prior interactions, and knowledge-base remediation.
  Delegate here when the agent is asking *why* something went wrong.
model: gemini-3.5-flash
temperature: 0.0
max_output_tokens: 2048
tools:
  - get_customer
  - list_claims
  - get_claim
  - list_interactions
  - search_interactions
  - list_cases
  - get_case
  - search_kb
limits:
  max_iterations: 6
  max_parallel_tools: 3
  wall_clock_seconds: 45
human_checkpoints:
  - kind: clarify
    when: more than one customer matches the name given
  - kind: confirm
    when: the investigation would read more than 20 interactions
references:
  - references/failure-codes.md
  - references/investigation-playbook.md
---

## Role

You investigate insurance claim problems on behalf of a support agent who is
often on a live call with the customer...

## Method

1. Establish the subject customer before anything else...
2. ...

## Grounding

Answer only from the EVIDENCE block. Cite the `ref` of every record you mention...

## When to involve the human

You are talking *with* a colleague, not producing a report for one. Ask when
asking is genuinely cheaper than guessing...
```

The body is plain Markdown. The `##` headings are conventional, not parsed — the whole
body becomes the system prompt for that agent.

### 3.4 Frontmatter schema

Validated at boot by `schema.py`. Unknown keys are an error, not a warning.

| Key | Type | Required | Notes |
|---|---|---|---|
| `name` | slug | ✓ | Must equal the directory name |
| `version` | semver | ✓ | Logged with every run |
| `description` | string ≤400 chars | ✓ | **This is what the orchestrator sees** — write it as delegation guidance |
| `model` | string | — | Defaults to `settings.gemini_model` |
| `temperature` | 0.0–1.0 | — | Default 0.0 |
| `max_output_tokens` | int | — | Default 2048 |
| `tools` | list of tool names | — | **Validated against the tool registry** — an unknown name fails boot |
| `limits.max_iterations` | int | — | Loop bound for agentic skills |
| `limits.max_parallel_tools` | int | — | |
| `limits.wall_clock_seconds` | int | — | |
| `human_checkpoints` | list | — | Declarative HITL triggers — [05](05-langgraph-orchestration.md) §HITL |
| `requires_groups` | list | — | Cognito groups needed to invoke this skill at all |
| `references` | list of paths | — | Loaded **on demand**, not at boot |
| `templates` | list of paths | — | Jinja2, registered for this skill |

Two validations do real work:

- **Tool names are checked against the registry.** A skill listing `get_polciy` fails
  the container at boot with a clear message, rather than silently offering the model a
  tool that does not exist.
- **`requires_groups` is enforced before the skill runs**, so an authorisation boundary
  can be declared in the skill rather than scattered through code.

### 3.5 Progressive disclosure

Three tiers, so the orchestrator's context stays small no matter how many skills exist:

| Tier | Loaded | Cost |
|---|---|---|
| **1 — Descriptions** | Always, for every skill | ~40 tokens each; this is the orchestrator's menu |
| **2 — Body** | When that specialist is invoked | ~400–900 tokens, for one agent only |
| **3 — References** | On demand, when the specialist reads one | ~500–2000 tokens each |

The orchestrator never sees the investigator's full instructions. It sees one sentence
and decides whether to delegate. The investigator loads its own body when it runs, and
pulls `failure-codes.md` only if it actually encounters a failure code.

A `read_reference(skill, path)` tool exposes tier 3 to the agent that owns the skill.
Reference paths are resolved **inside the skill directory only** — a traversal attempt
is rejected, not merely normalised.

### 3.6 Templates

Deterministic output shapes are Jinja2 templates, not model instructions. Asking a
model to "always format the ticket description with these five sections" works most of
the time; a template works every time.

```jinja
{# templates/ticket-draft.md.j2 #}
**Customer:** {{ customer.full_name }} ({{ customer.customer_id }})
{% if claim %}**Claim:** {{ claim.claim_id }} — {{ claim.failure_code }}{% endif %}

## Problem
{{ problem }}

## Evidence
{% for e in evidence %}- `{{ e.ref }}` — {{ e.summary }}
{% endfor %}

## Suggested next action
{{ next_action }}
```

The model supplies the *fields* (`problem`, `next_action`); the template supplies the
*shape*. The approval card ([07](07-frontend.md) §3.6) renders the same template, so
what the human approves is exactly what gets written.

Templates are sandboxed (`SandboxedEnvironment`), autoescape off (Markdown, not HTML),
and rendered with an explicit context dict — never `**state`.

### 3.7 Registry

```python
class SkillRegistry:
    def __init__(self, root: Path, strict: bool = True) -> None: ...
    def descriptions(self) -> list[SkillDescriptor]:  # tier 1 — orchestrator menu
    def get(self, name: str) -> Skill:                # tier 2 — body + config
    def reference(self, name: str, path: str) -> str: # tier 3 — on demand
    def render(self, name: str, template: str, ctx: dict) -> str:
```

Boot behaviour:

1. Walk `skills/`, parse every `SKILL.md`.
2. Validate frontmatter; cross-check tool names against the tool registry.
3. Verify every declared `references` and `templates` path exists.
4. Compute a SHA-256 over each skill directory; log `name@version` and digest.
5. **Any failure aborts startup.** A malformed skill must not reach production as a
   runtime surprise on the first user request.

### 3.8 Environments

| Environment | Source | Reload |
|---|---|---|
| Local (`uvicorn --reload`, `langgraph dev`) | Working tree | **Hot** — file watcher re-parses on change |
| Deployed | Baked into the image | Frozen; digest logged at boot |

Hot reload is what makes prompt iteration fast: edit `SKILL.md`, send the same message
in LangGraph Studio, see the behaviour change without a restart. That loop is the main
practical reason to externalise prompts at all.

### 3.9 The no-hardcoded-prompts rule

**Enforced, not merely stated.** A CI check walks the AST of `app/graph/` and
`app/agents/` and fails the build on any string literal over 200 characters that is not
in a test fixture:

```python
# tools/check_no_inline_prompts.py — runs in CI
FORBIDDEN_DIRS = ("app/graph", "app/agents")
MAX_LITERAL = 200
```

Legitimate exceptions are narrow and must be annotated:

```python
ERROR_TEMPLATE = "..."  # noqa: inline-prompt — user-facing error string, not a prompt
```

The rule covers system prompts, tool descriptions, routing policy text, few-shot
examples, and output-format instructions. It does not cover log messages, exception
strings, or SQL.

**Docstrings are exempt.** *(Added 2026-08-22.)* That sounds like a hole, and would be
one if a docstring could reach the model — but none can. System prompts come from
`SKILL.md` bodies and tool descriptions from `tools.yaml`, both loaded by the registry;
there is no code path that sends a Python docstring to Gemini. The exemption is what
lets the graph explain *why* it is shaped the way it is at the length that actually
takes, rather than compressing design rationale to fit a lint rule.

### 3.9a Tool descriptions — `app/agents/tools.yaml`

A tool description is prompt text: the model reads it to decide what to call. So it is
an asset, not a docstring.

```yaml
search_customer:
  summary: Find customers by name, email address, or customer ID.
  description: >
    Find customers by name, email address, or customer ID. Returns EVERY match, not the
    best one — if two people share a name you get both, and choosing between them is a
    question for the human, not a guess for you.
```

The registry cross-checks the file against the tool registry **in both directions** and
fails boot on either mismatch:

| Drift | Result |
|---|---|
| A registered tool with no entry | Boot fails — the model would get an empty description |
| An entry for a tool that no longer exists | Boot fails — the file cannot accumulate dead prose |

Argument descriptions stay in Python as short `Field(description=...)` strings. They
name an argument in a handful of words (`"Customer ID, e.g. CUST-000042."`), sit far
below the literal limit, and belong next to the type they describe — splitting them out
would separate a field's name, type, and meaning across two files for no gain.

### 3.10 Testing skills

| Test | Asserts |
|---|---|
| Schema | Every `SKILL.md` parses and validates |
| Tool references | Every declared tool exists in the registry |
| Path integrity | Every `references`/`templates` path resolves inside its directory |
| Token budget | Tier-1 descriptions total under 1500 tokens; no body over 3000 |
| Template render | Each template renders against a fixture context without error |
| Traversal | `read_reference("investigator", "../../secrets")` is rejected |
| Snapshot | Rendered ticket-draft output matches a golden file |

Token budgeting is a real test, not a nicety: tier-1 descriptions ride in **every**
orchestrator call, so unbounded growth there is a per-request cost regression that no
functional test would catch.

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| Markdown + YAML frontmatter | JSON/YAML prompt config; a database | Prompts are prose. Markdown diffs readably and needs no editor tooling |
| One directory per agent | One file per prompt | Keeps instructions, references, and templates that change together in one place |
| Frontmatter `description` as the delegation menu | Separate routing config | Single source of truth — a skill describes when to use itself |
| Progressive disclosure | Load everything up front | Orchestrator context stays flat as the skill count grows |
| Jinja2 for output shape | Model-instructed formatting | Deterministic, testable, and identical between approval preview and written record |
| Boot-time validation, fail hard | Lazy load with runtime errors | A typo becomes a failed deploy, not a failed customer interaction |
| CI-enforced literal limit | Convention and code review | Conventions erode; the check does not |
| Skills baked into the image | Fetched from S3 at runtime | Immutable, versioned with the code, no runtime dependency. Cost: a wording fix needs a redeploy |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| Malformed frontmatter | Boot validation | Container exits with the file and field named |
| Skill references an unknown tool | Boot cross-check | Container exits |
| Missing reference or template file | Boot path check | Container exits |
| Reference traversal attempt | Path resolution guard | `ToolError`, audited |
| Template render error | Try/except at render | Falls back to a plain structured rendering; the human still sees the payload |
| Tier-1 descriptions grow unbounded | CI token-budget test | Build fails |
| Two skills declare the same `name` | Boot uniqueness check | Container exits |
| Prompt literal added to graph code | CI AST check | Build fails |

## 6. Open questions

1. **Should skills be hot-reloadable in the deployed environment?** Fetching from S3
   would allow prompt fixes without a redeploy, at the cost of runtime dependency and a
   mutable-behaviour surface. Leaning no — immutability is worth more here.
2. **Per-skill model override.** The schema allows it, so an expensive specialist could
   run on a stronger model. Unused for now; worth measuring before enabling.
3. **Localisation.** `customer.preferred_lang` exists in the data model. Skills are
   English-only; multi-language would mean per-locale bodies or a translation step.
4. **Should `human_checkpoints` be advisory or enforced?** Currently the graph reads
   them as policy. Making them purely declarative risks the model ignoring them; making
   them fully code-enforced reduces the flexibility that keeps the conversation natural.
   Current position: enforced for `approve`, advisory for `clarify` and `confirm`.
