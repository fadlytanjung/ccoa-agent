"""Read tools — business operations, not database accessors.

The model never sees SQL, table names, or joins. It sees ``list_claims(customer_id,
status)``, and what comes back is a typed result it can route on.

Every public method returns :class:`ToolResult` and **never raises**. That is enforced
structurally by :func:`tool_boundary` rather than by remembering to write a try block:
a raised exception would abort the run and throw away evidence already gathered
(docs/03 §3.6).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agents.registry import SkillError, SkillRegistry
from app.config import Settings
from app.domain import ids
from app.domain.errors import ErrorClass, ToolError, forbidden, internal, invalid_input, not_found
from app.graph.tools.result import ToolResult
from app.repositories import Repositories
from app.services.retrieval import RetrievalService

log = logging.getLogger(__name__)


def tool_boundary[**P](func: Callable[P, ToolResult]) -> Callable[P, ToolResult]:
    """Convert any escaping exception into a returned :class:`ToolError`.

    This is the single place in the codebase that catches broadly, and it is deliberate:
    the graph's contract is that tools return failures rather than raising them, so the
    boundary has to be total. Narrowing it would mean an unanticipated exception class
    silently breaks that contract at runtime.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # the boundary is total by design — see docstring
            log.exception("tool %s failed", func.__name__)
            return ToolResult.failure(
                internal(f"{func.__name__} failed: {exc.__class__.__name__}", node=func.__name__)
            )

    return wrapper


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything the tools need. Constructed once per process."""

    repos: Repositories
    settings: Settings
    registry: SkillRegistry
    retrieval: RetrievalService


def _require_id(value: str, prefix: str, label: str) -> ToolError | None:
    """Validate an identifier at the boundary. A malformed ID never reaches a query."""
    if not ids.is_valid(value, prefix):
        return invalid_input(
            f"{label} must look like {ids.format_id(prefix, 1)}, got {value!r}",
            field=label,
        )
    return None


class ToolBox:
    """The read surface. One instance per process."""

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx

    # -- customers ---------------------------------------------------------
    @tool_boundary
    def search_customer(self, query: str, limit: int = 10) -> ToolResult:
        matches = self.ctx.repos.customers.search(query, limit=limit)
        return ToolResult.success(
            {
                "query": query,
                "match_count": len(matches),
                # Returning every match is the contract, not an implementation detail:
                # the caller must not be able to receive a silently-chosen winner.
                "matches": [m.model_dump(mode="json") for m in matches],
                "ambiguous": len(matches) > 1,
            },
            refs=tuple(f"customer:{m.customer_id}" for m in matches),
        )

    @tool_boundary
    def get_customer(self, customer_id: str) -> ToolResult:
        if error := _require_id(customer_id, "CUST", "customer_id"):
            return ToolResult.failure(error)

        profile = self.ctx.repos.customers.profile(customer_id)
        if profile is None:
            return ToolResult.failure(not_found("customer", customer_id))

        refs = (f"customer:{customer_id}", *(f"policy:{p.policy_id}" for p in profile.policies))
        return ToolResult.success(profile.model_dump(mode="json"), refs=refs)

    # -- interactions ------------------------------------------------------
    @tool_boundary
    def list_interactions(
        self,
        customer_id: str,
        limit: int = 10,
        since: str | None = None,
        channel: str | None = None,
    ) -> ToolResult:
        if error := _require_id(customer_id, "CUST", "customer_id"):
            return ToolResult.failure(error)
        if not self.ctx.repos.customers.exists(customer_id):
            return ToolResult.failure(not_found("customer", customer_id))

        rows = self.ctx.repos.interactions.list_for_customer(
            customer_id, limit=limit, since=since, channel=channel
        )
        total = self.ctx.repos.interactions.count_for_customer(customer_id)
        return ToolResult.success(
            {
                "customer_id": customer_id,
                "returned": len(rows),
                # The model needs to know it is looking at a window, or it will
                # summarise ten of forty contacts as though they were all of them.
                "total_available": total,
                "truncated": total > len(rows),
                "interactions": [r.model_dump(mode="json") for r in rows],
            },
            refs=tuple(f"interaction:{r.interaction_id}" for r in rows),
        )

    @tool_boundary
    def search_interactions(self, customer_id: str, query: str, limit: int = 5) -> ToolResult:
        if error := _require_id(customer_id, "CUST", "customer_id"):
            return ToolResult.failure(error)

        hits, method = self.ctx.retrieval.search_interactions(customer_id, query, limit=limit)
        return ToolResult.success(
            {
                "customer_id": customer_id,
                "query": query,
                # Stated, not implied: keyword recall is weaker, so "nothing found" is
                # weaker evidence and the answer should say so (docs/05 §3.11).
                "retrieval_method": method,
                "hits": [h.model_dump(mode="json") for h in hits],
            },
            refs=tuple(f"interaction:{h.interaction_id}" for h in hits),
        )

    # -- claims ------------------------------------------------------------
    @tool_boundary
    def list_claims(
        self, customer_id: str, status: str | None = None, limit: int = 20
    ) -> ToolResult:
        if error := _require_id(customer_id, "CUST", "customer_id"):
            return ToolResult.failure(error)
        if not self.ctx.repos.customers.exists(customer_id):
            return ToolResult.failure(not_found("customer", customer_id))

        rows = self.ctx.repos.claims.list_for_customer(customer_id, status=status, limit=limit)
        return ToolResult.success(
            {
                "customer_id": customer_id,
                "status_filter": status,
                "count": len(rows),
                "claims": [r.model_dump(mode="json") for r in rows],
            },
            refs=tuple(f"claim:{r.claim_id}" for r in rows),
        )

    @tool_boundary
    def get_claim(self, claim_id: str) -> ToolResult:
        if error := _require_id(claim_id, "CLM", "claim_id"):
            return ToolResult.failure(error)

        claim = self.ctx.repos.claims.get(claim_id)
        if claim is None:
            return ToolResult.failure(not_found("claim", claim_id))

        payload = claim.model_dump(mode="json")
        payload["cases"] = [
            c.model_dump(mode="json") for c in self.ctx.repos.cases.list_for_claim(claim_id)
        ]
        refs = (
            f"claim:{claim_id}",
            f"policy:{claim.policy_id}",
            *(f"case:{c['case_id']}" for c in payload["cases"]),
        )
        return ToolResult.success(payload, refs=refs)

    # -- cases -------------------------------------------------------------
    @tool_boundary
    def list_cases(
        self, customer_id: str, status: str | None = None, limit: int = 20
    ) -> ToolResult:
        if error := _require_id(customer_id, "CUST", "customer_id"):
            return ToolResult.failure(error)
        if not self.ctx.repos.customers.exists(customer_id):
            return ToolResult.failure(not_found("customer", customer_id))

        rows = self.ctx.repos.cases.list_for_customer(customer_id, status=status, limit=limit)
        return ToolResult.success(
            {
                "customer_id": customer_id,
                "status_filter": status,
                "count": len(rows),
                "cases": [r.model_dump(mode="json") for r in rows],
            },
            refs=tuple(f"case:{r.case_id}" for r in rows),
        )

    @tool_boundary
    def get_case(self, case_id: str) -> ToolResult:
        if error := _require_id(case_id, "CASE", "case_id"):
            return ToolResult.failure(error)

        detail = self.ctx.repos.cases.detail(case_id)
        if detail is None:
            return ToolResult.failure(not_found("case", case_id))

        payload = detail.model_dump(mode="json")
        # An empty ticket list is a fact the resolution skill acts on, so make it
        # explicit rather than something the model has to notice.
        payload["has_tickets"] = bool(detail.ticket_ids)
        return ToolResult.success(payload, refs=(f"case:{case_id}",))

    # -- knowledge base ----------------------------------------------------
    @tool_boundary
    def search_kb(self, query: str, limit: int = 5) -> ToolResult:
        hits, method = self.ctx.retrieval.search_kb(query, limit=limit)
        return ToolResult.success(
            {
                "query": query,
                "retrieval_method": method,
                "count": len(hits),
                "articles": [h.model_dump(mode="json") for h in hits],
            },
            refs=tuple(f"kb:{h.article_id}" for h in hits),
        )

    # -- skill references (tier 3) ----------------------------------------
    @tool_boundary
    def read_reference(self, skill: str, path: str) -> ToolResult:
        """Read a reference document belonging to the calling skill.

        Traversal is rejected inside the registry; a rejection surfaces here as a
        ``forbidden`` result and is audited, because an attempt to read outside the
        skill directory is a security event rather than a typo.
        """
        declared = self.ctx.registry.get(skill).frontmatter.references

        # A model that drops the directory prefix should not lose a turn over it.
        # Resolving by filename costs nothing and is bounded by the declared list, so
        # it cannot reach anything the skill did not already offer.
        resolved = path
        if resolved not in declared:
            matches = [r for r in declared if r.rsplit("/", 1)[-1] == path.rsplit("/", 1)[-1]]
            if len(matches) == 1:
                resolved = matches[0]

        try:
            body = self.ctx.registry.reference(skill, resolved)
        except SkillError as exc:
            # The error names what *is* available. A failure that just says "no" leaves
            # the model to guess again; one that lists the options lets it recover
            # inside the same investigation.
            return ToolResult.failure(
                ToolError(
                    error_class=ErrorClass.INVALID_INPUT,
                    code="reference_unavailable",
                    message=f"{exc}. Available: {', '.join(declared) or 'none'}",
                    detail={"skill": skill, "path": path},
                )
            )
        return ToolResult.success(
            {"skill": skill, "path": resolved, "content": body},
            refs=(f"reference:{skill}/{resolved}",),
        )


def authorise(actor_groups: tuple[str, ...], action: str, required_group: str) -> ToolError | None:
    """Group check for a mutating action. Used by ``commit``, never by a tool."""
    if required_group not in actor_groups:
        return forbidden(action, required_group)
    return None


#: Tools that may be bound to a model. Mutating tools are deliberately absent — there is
#: no prompt that can talk the model into writing, because the capability is not there.
READ_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_customer",
        "get_customer",
        "list_interactions",
        "search_interactions",
        "list_claims",
        "get_claim",
        "list_cases",
        "get_case",
        "search_kb",
        "read_reference",
    }
)

MUTATING_TOOL_NAMES: frozenset[str] = frozenset({"create_ticket", "escalate_case"})

ALL_TOOL_NAMES: frozenset[str] = READ_TOOL_NAMES | MUTATING_TOOL_NAMES


def dispatch(box: ToolBox, name: str, args: dict[str, Any]) -> ToolResult:
    """Invoke a read tool by name, validating that it is one.

    Guards against a model hallucinating a tool name that happens to match a method on
    :class:`ToolBox` — only the declared read surface is reachable.
    """
    if name not in READ_TOOL_NAMES:
        return ToolResult.failure(invalid_input(f"unknown tool {name!r}", field="tool", tool=name))
    method = getattr(box, name)
    return method(**args)  # type: ignore[no-any-return]
