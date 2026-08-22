"""Deterministic corpus generation — docs/12.

Two properties are load-bearing and everything here serves them:

* **The same seed produces byte-identical data.** No wall-clock time, no unseeded
  randomness, no set iteration, one RNG instance threaded through every choice. This is
  what makes grounding tests assertable and the ``SEED_VERSION`` contract coherent.
* **The reference prompts work verbatim.** docs/12 §3.4 plants specific records; they
  are placed on reserved identifiers (:mod:`app.seed.ids`) so a ratio change elsewhere
  cannot move them.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from app.domain import clock
from app.domain.enums import (
    CaseStatus,
    Category,
    ClaimChannel,
    ClaimStatus,
    CreatedVia,
    CustomerStatus,
    CustomerTier,
    Direction,
    FailureCode,
    InteractionChannel,
    PolicyProduct,
    PolicyStatus,
    Priority,
    Sentiment,
    TicketStatus,
)
from app.seed import content
from app.seed.ids import IdAllocator

#: Bump whenever generated data changes — volumes, planted records, realism rules, or
#: SEED itself. It namespaces the Litestream S3 prefix, so without the bump a task
#: booting after a reseed restores the *previous* generation and silently discards the
#: new corpus (docs/12 §3.6, ADR-007 §1a).
SEED_VERSION: Final = "v3"

SEED: Final = 20260821

#: Every timestamp is an offset from this instant. A generator that called
#: ``datetime.now()`` would produce a different corpus on every build.
EPOCH: Final = datetime(2026, 8, 21, 0, 0, 0, tzinfo=UTC)

CUSTOMER_COUNT: Final = 120
KB_ARTICLE_COUNT: Final = 40

# --- Planted scenario coordinates (docs/12 §3.4) ---------------------------
PLANTED_CUSTOMER: Final = 42
PLANTED_DUPLICATE_CUSTOMER: Final = 91
PLANTED_NAME: Final = "John Tan"
PLANTED_POLICY: Final = 73
PLANTED_CLAIM: Final = 117
PLANTED_CASE: Final = 8
PLANTED_INTERACTIONS: Final = (391, 402, 418)
PLANTED_ARTICLE: Final = content.PLANTED_ARTICLE_ID

#: Skewed, not uniform: document problems dominate real claim failures.
FAILURE_WEIGHTS: Final[tuple[tuple[FailureCode, int], ...]] = (
    (FailureCode.DOC_UNREADABLE, 30),
    (FailureCode.DOC_MISSING, 24),
    (FailureCode.VALIDATION_ERROR, 14),
    (FailureCode.GATEWAY_TIMEOUT, 12),
    (FailureCode.POLICY_LAPSED, 9),
    (FailureCode.DUPLICATE, 7),
    (FailureCode.LIMIT_EXCEEDED, 4),
)

#: Long-tailed: most customers contact us three or four times, a few many more. Uniform
#: volumes would hide the retrieval problem the assistant exists to solve.
INTERACTION_COUNT_WEIGHTS: Final[tuple[tuple[int, int], ...]] = (
    (3, 20),
    (4, 22),
    (5, 20),
    (6, 14),
    (7, 10),
    (8, 6),
    (10, 5),
    (12, 3),
)

#: Probability that a customer who already has one case has a second, unrelated one.
#: Keeps the case-to-interaction ratio near one in six (docs/12 §3.1).
SECOND_CASE_PROBABILITY: Final = 0.30

TIER_WEIGHTS: Final[tuple[tuple[CustomerTier, int], ...]] = (
    (CustomerTier.STANDARD, 52),
    (CustomerTier.SILVER, 28),
    (CustomerTier.GOLD, 15),
    (CustomerTier.PLATINUM, 5),
)

CLAIM_STATUS_WEIGHTS: Final[tuple[tuple[ClaimStatus, int], ...]] = (
    (ClaimStatus.PAID, 22),
    (ClaimStatus.APPROVED, 16),
    (ClaimStatus.UNDER_REVIEW, 16),
    (ClaimStatus.SUBMITTED, 14),
    (ClaimStatus.SUBMISSION_FAILED, 16),
    (ClaimStatus.REJECTED, 8),
    (ClaimStatus.DRAFT, 5),
    (ClaimStatus.WITHDRAWN, 3),
)


@dataclass(slots=True)
class Corpus:
    """Every row, in insertion order."""

    customers: list[dict[str, Any]] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    interactions: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[dict[str, Any]] = field(default_factory=list)
    case_events: list[dict[str, Any]] = field(default_factory=list)
    ticket_events: list[dict[str, Any]] = field(default_factory=list)
    kb_articles: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in asdict(self).items()}

    def total_rows(self) -> int:
        return sum(self.counts().values())

    def digest(self) -> str:
        """SHA-256 over the whole corpus, canonicalised.

        CI generates twice and compares this. A non-deterministic generator fails the
        build rather than producing a demo that drifts between deploys.
        """
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _weighted(rng: random.Random, options: tuple[tuple[Any, int], ...]) -> Any:
    values = [o[0] for o in options]
    weights = [o[1] for o in options]
    return rng.choices(values, weights=weights, k=1)[0]


def _stamp(days_ago: float, *, hour: int = 10, minute: int = 0) -> str:
    moment = EPOCH - timedelta(days=days_ago)
    return clock.to_iso(moment.replace(hour=hour % 24, minute=minute % 60, second=0))


class SeedGenerator:
    """Builds the corpus. One instance, one RNG, one deterministic result."""

    def __init__(self, seed: int = SEED) -> None:
        self.rng = random.Random(seed)
        self.corpus = Corpus()
        self.customer_ids = IdAllocator("CUST")
        self.policy_ids = IdAllocator("POL", {PLANTED_POLICY})
        self.claim_ids = IdAllocator("CLM", {PLANTED_CLAIM})
        self.case_ids = IdAllocator("CASE", {PLANTED_CASE})
        self.interaction_ids = IdAllocator("INT", set(PLANTED_INTERACTIONS))
        self.ticket_ids = IdAllocator("TKT")
        self.article_ids = IdAllocator("KB", {PLANTED_ARTICLE})

    # -- entry point -------------------------------------------------------
    def generate(self) -> Corpus:
        self._generate_kb()
        self._generate_customers()
        for row in list(self.corpus.customers):
            self._generate_for_customer(row)
        self._assert_planted()
        return self.corpus

    # -- knowledge base ----------------------------------------------------
    def _generate_kb(self) -> None:
        specs = content.ARTICLES
        if len(specs) != KB_ARTICLE_COUNT:
            raise ValueError(
                f"expected {KB_ARTICLE_COUNT} knowledge-base articles, found {len(specs)}"
            )

        planted_index = PLANTED_ARTICLE - 1
        for index, spec in enumerate(specs):
            if index == planted_index:
                article_id = self.article_ids.take(PLANTED_ARTICLE)
                body = content.KB_PLANTED_BODY
            else:
                article_id = self.article_ids.next()
                body = spec.render()
            self.corpus.kb_articles.append(
                {
                    "article_id": article_id,
                    "title": spec.title,
                    "category": spec.category,
                    "body": body,
                    "applies_to": ",".join(c.value for c in spec.applies_to) or None,
                    "updated_at": _stamp(30 + index),
                }
            )

        covered = {
            code
            for row in self.corpus.kb_articles
            for code in (row["applies_to"] or "").split(",")
            if code
        }
        missing = {c.value for c in FailureCode} - covered
        if missing:
            raise ValueError(f"no knowledge-base article covers: {sorted(missing)}")

    # -- customers ---------------------------------------------------------
    def _generate_customers(self) -> None:
        used_names: set[str] = set()
        for nth in range(1, CUSTOMER_COUNT + 1):
            customer_id = self.customer_ids.next()

            if nth in (PLANTED_CUSTOMER, PLANTED_DUPLICATE_CUSTOMER):
                full_name = PLANTED_NAME
                tier = CustomerTier.GOLD if nth == PLANTED_CUSTOMER else CustomerTier.SILVER
            else:
                full_name = self._unique_name(used_names)
                tier = _weighted(self.rng, TIER_WEIGHTS)
            used_names.add(full_name)

            slug = full_name.lower().replace(" ", ".")
            opened = self.rng.randint(200, 2200)
            self.corpus.customers.append(
                {
                    "customer_id": customer_id,
                    "full_name": full_name,
                    # Email carries the identifier so it is unique by construction —
                    # two John Tans must not collide on a UNIQUE column.
                    "email": f"{slug}.{nth}@example.com",
                    "phone": f"+65 {self.rng.randint(8000, 9999)}{self.rng.randint(1000, 9999)}",
                    "date_of_birth": _stamp(self.rng.randint(7500, 22000))[:10],
                    "address_line1": (
                        f"{self.rng.randint(1, 780)} "
                        f"{self.rng.choice(content.STREETS)} "
                        f"#{self.rng.randint(2, 28):02d}-{self.rng.randint(1, 220):03d}"
                    ),
                    "city": self.rng.choice(content.CITIES),
                    "postal_code": f"{self.rng.randint(100000, 829999)}",
                    "country": "SG",
                    "tier": tier.value,
                    "status": _weighted(
                        self.rng,
                        (
                            (CustomerStatus.ACTIVE, 92),
                            (CustomerStatus.SUSPENDED, 5),
                            (CustomerStatus.CLOSED, 3),
                        ),
                    ).value
                    if nth != PLANTED_CUSTOMER
                    else CustomerStatus.ACTIVE.value,
                    "preferred_lang": "en",
                    "risk_flag": 1 if self.rng.random() < 0.06 else 0,
                    "created_at": _stamp(opened),
                    "updated_at": _stamp(self.rng.randint(1, min(opened, 120))),
                }
            )

    def _unique_name(self, used: set[str]) -> str:
        """A name that is not already taken and never accidentally ``John Tan``.

        The duplicate-name scenario has to be exactly two people, or the disambiguation
        test in docs/12 §3.8 stops meaning anything.
        """
        for _ in range(200):
            candidate = (
                f"{self.rng.choice(content.GIVEN_NAMES)} {self.rng.choice(content.FAMILY_NAMES)}"
            )
            if candidate != PLANTED_NAME and candidate not in used:
                return candidate
        raise RuntimeError("exhausted the name pool; widen GIVEN_NAMES or FAMILY_NAMES")

    # -- per-customer graph ------------------------------------------------
    def _generate_for_customer(self, customer: dict[str, Any]) -> None:
        nth = int(customer["customer_id"].split("-")[1])
        is_planted = nth == PLANTED_CUSTOMER

        policies = self._generate_policies(customer, is_planted=is_planted)
        claims = self._generate_claims(customer, policies, is_planted=is_planted)
        cases = self._generate_cases(customer, claims, is_planted=is_planted)
        self._generate_interactions(customer, cases, claims, is_planted=is_planted)
        self._generate_tickets(customer, cases)

    def _generate_policies(
        self, customer: dict[str, Any], *, is_planted: bool
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        plan: tuple[tuple[PolicyProduct, PolicyStatus, int | None], ...]
        if is_planted:
            # Two active policies, and the motor one lands on the reserved identifier
            # the investigation chain in docs/12 §3.4 refers to.
            plan = (
                (PolicyProduct.MOTOR, PolicyStatus.ACTIVE, PLANTED_POLICY),
                (PolicyProduct.HEALTH, PolicyStatus.ACTIVE, None),
            )
        else:
            count = _weighted(self.rng, ((1, 46), (2, 38), (3, 16)))
            plan = tuple(
                (
                    self.rng.choice(list(PolicyProduct)),
                    _weighted(
                        self.rng,
                        (
                            (PolicyStatus.ACTIVE, 72),
                            (PolicyStatus.LAPSED, 12),
                            (PolicyStatus.CANCELLED, 9),
                            (PolicyStatus.PENDING, 7),
                        ),
                    ),
                    None,
                )
                for _ in range(count)
            )

        for product, status, reserved in plan:
            policy_id = self.policy_ids.take(reserved) if reserved else self.policy_ids.next()
            start = self.rng.randint(120, 1500)
            row = {
                "policy_id": policy_id,
                "customer_id": customer["customer_id"],
                "product": product.value,
                "status": status.value,
                "premium_cents": self.rng.randrange(38_000, 480_000, 500),
                "currency": "SGD",
                "effective_from": _stamp(start),
                "effective_to": None
                if status == PolicyStatus.ACTIVE
                else _stamp(max(1, start - 365)),
                "created_at": _stamp(start + 3),
            }
            rows.append(row)
            self.corpus.policies.append(row)
        return rows

    def _generate_claims(
        self, customer: dict[str, Any], policies: list[dict[str, Any]], *, is_planted: bool
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        if is_planted:
            motor = policies[0]
            claim_id = self.claim_ids.take(PLANTED_CLAIM)
            row = {
                "claim_id": claim_id,
                "policy_id": motor["policy_id"],
                "customer_id": customer["customer_id"],
                "status": ClaimStatus.SUBMISSION_FAILED.value,
                "failure_code": FailureCode.DOC_UNREADABLE.value,
                "failure_detail": (
                    "Optical character recognition could not extract the required fields "
                    "from the uploaded workshop invoice. Three submission attempts have "
                    "failed with the same result."
                ),
                "amount_cents": 184_500,
                "currency": "SGD",
                "incident_date": _stamp(21)[:10],
                "submitted_at": _stamp(4, hour=14, minute=12),
                "channel": ClaimChannel.MOBILE.value,
                "created_at": _stamp(18, hour=9, minute=30),
                "updated_at": _stamp(4, hour=14, minute=12),
            }
            rows.append(row)
            self.corpus.claims.append(row)
            return rows

        # ~15% of customers have no claims at all: "nothing found" is a correct answer
        # the assistant must be able to give (docs/12 §3.5).
        if self.rng.random() < 0.15 or not policies:
            return rows

        for _ in range(self.rng.choice((1, 1, 2, 2, 3))):
            policy = self.rng.choice(policies)
            status = _weighted(self.rng, CLAIM_STATUS_WEIGHTS)
            failed = status == ClaimStatus.SUBMISSION_FAILED
            code = _weighted(self.rng, FAILURE_WEIGHTS) if failed else None
            incident = self.rng.randint(5, 400)
            claim_id = self.claim_ids.next()
            row = {
                "claim_id": claim_id,
                "policy_id": policy["policy_id"],
                "customer_id": customer["customer_id"],
                "status": status.value,
                "failure_code": code.value if code else None,
                "failure_detail": (
                    f"Submission rejected by validation with {code.value}." if code else None
                ),
                "amount_cents": self.rng.randrange(12_000, 1_450_000, 500),
                "currency": "SGD",
                "incident_date": _stamp(incident)[:10],
                "submitted_at": None
                if status == ClaimStatus.DRAFT
                else _stamp(max(1, incident - 2)),
                "channel": self.rng.choice(list(ClaimChannel)).value,
                "created_at": _stamp(incident),
                "updated_at": _stamp(max(1, incident - self.rng.randint(0, 10))),
            }
            rows.append(row)
            self.corpus.claims.append(row)
        return rows

    def _generate_cases(
        self, customer: dict[str, Any], claims: list[dict[str, Any]], *, is_planted: bool
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        if is_planted:
            case_id = self.case_ids.take(PLANTED_CASE)
            opened = _stamp(17, hour=11, minute=5)
            row = {
                "case_id": case_id,
                "customer_id": customer["customer_id"],
                "claim_id": claims[0]["claim_id"],
                "title": "Repeated claim submission failure",
                "category": Category.CLAIM_ISSUE.value,
                "status": CaseStatus.INVESTIGATING.value,
                "priority": Priority.HIGH.value,
                "summary": (
                    "Customer has attempted to submit a motor claim three times. Each "
                    "attempt fails with DOC_UNREADABLE. Awaiting document review."
                ),
                "owner": content.HANDLERS[2],
                "escalated_to": None,
                "opened_at": opened,
                "resolved_at": None,
                "created_at": opened,
                "updated_at": _stamp(3, hour=16, minute=40),
            }
            rows.append(row)
            self.corpus.cases.append(row)
            self._generate_case_events(row, planted=True)
            return rows

        # Roughly one case per six interactions, driven off claims where one exists.
        failed_claims = [c for c in claims if c["status"] == ClaimStatus.SUBMISSION_FAILED.value]
        wants_case = failed_claims or self.rng.random() < 0.42
        if not wants_case:
            return rows

        rows.append(self._make_case(customer, failed_claims[0] if failed_claims else None))
        if self.rng.random() < SECOND_CASE_PROBABILITY:
            rows.append(self._make_case(customer, None))
        return rows

    def _make_case(self, customer: dict[str, Any], claim: dict[str, Any] | None) -> dict[str, Any]:
        category = (
            Category.CLAIM_ISSUE
            if claim
            else self.rng.choice([c for c in Category if c != Category.CLAIM_ISSUE])
        )
        status = _weighted(
            self.rng,
            (
                (CaseStatus.RESOLVED, 34),
                (CaseStatus.CLOSED, 22),
                (CaseStatus.INVESTIGATING, 14),
                (CaseStatus.OPEN, 12),
                (CaseStatus.PENDING_CUSTOMER, 10),
                (CaseStatus.ESCALATED, 8),
            ),
        )
        opened_days = self.rng.randint(4, 260)
        case_id = self.case_ids.next()
        resolved = status in (CaseStatus.RESOLVED, CaseStatus.CLOSED)
        row = {
            "case_id": case_id,
            "customer_id": customer["customer_id"],
            "claim_id": claim["claim_id"] if claim else None,
            "title": self.rng.choice(content.SUBJECTS[category]),
            "category": category.value,
            "status": status.value,
            "priority": _weighted(
                self.rng,
                (
                    (Priority.MEDIUM, 44),
                    (Priority.LOW, 26),
                    (Priority.HIGH, 24),
                    (Priority.CRITICAL, 6),
                ),
            ).value,
            "summary": self._case_summary(category, claim),
            "owner": self.rng.choice(content.HANDLERS),
            "escalated_to": "Tier 2 Support" if status == CaseStatus.ESCALATED else None,
            "opened_at": _stamp(opened_days, hour=self.rng.randint(9, 17)),
            "resolved_at": _stamp(max(1, opened_days - self.rng.randint(1, 20)))
            if resolved
            else None,
            "created_at": _stamp(opened_days, hour=self.rng.randint(9, 17)),
            "updated_at": _stamp(max(1, opened_days - self.rng.randint(0, 15))),
        }
        self.corpus.cases.append(row)
        self._generate_case_events(row, planted=False)
        return row

    def _case_summary(self, category: Category, claim: dict[str, Any] | None) -> str:
        if claim and claim["failure_code"]:
            return (
                f"Claim {claim['claim_id']} failed submission with "
                f"{claim['failure_code']}. Investigating with the customer."
            )
        return f"Customer raised a {category.value.replace('_', ' ')} issue. Under review."

    def _generate_case_events(self, case: dict[str, Any], *, planted: bool) -> None:
        if planted:
            timeline = (
                ("opened", "Case opened after second failed submission.", 17),
                ("note_added", "Confirmed failure code DOC_UNREADABLE on all attempts.", 12),
                ("note_added", "Customer re-uploaded; third attempt failed identically.", 6),
                ("status_changed", "Status set to investigating pending document review.", 3),
            )
            for event_type, detail, days in timeline:
                self.corpus.case_events.append(
                    {
                        "case_id": case["case_id"],
                        "event_type": event_type,
                        "detail": detail,
                        "actor": content.HANDLERS[2],
                        "occurred_at": _stamp(days, hour=11),
                    }
                )
            return

        opened_days = (EPOCH - clock.parse(case["opened_at"])).days
        for nth in range(self.rng.randint(2, 5)):
            offset = max(0, opened_days - nth * self.rng.randint(1, 6))
            self.corpus.case_events.append(
                {
                    "case_id": case["case_id"],
                    "event_type": self.rng.choice(
                        ("opened", "note_added", "status_changed", "owner_assigned")
                    ),
                    "detail": self.rng.choice(
                        (
                            "Reviewed the customer's account history.",
                            "Contacted the customer for further detail.",
                            "Awaiting a response from the specialist team.",
                            "Updated the case status after review.",
                            "Confirmed the policy position with underwriting.",
                        )
                    ),
                    "actor": case["owner"] or content.HANDLERS[0],
                    "occurred_at": _stamp(offset, hour=self.rng.randint(9, 18)),
                }
            )

    def _generate_interactions(
        self,
        customer: dict[str, Any],
        cases: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        *,
        is_planted: bool,
    ) -> None:
        if is_planted:
            self._generate_planted_interactions(customer, cases[0])
            return

        count = _weighted(self.rng, INTERACTION_COUNT_WEIGHTS)
        case = cases[0] if cases else None
        case_opened_days = (EPOCH - clock.parse(case["opened_at"])).days if case else None
        # Sentiment skews negative where a claim failed — summaries then have something
        # for the assistant to detect (docs/12 §3.5).
        has_failure = any(c["status"] == ClaimStatus.SUBMISSION_FAILED.value for c in claims)

        for nth in range(count):
            # Interactions cluster around case activity rather than scattering evenly,
            # so chronology carries signal.
            clustered = case is not None and self.rng.random() < 0.45
            if clustered and case_opened_days is not None:
                days = max(1, case_opened_days - self.rng.randint(-2, 12))
            else:
                days = self.rng.randint(2, 380)

            category = (
                Category(case["category"])
                if clustered and case
                else self.rng.choice(list(Category))
            )
            channel = _weighted(
                self.rng,
                (
                    (InteractionChannel.VOICE, 40),
                    (InteractionChannel.CHAT, 30),
                    (InteractionChannel.EMAIL, 22),
                    (InteractionChannel.CALLBACK, 8),
                ),
            )
            sentiment = _weighted(
                self.rng,
                ((Sentiment.NEGATIVE, 55), (Sentiment.NEUTRAL, 35), (Sentiment.POSITIVE, 10))
                if has_failure
                else ((Sentiment.NEUTRAL, 55), (Sentiment.POSITIVE, 28), (Sentiment.NEGATIVE, 17)),
            )
            handler = self.rng.choice(content.HANDLERS)
            subject = self.rng.choice(content.SUBJECTS[category])

            self.corpus.interactions.append(
                {
                    "interaction_id": self.interaction_ids.next(),
                    "customer_id": customer["customer_id"],
                    "case_id": case["case_id"] if clustered and case else None,
                    "channel": channel.value,
                    "direction": (
                        Direction.OUTBOUND.value
                        if channel == InteractionChannel.CALLBACK
                        else Direction.INBOUND.value
                    ),
                    "subject": subject,
                    "transcript": self._transcript(channel, category, handler),
                    "summary": self._summary(subject, category, sentiment),
                    "sentiment": sentiment.value,
                    "handled_by": handler,
                    "duration_sec": self.rng.randint(90, 1500)
                    if channel != InteractionChannel.EMAIL
                    else 0,
                    "occurred_at": _stamp(
                        days, hour=self.rng.randint(9, 19), minute=self.rng.randint(0, 59)
                    ),
                    "created_at": _stamp(days, hour=self.rng.randint(9, 19)),
                }
            )
            del nth

    def _generate_planted_interactions(
        self, customer: dict[str, Any], case: dict[str, Any]
    ) -> None:
        """Seven interactions across three channels, spanning 90 days, mixed sentiment.

        Three of them are the reserved investigation chain: an agent following the
        evidence should be able to reconstruct what the customer actually did.
        """
        chain = (
            (
                PLANTED_INTERACTIONS[0],
                InteractionChannel.CHAT,
                "Claim upload keeps failing",
                "Customer reports the claim upload fails every time. Advised to retry "
                "with a clearer photograph of the workshop invoice.",
                Sentiment.NEGATIVE,
                16,
            ),
            (
                PLANTED_INTERACTIONS[1],
                InteractionChannel.VOICE,
                "Third attempt, still rejected",
                "Customer has now attempted three uploads. All rejected with the same "
                "document error. Case opened for document review.",
                Sentiment.NEGATIVE,
                9,
            ),
            (
                PLANTED_INTERACTIONS[2],
                InteractionChannel.EMAIL,
                "Sending photos instead",
                "Customer asked whether the invoice can be emailed instead of uploaded. "
                "Explained that emailed documents bypass validation and delay assessment.",
                Sentiment.NEUTRAL,
                4,
            ),
        )
        for reserved, channel, subject, summary, sentiment, days in chain:
            self.corpus.interactions.append(
                {
                    "interaction_id": self.interaction_ids.take(reserved),
                    "customer_id": customer["customer_id"],
                    "case_id": case["case_id"],
                    "channel": channel.value,
                    "direction": Direction.INBOUND.value,
                    "subject": subject,
                    "transcript": self._transcript(
                        channel, Category.CLAIM_ISSUE, content.HANDLERS[2]
                    ),
                    "summary": summary,
                    "sentiment": sentiment.value,
                    "handled_by": content.HANDLERS[2],
                    "duration_sec": 0 if channel == InteractionChannel.EMAIL else 620,
                    "occurred_at": _stamp(days, hour=14, minute=20),
                    "created_at": _stamp(days, hour=14, minute=25),
                }
            )

        # Four unrelated contacts, so summarising the history is real work rather than
        # reading three obviously-connected rows.
        others = (
            (InteractionChannel.VOICE, Category.BILLING, Sentiment.NEUTRAL, 86),
            (InteractionChannel.CHAT, Category.COVERAGE_QUERY, Sentiment.POSITIVE, 61),
            (InteractionChannel.EMAIL, Category.POLICY_CHANGE, Sentiment.NEUTRAL, 44),
            (InteractionChannel.VOICE, Category.CLAIM_ISSUE, Sentiment.NEGATIVE, 24),
        )
        for channel, category, sentiment, days in others:
            handler = content.HANDLERS[(days) % len(content.HANDLERS)]
            subject = content.SUBJECTS[category][days % len(content.SUBJECTS[category])]
            self.corpus.interactions.append(
                {
                    "interaction_id": self.interaction_ids.next(),
                    "customer_id": customer["customer_id"],
                    "case_id": None,
                    "channel": channel.value,
                    "direction": Direction.INBOUND.value,
                    "subject": subject,
                    "transcript": self._transcript(channel, category, handler),
                    "summary": self._summary(subject, category, sentiment),
                    "sentiment": sentiment.value,
                    "handled_by": handler,
                    "duration_sec": 0 if channel == InteractionChannel.EMAIL else 480,
                    "occurred_at": _stamp(days, hour=11, minute=15),
                    "created_at": _stamp(days, hour=11, minute=20),
                }
            )

    def _generate_tickets(self, customer: dict[str, Any], cases: list[dict[str, Any]]) -> None:
        for case in cases:
            # CASE-000008 must have zero tickets: the fourth reference prompt needs an
            # open case with nothing raised against it yet (docs/12 §3.4).
            if case["case_id"].endswith(f"{PLANTED_CASE:06d}"):
                continue
            for _ in range(_weighted(self.rng, ((0, 12), (1, 45), (2, 30), (3, 13)))):
                self._append_ticket(customer, case)

        # A few tickets exist without a case — raised directly by an agent.
        if not cases and self.rng.random() < 0.18:
            self._append_ticket(customer, None)

    def _append_ticket(self, customer: dict[str, Any], case: dict[str, Any] | None) -> None:
        ticket_id = self.ticket_ids.next()
        category = Category(case["category"]) if case else self.rng.choice(list(Category))
        opened_days = (
            (EPOCH - clock.parse(case["opened_at"])).days if case else self.rng.randint(3, 200)
        )
        created = max(1, opened_days - self.rng.randint(0, 4))
        status = _weighted(
            self.rng,
            (
                (TicketStatus.RESOLVED, 34),
                (TicketStatus.CLOSED, 20),
                (TicketStatus.IN_PROGRESS, 20),
                (TicketStatus.OPEN, 18),
                (TicketStatus.PENDING, 8),
            ),
        )
        handler = self.rng.choice(content.HANDLERS)
        title = case["title"] if case else self.rng.choice(content.SUBJECTS[category])
        row = {
            "ticket_id": ticket_id,
            "customer_id": customer["customer_id"],
            "case_id": case["case_id"] if case else None,
            "title": title,
            "description": (
                f"{title}. Raised for customer {customer['customer_id']} "
                f"({category.value.replace('_', ' ')}). See case history for context."
            ),
            "category": category.value,
            "priority": case["priority"] if case else Priority.MEDIUM.value,
            "status": status.value,
            "assignee": handler,
            "created_by": handler,
            "created_via": CreatedVia.AGENT_MANUAL.value,
            "created_at": _stamp(created, hour=self.rng.randint(9, 18)),
            "updated_at": _stamp(max(1, created - self.rng.randint(0, 6))),
        }
        self.corpus.tickets.append(row)

        for nth in range(self.rng.randint(1, 4)):
            self.corpus.ticket_events.append(
                {
                    "ticket_id": ticket_id,
                    "event_type": self.rng.choice(
                        ("created", "assigned", "comment", "status_changed")
                    ),
                    "detail": self.rng.choice(
                        (
                            "Ticket created from the case.",
                            "Assigned to the specialist queue.",
                            "Awaiting information from the customer.",
                            "Resolution confirmed with the customer.",
                            "Reviewed and updated the priority.",
                        )
                    ),
                    "actor": handler,
                    "occurred_at": _stamp(max(0, created - nth), hour=self.rng.randint(9, 18)),
                }
            )

    # -- text composition --------------------------------------------------
    def _transcript(self, channel: InteractionChannel, category: Category, handler: str) -> str:
        """Compose a transcript from channel-appropriate fragments.

        Capped at ~2 KB: long transcripts inflate both the database and the model's
        context, and the summary carries the signal anyway (docs/04 §6 question 1).
        """
        lines = [
            self.rng.choice(content.OPENINGS[channel.value]).format(handler=handler),
            self.rng.choice(content.CUSTOMER_LINES[category]),
            self.rng.choice(content.AGENT_LINES),
        ]
        for _ in range(self.rng.randint(1, 3)):
            lines.append(self.rng.choice(content.CUSTOMER_LINES[category]))
            lines.append(self.rng.choice(content.AGENT_LINES))
        lines.append(self.rng.choice(content.RESOLUTIONS))
        lines.append(self.rng.choice(content.CLOSINGS[channel.value]))

        text = "\n".join(lines)
        return text if len(text) <= 2000 else text[:1997] + "..."

    def _summary(self, subject: str, category: Category, sentiment: Sentiment) -> str:
        tone = {
            Sentiment.NEGATIVE: "Customer was frustrated",
            Sentiment.NEUTRAL: "Customer was matter-of-fact",
            Sentiment.POSITIVE: "Customer was satisfied",
        }[sentiment]
        outcome = self.rng.choice(
            (
                "Explained the position and confirmed the next step.",
                "Logged the detail and advised a follow-up window.",
                "Resolved on the contact; no further action needed.",
                "Referred to the specialist team for a decision.",
            )
        )
        return f"{subject}. {tone}. {outcome}"

    # -- invariants --------------------------------------------------------
    def _assert_planted(self) -> None:
        """Fail generation rather than ship a corpus the reference prompts miss."""
        for allocator, label in (
            (self.policy_ids, "policy"),
            (self.claim_ids, "claim"),
            (self.case_ids, "case"),
            (self.interaction_ids, "interaction"),
            (self.article_ids, "article"),
        ):
            outstanding = allocator.unclaimed_reservations()
            if outstanding:
                raise RuntimeError(
                    f"planted {label} identifiers were never used: {sorted(outstanding)}"
                )

        named = [c for c in self.corpus.customers if c["full_name"] == PLANTED_NAME]
        if len(named) != 2:
            raise RuntimeError(
                f"expected exactly 2 customers named {PLANTED_NAME!r}, found {len(named)}"
            )

        planted_case_id = f"CASE-{PLANTED_CASE:06d}"
        if any(t["case_id"] == planted_case_id for t in self.corpus.tickets):
            raise RuntimeError(f"{planted_case_id} must have no tickets")


def generate(seed: int = SEED) -> Corpus:
    """Build the corpus. Pure — no I/O, no clock, no environment."""
    return SeedGenerator(seed).generate()
