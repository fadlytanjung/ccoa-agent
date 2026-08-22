# 21 — Design system

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-014, REQ-015, REQ-060, REQ-061
> **Depends on:** [07 — Frontend](07-frontend.md), [10 — Security](10-security.md)

## 1. Purpose

What the interface looks like, and why — tokens, components, composition, and motion,
with enough rules that two people building different screens produce one product.

The interface this replaces was assembled from ad-hoc Tailwind utilities and a handful of
CSS variables invented per component. It worked, and it looked like a prototype: no type
scale, no spacing rhythm, no touch targets, no phone layout, and no visible difference
between what the assistant *claims* and what the records *say* — which in an operations
tool is not a cosmetic problem.

## 2. Scope

**In scope:** the token architecture, typography, the component library and where it comes
from, page composition at each breakpoint, motion during streaming, and the accessibility
floor.

**Out of scope:** screen-by-screen behaviour ([07](07-frontend.md)), the HTTP contract
([06](06-backend-api.md)), what the assistant is allowed to say ([17](17-agent-skills.md)).

---

## 3. Provenance

The system is adapted from an existing MongoDB-inspired design system used on another
product in this organisation: deep teal, bright green, white and pale-green surfaces, DM
Sans throughout, compact radii, flat bordered cards, restrained elevation. What is
inherited is the **system** — the token architecture, the type scale, the composition and
accessibility rules. What is not inherited is identity: CCOA has its own mark
(`src/components/Brand.tsx`), and none of the source product's copy, concepts, or assets
appear here.

Bright brand green is an **action and identity colour**. It never means safe, verified,
approved, or low-risk. Verified supporting evidence uses the semantic-positive tokens,
which are a different, deliberately duller green. This matters more here than in the
source product: an assistant that renders its own guesses in the same green the interface
uses for confirmed records is actively misleading.

## 4. Design

### 4.1 Token architecture

Three layers, in `frontend/src/index.css`:

```text
Primitive values  →  Semantic purpose  →  Component usage
--ccoa-green-400      --brand-green         bg-primary
```

* **Primitives** (`--ccoa-*`) define the system. A component that reaches for one has
  hard-coded a decision the system owns.
* **Semantics** (`--brand-*`, `--surface-*`, `--text-*`, `--border-*`, `--semantic-*`,
  `--space-*`, `--radius-*`, `--shadow-*`, `--motion-*`) are what components use.
* **Tailwind utilities** are generated from the semantic layer via `@theme inline`, so
  `bg-surface-feature` and `p-xl` resolve to tokens rather than to arbitrary values.

Dark mode redefines only the semantic layer under `.dark`. No component knows which mode
it is in.

**Rule:** never write a raw hex, an arbitrary pixel padding, or an arbitrary radius when a
token exists. `bg-[#00ed64]`, `p-[22px]`, and `rounded-[13px]` are all defects.

### 4.2 Typography

DM Sans, bundled via `@fontsource-variable/dm-sans` rather than fetched from Google
Fonts — the container ships `font-src 'self'`, so a CDN font is blocked outright and the
page silently falls back to a system font in exactly the environment nobody is inspecting.

Type styles are **composite classes** (`.text-heading-2`, `.text-body-sm`, `.text-button`,
`.text-micro-uppercase`, …) that set size, weight, line height, and tracking together.
Never assemble a type style from separate utilities: the scale exists so that two
components at the same level look the same.

They set no colour, so they pair with one: `text-heading-2 text-foreground`. `cn()`
registers them in tailwind-merge's `font-size` group so that pairing survives the merge —
see the comment in `src/lib/utils.ts` for the failure it prevents.

Monospace (`font-mono`, `.text-code`) is reserved for identifiers, timestamps, and aligned
technical values. It is the interface's signal for "this is a record id you can look up",
which is why citation chips and record cards use it and prose never does.

### 4.3 Components

`src/components/ui/` holds application-owned shadcn/ui-style primitives — `Button`,
`Card`, `Badge`, `Input`, `Skeleton`, `Sheet`. They are source, not a dependency: they are
edited in place. Radix supplies behaviour (focus trap, focus restore, `Escape`, scroll
lock, `aria-modal`) for anything that overlays, because that is the part that is tedious
to write and quietly wrong when hand-rolled.

Variants use `class-variance-authority` so a variant is a named decision rather than a
string of utilities copied between files.

Product components (`MessageList`, `ApprovalCard`, `ContextPanel`, `ActivityTrail`, …)
live one level up and compose primitives. Icons come from `lucide-react`.

Component contracts worth stating outright:

| Component | Contract |
|---|---|
| `Button` | pill radius, `text-button`, **minimum 44px target in every size** |
| `Card` | canvas surface, hairline border, `radius-lg`, **no shadow by default** |
| `Badge` | semantic background + semantic text, and always visible words |
| `Sheet` | the desktop rails, below `lg` |
| `Input` | `radius-md`, `border-strong`, minimum 44px height |

