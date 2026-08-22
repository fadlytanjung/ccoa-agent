"""Seed corpus verification — docs/12 §3.8.

The assertion most likely to be broken by accident is the duplicate-name one. Someone
"fixing" two customers with the same name would silently delete the disambiguation
demo, so the test names that intent out loud.
"""

from __future__ import annotations

from app.domain.enums import ClaimStatus, FailureCode
from app.seed import generate
from app.seed.generator import (
    CUSTOMER_COUNT,
    KB_ARTICLE_COUNT,
    PLANTED_NAME,
    SEED,
    Corpus,
)

#: Locked in so a ratio change is a visible decision, not a drift (docs/12 §3.1).
EXPECTED_COUNTS = {
    "customers": 120,
    "policies": 213,
    "claims": 173,
    "cases": 89,
    "interactions": 608,
    "tickets": 145,
    "case_events": 309,
    "ticket_events": 353,
    "kb_articles": 40,
}


class TestDeterminism:
    def test_two_runs_are_byte_identical(self) -> None:
        assert generate(SEED).digest() == generate(SEED).digest()

    def test_a_different_seed_produces_a_different_corpus(self) -> None:
        assert generate(SEED).digest() != generate(SEED + 1).digest()

    def test_counts_are_locked(self) -> None:
        assert generate().counts() == EXPECTED_COUNTS

    def test_total_matches_the_spec(self) -> None:
        assert generate().total_rows() == sum(EXPECTED_COUNTS.values()) == 2050


class TestVolumes:
    def test_clears_the_stated_minimum(self, corpus: Corpus) -> None:
        assert len(corpus.customers) == CUSTOMER_COUNT >= 100
        assert len(corpus.interactions) >= 500

    def test_every_failure_code_has_an_article(self, corpus: Corpus) -> None:
        covered: set[str] = set()
        for article in corpus.kb_articles:
            covered.update(c for c in (article["applies_to"] or "").split(",") if c)
        assert {code.value for code in FailureCode} <= covered

    def test_article_count(self, corpus: Corpus) -> None:
        assert len(corpus.kb_articles) == KB_ARTICLE_COUNT


class TestPlantedScenarios:
    def test_exactly_two_customers_share_the_planted_name(self, corpus: Corpus) -> None:
        """Do not "fix" this.

        Two people named John Tan is what forces the `clarify` checkpoint on the very
        first reference prompt, so disambiguation is demonstrated rather than described
        (docs/12 §3.4). Deduplicating them would silently remove the demo.
        """
        named = [c for c in corpus.customers if c["full_name"] == PLANTED_NAME]
        assert len(named) == 2
        assert {c["customer_id"] for c in named} == {"CUST-000042", "CUST-000091"}

    def test_the_richer_customer_is_gold_with_two_active_policies(self, corpus: Corpus) -> None:
        policies = [p for p in corpus.policies if p["customer_id"] == "CUST-000042"]
        assert len(policies) == 2
        assert all(p["status"] == "active" for p in policies)
        assert {p["product"] for p in policies} == {"motor", "health"}

    def test_the_failed_claim_is_planted_with_its_code(self, corpus: Corpus) -> None:
        claim = next(c for c in corpus.claims if c["claim_id"] == "CLM-00000117")
        assert claim["status"] == ClaimStatus.SUBMISSION_FAILED.value
        assert claim["failure_code"] == FailureCode.DOC_UNREADABLE.value
        assert claim["policy_id"] == "POL-00000073"
        assert claim["customer_id"] == "CUST-000042"

    def test_the_open_case_has_no_tickets(self, corpus: Corpus) -> None:
        """The fourth reference prompt needs a case with nothing raised against it."""
        case = next(c for c in corpus.cases if c["case_id"] == "CASE-000008")
        assert case["status"] == "investigating"
        assert case["priority"] == "high"
        assert case["category"] == "claim_issue"
        assert case["claim_id"] == "CLM-00000117"
        assert not [t for t in corpus.tickets if t["case_id"] == "CASE-000008"]

    def test_the_investigation_chain_is_intact(self, corpus: Corpus) -> None:
        chain = {"INT-00000391", "INT-00000402", "INT-00000418"}
        linked = {i["interaction_id"] for i in corpus.interactions if i["case_id"] == "CASE-000008"}
        assert chain <= linked

    def test_the_planted_customer_has_seven_interactions(self, corpus: Corpus) -> None:
        rows = [i for i in corpus.interactions if i["customer_id"] == "CUST-000042"]
        assert len(rows) == 7
        assert {r["channel"] for r in rows} >= {"voice", "chat", "email"}

    def test_the_remediation_article_is_reachable(self, corpus: Corpus) -> None:
        article = next(a for a in corpus.kb_articles if a["article_id"] == "KB-0031")
        assert FailureCode.DOC_UNREADABLE.value in (article["applies_to"] or "")
        assert "DOC_UNREADABLE" in article["body"]


