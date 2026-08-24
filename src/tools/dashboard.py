"""Read-only executive dashboard agent adapter."""

from typing import Optional
from services.executive_service import get_executive_service
from src.tools._common import _configured_auth_requires_owner, _parse_tool_args


async def do_query_dashboard(content: str, owner: Optional[str] = None):
    if _configured_auth_requires_owner(owner): return {"error": "Authenticated owner is required", "code": "owner_required", "exit_code": 1}
    try:
        args = _parse_tool_args(content)
        if not isinstance(args, dict): raise ValueError("Tool arguments must be an object")
        action = str(args.get("action") or "")
        if action == "today": result = await get_executive_service().today(owner, timezone_name=args.get("timezone"))
        elif action in {"morning", "evening", "weekly"}: result = await get_executive_service().briefing(owner, kind=action, timezone_name=args.get("timezone"))
        else: raise ValueError("Unknown dashboard action")
        return {"dashboard": result, "exit_code": 0}
    except Exception as exc: return {"error": str(exc), "code": "dashboard_unavailable", "exit_code": 1}
