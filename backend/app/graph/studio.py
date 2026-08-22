"""Module-level graph export for the LangGraph Agent Server — docs/14 §3.5.

``langgraph.json`` points here rather than at ``builder.py`` for one reason:
constructing the graph opens a database, loads the skill registry, and validates the
tool surface. Doing that at import time is exactly right for ``langgraph dev`` and
exactly wrong for ``import app.graph.builder`` in a unit test. Keeping the side effect
in its own module means ``builder`` stays importable for free.

No checkpointer is passed. The Agent Server supplies its own persistence, and
``build_graph`` defaulting to ``None`` makes this export correct by construction.
"""

from __future__ import annotations

from app.config import get_settings
from app.graph.builder import build_graph

get_settings()  # fail fast on misconfiguration, before Studio shows an empty graph

graph = build_graph()
