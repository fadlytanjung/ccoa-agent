"""The authenticated caller — docs/06 §3.3, docs/10 §3.

An ``Actor`` is a property of the *request*, not of the conversation. It travels in
``config["configurable"]`` and never enters ``AgentState``, so a resumed run cannot
inherit a stale identity (docs/05 §3.2).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.enums import Group


class Actor(BaseModel):
    """Identity and authority of whoever made the current request."""

    model_config = {"frozen": True}

    sub: str
    email: str = ""
    groups: tuple[str, ...] = Field(default_factory=tuple)

    def has_group(self, group: Group | str) -> bool:
        return str(group) in self.groups

    def require(self, group: Group | str) -> None:
        """Raise :class:`Forbidden` unless the actor holds ``group``."""
        if not self.has_group(group):
            from app.domain.errors import Forbidden

            raise Forbidden(
                "insufficient_group",
                f"This action requires membership of the {str(group)!r} group.",
            )

    def to_config(self) -> dict[str, str | list[str]]:
        """Shape placed under ``config['configurable']['actor']``."""
        return {"sub": self.sub, "email": self.email, "groups": list(self.groups)}

    @classmethod
    def from_config(cls, raw: dict[str, object] | None) -> Actor | None:
        if not raw:
            return None
        groups = raw.get("groups") or []
        return cls(
            sub=str(raw.get("sub", "")),
            email=str(raw.get("email", "")),
            groups=tuple(str(g) for g in groups) if isinstance(groups, list | tuple) else (),
        )


#: The fixed identity used when ``AUTH_MODE=dev`` (docs/14 §3.7). It holds *both*
#: groups so both authorisation paths are reachable without a Cognito pool.
DEV_ACTOR = Actor(
    sub="local-dev-user",
    email="dev@localhost",
    groups=(Group.AGENT, Group.SUPERVISOR),
)
