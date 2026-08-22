"""Read-only context routes — docs/06 §3.2.

These exist so the sidebar can render context without going through the graph. They are
**read-only by construction**: there is no non-graph write path in this API, which keeps
"every mutation is approved and audited" a structural property rather than a convention
(docs/00 §6).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from app.api.deps import AgentActor
from app.domain.errors import NotFound
from app.domain.ids import (
    CASE_ID_PATTERN,
    CLAIM_ID_PATTERN,
    CUSTOMER_ID_PATTERN,
    TICKET_ID_PATTERN,
)
from app.domain.models import (
    CaseDetail,
    Claim,
    CustomerMatch,
    CustomerProfile,
    InteractionSummary,
    SupportCase,
    TicketDetail,
)
from app.repositories import Repositories

router = APIRouter(tags=["context"])

# Validated at the boundary, so a malformed identifier is a 422 before any query runs
# (docs/04 §3.2).
CustomerIdPath = Annotated[str, Path(pattern=CUSTOMER_ID_PATTERN)]
CaseIdPath = Annotated[str, Path(pattern=CASE_ID_PATTERN)]
ClaimIdPath = Annotated[str, Path(pattern=CLAIM_ID_PATTERN)]
TicketIdPath = Annotated[str, Path(pattern=TICKET_ID_PATTERN)]


def _repos(request: Request) -> Repositories:
    return request.app.state.repos  # type: ignore[no-any-return]


@router.get("/customers")
def search_customers(
    request: Request,
    actor: AgentActor,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: int = 10,
) -> list[CustomerMatch]:
    del actor
    return _repos(request).customers.search(q, limit=limit)


@router.get("/customers/{customer_id}")
def get_customer(
    request: Request, customer_id: CustomerIdPath, actor: AgentActor
) -> CustomerProfile:
    del actor
    profile = _repos(request).customers.profile(customer_id)
    if profile is None:
        raise NotFound("customer_not_found", f"No customer matches identifier {customer_id}.")
    return profile


@router.get("/customers/{customer_id}/interactions")
def list_interactions(
    request: Request,
    customer_id: CustomerIdPath,
    actor: AgentActor,
    limit: int = 20,
    since: str | None = None,
) -> list[InteractionSummary]:
    del actor
    repos = _repos(request)
    if not repos.customers.exists(customer_id):
        raise NotFound("customer_not_found", f"No customer matches identifier {customer_id}.")
    return repos.interactions.list_for_customer(customer_id, limit=limit, since=since)


@router.get("/customers/{customer_id}/cases")
def list_cases(
    request: Request,
    customer_id: CustomerIdPath,
    actor: AgentActor,
    status: str | None = None,
) -> list[SupportCase]:
    del actor
    repos = _repos(request)
    if not repos.customers.exists(customer_id):
        raise NotFound("customer_not_found", f"No customer matches identifier {customer_id}.")
    return repos.cases.list_for_customer(customer_id, status=status)


@router.get("/customers/{customer_id}/claims")
def list_claims(
    request: Request,
    customer_id: CustomerIdPath,
    actor: AgentActor,
    status: str | None = None,
) -> list[Claim]:
    del actor
    repos = _repos(request)
    if not repos.customers.exists(customer_id):
        raise NotFound("customer_not_found", f"No customer matches identifier {customer_id}.")
    return repos.claims.list_for_customer(customer_id, status=status)


@router.get("/cases/{case_id}")
def get_case(request: Request, case_id: CaseIdPath, actor: AgentActor) -> CaseDetail:
    del actor
    detail = _repos(request).cases.detail(case_id)
    if detail is None:
        raise NotFound("case_not_found", f"No case matches identifier {case_id}.")
    return detail


@router.get("/claims/{claim_id}")
def get_claim(request: Request, claim_id: ClaimIdPath, actor: AgentActor) -> Claim:
    del actor
    claim = _repos(request).claims.get(claim_id)
    if claim is None:
        raise NotFound("claim_not_found", f"No claim matches identifier {claim_id}.")
    return claim


@router.get("/tickets/{ticket_id}")
def get_ticket(request: Request, ticket_id: TicketIdPath, actor: AgentActor) -> TicketDetail:
    del actor
    detail = _repos(request).tickets.detail(ticket_id)
    if detail is None:
        raise NotFound("ticket_not_found", f"No ticket matches identifier {ticket_id}.")
    return detail
