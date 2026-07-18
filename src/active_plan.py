"""Request-local state for an approved plan currently being executed.

The browser owns the durable plan record.  A chat request sends that record's
identity and version with the approved checklist; this module keeps the
corresponding mutable state scoped to the request while tools execute.  Using a
``ContextVar`` prevents concurrent agent turns from updating one another's
plans while still allowing the tool dispatcher to remain context agnostic.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class ActivePlanState:
    """The current approved plan revision for one agent request."""

    session_id: str
    plan_id: str
    text: str
    version: int = 0

    def advance(self, text: str) -> dict:
        """Replace the checklist and return a compare-and-set update payload."""

        base_version = self.version
        self.text = text
        self.version = base_version + 1
        return {
            "plan": self.text,
            "session_id": self.session_id,
            "plan_id": self.plan_id,
            "base_version": base_version,
            "version": self.version,
        }


_ACTIVE_PLAN: ContextVar[Optional[ActivePlanState]] = ContextVar(
    "odysseus_active_plan",
    default=None,
)


def get_active_plan() -> Optional[ActivePlanState]:
    """Return the plan bound to the current tool task, if one exists."""

    return _ACTIVE_PLAN.get()


@contextmanager
def bind_active_plan(state: ActivePlanState) -> Iterator[ActivePlanState]:
    """Bind ``state`` for tool calls made inside this context."""

    token = _ACTIVE_PLAN.set(state)
    try:
        yield state
    finally:
        _ACTIVE_PLAN.reset(token)
