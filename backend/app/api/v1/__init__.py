"""Version 1 of the HTTP contract — docs/06 §3.1.

The version is in the path because ALB path routing is already the dispatch mechanism,
so a v2 costs a listener rule rather than a redesign.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import customers, threads

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(threads.router)
api_router.include_router(customers.router)

__all__ = ["api_router"]