Shadows are for temporary or raised layers only. A pending approval gets one because it is
the one thing on screen that stops the work; ordinary cards do not.

### 4.4 Composition

The workspace is three regions on a wide screen:

```text
┌──────────────────────────────────────────────────────────────┐
│ Header, 80px: mark, active conversation, environment badge   │
├──────────────┬─────────────────────────┬─────────────────────┤
│ Conversations│ Conversation            │ Customer context    │
│ ~18%         │ remaining, max 46rem    │ ~22%                │
│              │                         │                     │
│ ────────────  │                         │                     │
│ Account       │                         │                     │
│ Sign out      │                         │                     │
└──────────────┴─────────────────────────┴─────────────────────┘
```

The conversation column is capped at `46rem` so answers stay in the 55–75 character range
that long-form text is readable at, rather than stretching across a 27-inch monitor. The
rails are proportional with hard stops — see [§4.7a](#47a-density).

**Identity and sign-out sit at the foot of the thread rail, not in the header.** That is
where this shape of tool puts them and where people look; it also keeps a destructive
action out of the one bar visible at every width, a mis-tap away from the panel toggles.
`mt-auto` and a border separate the account block from the history — without the gap the
last conversation and the sign-out button read as one list, which is how someone signs out
while trying to open a thread.

### 4.5 Responsive behaviour

**Mobile-first, and transformed by task priority — not by narrowing three columns.**

| Width | Composition |
|---|---|
| `>= 1024px` (`lg`) | all three regions visible |
| `< 1024px` | the conversation is the whole screen; both rails become sheets opened from the header |

The conversation is the primary task at every width, so it is the region that never moves.
The two rails are supporting context.

Each panel is mounted **exactly once**, in whichever region currently holds it —
`useMediaQuery(DESKTOP_QUERY)` decides, not `hidden lg:block`. Rendering both and hiding
one with CSS keeps both mounted: the thread list and the customer profile are fetched
twice, and two elements answer to the same `data-testid`. See `src/hooks/useMediaQuery.ts`.

Non-negotiable at every width:

- touch targets at least 44×44px;
- **no horizontal page scrolling** — wide content (tables, payload previews) scrolls inside
  its own container;
- the composer clears the iOS home indicator (`env(safe-area-inset-bottom)`) and keeps
  16px text, below which Safari zooms the page and never zooms back;
- reading and focus order survive the reflow.

`frontend/e2e/mobile.spec.ts` holds this line: a regression to squeezed columns passes
every desktop test in the suite.

### 4.6 Motion

Motion explains state change. It is never decoration, and it never delays access to
information.

| Token | Duration | Used for |
|---|---|---|
| `--motion-press` | 100ms | pressed feedback |
| `--motion-interactive` | 180ms | hover, focus, selection, colour transitions |
| `--motion-reveal` | 260ms | expand, collapse, sheet, message entry |
| `--motion-emphasis` | 420ms | rare, major emphasis |

Streaming is where this earns its place. A graph turn is several seconds of silence, and
silence is indistinguishable from a hang — so:

| Signal | What it means |
|---|---|
| thinking dots | a turn is running and **no token has arrived yet** |
| activity rows animating in, staggered 40ms | a `step` or `tool` event just arrived |
| spinner in the trail header | a tool call is open |
| blinking caret after the draft | the answer is still arriving, not truncated |
| dashed border on the draft | provisional — the `message` event replaces it wholesale |
| approval card rising in | the graph has stopped and is waiting for a human |
| **the activity trail tinted green** | the graph is working — *process*, never output |

Colour does the same job as motion here, and outlasts it: while a turn runs the activity
trail sits on `surface-feature` with a `brand-green-dark` label and the open tool call
highlighted, and it settles back to a plain bordered box when the turn ends. At a glance
that is what separates the assistant's *working* from the assistant's *answer* — and it
survives `prefers-reduced-motion`, where the spinner does not.

Two rules constrain all of it:

1. **Never fabricate activity.** Every row corresponds to an event the backend actually
   sent. A spinner that runs on a timer is a lie about what the system is doing.
2. **`prefers-reduced-motion` stops every animation and removes no information.** The
   caret stops blinking but still marks the insertion point; the trail still lists every
   step. Anything that disappears under reduced motion was carrying meaning it should
   never have carried alone.

### 4.7 Assistant output versus verified records

The decision-safety rule that shapes the whole screen: **the assistant interprets records;
it does not replace them.**

- Assistant messages are Markdown rendered through `Markdown.tsx` with **no raw HTML** —
  the content is model output built from customer data, and treating it as markup would be
  an injection path straight through the CSP.
- Headings inside a message render at label scale, so a model reaching for `#` cannot
  out-shout the page's real `h1`.
- Every claim carries citation chips, and a chip focuses the record it points at — on a
  phone it opens the context sheet, because highlighting a record behind a closed panel
  helps nobody.
- The activity trail is labelled "Assistant activity", never presented as evidence.
- The composer carries a standing disclaimer: *the assistant interprets records; it does
  not replace them.*
- For an `approve` checkpoint, the **exact payload that will be written** is shown, and the
  field summary is never hidden behind disclosure. Only the verbatim text folds.

### 4.7a Density

Three rules, each learned from a screen that had stopped being readable.

**Rails are supporting context and never out-weigh the conversation.** The widths are
proportional with hard stops — `clamp(216px, 18vw, 280px)` and `clamp(272px, 22vw, 340px)`,
roughly 18 / 60 / 22 on a 1440px screen. The ceiling is the part that matters: a
conversation list is full of long titles, and a rail sized by its content grows to fit the
worst one. (It did. `w-[--rail-width]` compiles to `width:--rail-width`, which is invalid
CSS and silently dropped — Tailwind v4 wants `w-(--rail-width)` — so the rail had no width
at all and the layout was closer to 40 / 40 / 20.)

**Repetition collapses.** Repeated calls to one tool render as a single row with a `×N`
count rather than N rows. The count preserves what the extra rows carried — how much work
happened — without the height.

**Inputs inside a bordered box do not draw their own ring.** The global `:focus-visible`
outline lives in `@layer base`, so a component whose *wrapper* shows focus — the composer,
every `Input` inside a bordered container — opts out with `outline-none` and gets one ring
instead of two nested ones. Unlayered, that rule outranked the utility and every such field
drew a second outline inside the border already highlighting it.

**Long lists truncate to a chip.** Past three, citations collapse into a `+N` that opens a
paginated dialog. A dozen chips wrapped over four lines does not just bury the answer, it
makes the citations useless: nobody scans a wall of identifiers.

### 4.8 Accessibility floor

- WCAG AA contrast; semantic colour always paired with text and an icon.
- Every control keyboard operable, with a visible focus ring (`:focus-visible` is defined
  globally and never removed without a replacement).
- Icon-only buttons carry accessible names.
- The streaming region announces **step labels only**, politely. A per-token live region
  makes a screen reader unusable during streaming.
- `prefers-reduced-motion` is honoured everywhere ([§4.6](#46-motion)).

## 5. Decisions and tradeoffs

| Decision | Why | Cost |
|---|---|---|
| Adapt an existing system rather than invent one | It is already coherent, already accessible, and already argued through | Some tokens (hero spacing, marketing type sizes) are unused here |
| shadcn/ui source-in-repo rather than a component package | Components need editing to fit the tokens; a package would be fought | The repo owns the maintenance |
| `framer-motion` rather than CSS transitions alone | Enter/exit animation for a list that changes mid-stream is genuinely hard in CSS | ~42KB gzip, isolated in its own chunk |
| `useMediaQuery` rather than `hidden lg:block` | Mounts each panel once; halves the queries and removes duplicate test ids | A JS breakpoint can disagree with a CSS one, so `lg` is defined in one constant |
| Bundle DM Sans | `font-src 'self'` blocks Google Fonts, silently | 55KB of woff2 in the image |
| Markdown without raw HTML | Model output rendered as markup is an injection path | Some formatting the model might attempt is dropped |

## 6. Failure modes

| Failure | Symptom | Guard |
|---|---|---|
| A CDN font under the container CSP | Correct locally, system font in the deployed app | Font is bundled; CSP verified by `docker/verify-image.sh` |
| `add_header` in a `location` discards inherited headers | **No CSP at all**, with a clean 200 | Headers in an include pulled into every location; asserted per location |
| Type class merged away by tailwind-merge | Wrong size, or a lost colour | `cn()` registers the composite classes; see `lib/utils.ts` |
| Panels rendered twice via CSS hiding | Duplicate fetches, ambiguous test ids | `useMediaQuery`; mobile e2e asserts one match |
| Motion carrying meaning | Reduced-motion users lose information | Every animation removable with nothing lost; asserted by inspection at review |
| Horizontal scroll on a phone | The whole page slides sideways | `e2e/mobile.spec.ts` asserts zero overflow |

## 7. Open questions

1. **Dark mode has no toggle.** The tokens are defined and `prefers-color-scheme` is not
   yet wired to the `.dark` class, so the dark palette is currently unreachable. Deliberate
   — it is untested against the contrast floor.
2. **No visual regression testing.** The e2e suite asserts structure and layout rules, not
   appearance. Screenshot testing was considered and rejected as too noisy for a corpus
   whose content is model-generated.
3. **The suggestion chips are not clickable.** A tap that spends a model call on a prompt
   the agent did not choose is worse than a tap that fills the composer; making them fill
   the composer instead is a small, unmade improvement.