class TestRealism:
    def test_some_customers_have_no_claims(self, corpus: Corpus) -> None:
        """ "Not found" is a correct answer the assistant must be able to give."""
        with_claims = {c["customer_id"] for c in corpus.claims}
        without = [c for c in corpus.customers if c["customer_id"] not in with_claims]
        assert len(without) >= 10

    def test_failure_codes_are_skewed_not_uniform(self, corpus: Corpus) -> None:
        codes = [c["failure_code"] for c in corpus.claims if c["failure_code"]]
        counts = {code: codes.count(code) for code in set(codes)}
        top = max(counts, key=lambda k: counts[k])
        assert top in {FailureCode.DOC_UNREADABLE.value, FailureCode.DOC_MISSING.value}
        assert counts[top] > min(counts.values()) * 2

    def test_transcripts_are_capped(self, corpus: Corpus) -> None:
        assert max(len(i["transcript"]) for i in corpus.interactions) <= 2000

    def test_handlers_come_from_a_small_pool(self, corpus: Corpus) -> None:
        assert len({i["handled_by"] for i in corpus.interactions}) <= 12

    def test_no_wall_clock_leaked_into_timestamps(self, corpus: Corpus) -> None:
        # Every timestamp is an offset from EPOCH, so none may be after it.
        assert max(c["created_at"] for c in corpus.customers) <= "2026-08-21T23:59:59Z"


class TestReferentialIntegrity:
    def test_every_foreign_key_resolves(self, corpus: Corpus) -> None:
        customers = {c["customer_id"] for c in corpus.customers}
        policies = {p["policy_id"] for p in corpus.policies}
        claims = {c["claim_id"] for c in corpus.claims}
        cases = {c["case_id"] for c in corpus.cases}

        assert {p["customer_id"] for p in corpus.policies} <= customers
        assert {c["policy_id"] for c in corpus.claims} <= policies
        assert {c["customer_id"] for c in corpus.claims} <= customers
        assert {c["claim_id"] for c in corpus.cases if c["claim_id"]} <= claims
        assert {i["case_id"] for i in corpus.interactions if i["case_id"]} <= cases
        assert {t["case_id"] for t in corpus.tickets if t["case_id"]} <= cases

    def test_identifiers_are_unique(self, corpus: Corpus) -> None:
        for rows, key in (
            (corpus.customers, "customer_id"),
            (corpus.policies, "policy_id"),
            (corpus.claims, "claim_id"),
            (corpus.interactions, "interaction_id"),
            (corpus.cases, "case_id"),
            (corpus.tickets, "ticket_id"),
            (corpus.kb_articles, "article_id"),
        ):
            values = [row[key] for row in rows]
            assert len(values) == len(set(values)), f"duplicate {key}"

    def test_emails_are_unique(self, corpus: Corpus) -> None:
        emails = [c["email"] for c in corpus.customers]
        assert len(emails) == len(set(emails))
