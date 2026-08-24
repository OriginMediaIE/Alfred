"""Search-domain tool implementations.

Extracted from tool_implementations.py as part of slice 1 (#4082/#4071).
Holds the search_chats tool.
``src.tool_implementations`` re-exports these for backward compatibility.
"""
import logging
from typing import Dict

from src.tools._common import _configured_auth_requires_owner

logger = logging.getLogger(__name__)


async def do_search_chats(query: str, limit: int = 20, owner: str | None = None) -> Dict:
    """Search past session transcripts for the calling user's sessions only.

    Configured multi-user deployments require an authenticated owner.  Even
    with one, legacy/null-owner sessions are deliberately excluded so data
    created before ownership was introduced cannot become implicitly shared.
    Ownerless search remains available only when auth is explicitly disabled
    for single-user mode and is still restricted to null-owner rows.
    """
    if _configured_auth_requires_owner(owner):
        return {
            "error": "Authenticated owner is required to search chat history",
            "exit_code": 1,
        }

    try:
        from src.session_search import search_session_messages

        results = search_session_messages(
            query,
            limit=limit,
            owner=owner,
            restrict_owner=True,
            include_legacy_owner=False,
        )
        if not results:
            return {"results": f"No chats found matching \"{query}\"."}

        # Group by session to avoid duplicate links
        seen_sessions = {}
        for result in results:
            if result.session_id not in seen_sessions:
                seen_sessions[result.session_id] = result

        lines = [f"Found {len(seen_sessions)} session(s) matching \"{query}\":\n"]
        for sid, result in seen_sessions.items():
            lines.append(f"- [**{result.session_name}**](#session-{sid})")
            lines.append(f"  Open: [Open chat](#session-{sid})")
            lines.append(f"  Match ({result.role}): {result.content_snippet}")
            if result.context_before:
                before = result.context_before[-1]
                lines.append(f"  Before ({before['role']}): {before['content'][:180]}")
            if result.context_after:
                after = result.context_after[0]
                lines.append(f"  After ({after['role']}): {after['content'][:180]}")
            lines.append("")

        return {"results": "\n".join(lines)}
    except Exception as e:
        logger.error(f"search_chats failed: {e}")
        return {"error": str(e), "exit_code": 1}
