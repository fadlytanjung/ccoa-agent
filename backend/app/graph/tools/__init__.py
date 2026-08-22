"""The tool surface — the only bridge between the graph and the data (docs/03 §3.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.graph.tools.descriptions import assert_in_step, describe
from app.graph.tools.mutations import MUTATIONS, REQUIRED_GROUP
from app.graph.tools.result import ToolCallRecord, ToolResult
from app.graph.tools.toolbox import (
    ALL_TOOL_NAMES,
    MUTATING_TOOL_NAMES,
    READ_TOOL_NAMES,
    ToolBox,
    ToolContext,
    authorise,
    dispatch,
)

__all__ = [
    "ALL_TOOL_NAMES",
    "MUTATING_TOOL_NAMES",
    "MUTATIONS",
    "READ_TOOL_NAMES",
    "REQUIRED_GROUP",
    "ToolBox",
    "ToolCallRecord",
    "ToolContext",
    "ToolResult",
    "assert_in_step",
    "authorise",
    "bind_tools_for",
    "describe",
    "dispatch",
]


# --- Argument schemas -------------------------------------------------------
# Field descriptions stay short by design. The long-form guidance the model reasons
# over lives in app/agents/tools.yaml; these name the argument and nothing more.
class SearchCustomerArgs(BaseModel):
    query: str = Field(description="Name, email address, or customer ID.")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum matches to return.")


class CustomerIdArgs(BaseModel):
    customer_id: str = Field(description="Customer ID, e.g. CUST-000042.")


class ListInteractionsArgs(BaseModel):
    customer_id: str = Field(description="Customer ID, e.g. CUST-000042.")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum interactions to return.")
    since: str | None = Field(default=None, description="ISO-8601 date; only later contacts.")
    channel: str | None = Field(default=None, description="voice, chat, email, or callback.")


class SearchInteractionsArgs(BaseModel):
    customer_id: str = Field(description="Customer ID, e.g. CUST-000042.")
    query: str = Field(description="What to look for in past contacts.")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum hits to return.")


class ListClaimsArgs(BaseModel):
    customer_id: str = Field(description="Customer ID, e.g. CUST-000042.")
    status: str | None = Field(default=None, description="Claim status to filter by.")
    limit: int = Field(default=20, ge=1, le=50, description="Maximum claims to return.")


class ClaimIdArgs(BaseModel):
    claim_id: str = Field(description="Claim ID, e.g. CLM-00000117.")


class ListCasesArgs(BaseModel):
    customer_id: str = Field(description="Customer ID, e.g. CUST-000042.")
    status: str | None = Field(default=None, description="Case status, or 'open' for any active.")
    limit: int = Field(default=20, ge=1, le=50, description="Maximum cases to return.")


class CaseIdArgs(BaseModel):
    case_id: str = Field(description="Case ID, e.g. CASE-000008.")


class SearchKbArgs(BaseModel):
    query: str = Field(description="Failure code or search terms.")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum articles to return.")


class ReadReferenceArgs(BaseModel):
    """No `skill` argument, deliberately.

    The graph already knows which specialist is running, and asking the model to name
    its own skill meant it sometimes named the wrong one — the call then failed and
    burned an iteration of the investigation budget. It was also a needless widening of
    the boundary: a tool that takes a skill name is a tool that can be pointed at
    another skill's files.
    """

    path: str = Field(description="Reference path listed in your instructions.")


ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "search_customer": SearchCustomerArgs,
    "get_customer": CustomerIdArgs,
    "list_interactions": ListInteractionsArgs,
    "search_interactions": SearchInteractionsArgs,
    "list_claims": ListClaimsArgs,
    "get_claim": ClaimIdArgs,
    "list_cases": ListCasesArgs,
    "get_case": CaseIdArgs,
    "search_kb": SearchKbArgs,
    "read_reference": ReadReferenceArgs,
}


def bind_tools_for(
    box: ToolBox, names: tuple[str, ...], *, skill: str | None = None
) -> list[StructuredTool]:
    """Build LangChain tools for the names a skill declared.

    Ordered deterministically so the prompt prefix stays byte-identical across turns
    and remains cacheable (docs/05 §3.10).

    ``skill`` is bound into ``read_reference`` rather than asked of the model — see
    :class:`ReadReferenceArgs`.
    """

    def _runner(tool_name: str) -> Any:
        """Build the callable for one tool.

        A factory rather than a closure with a default argument: LangChain inspects the
        function's signature to decide what to pass, so a bookkeeping parameter like
        `_name=...` becomes part of the tool's contract and the real arguments stop
        lining up. That produced a `read_reference` that failed every call with a
        missing-argument error.
        """

        def run(**kwargs: Any) -> dict[str, Any]:
            if tool_name == "read_reference" and skill is not None:
                kwargs["skill"] = skill
            return dispatch(box, tool_name, kwargs).as_payload()

        return run

    tools: list[StructuredTool] = []
    for name in sorted(set(names) & READ_TOOL_NAMES):
        tools.append(
            StructuredTool.from_function(
                func=_runner(name),
                name=name,
                description=describe(name),
                args_schema=ARG_SCHEMAS[name],
            )
        )
    return tools
