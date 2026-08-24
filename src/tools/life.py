"""Canonical agent adapters for personal-life records."""
from datetime import datetime,timezone
from services.life_service import LifeNotFound,get_life_service
from src.action_ledger import ActionLedgerError,get_action_ledger
from src.life_tool_contract import QUERY_LIFE_ACTIONS,MANAGE_LIFE_ACTIONS,DELETE_LIFE_ACTIONS
from src.tools._common import _configured_auth_requires_owner,_parse_tool_args
def _error(exc):return {"error":str(exc),"code":getattr(exc,"code","invalid_arguments"),"exit_code":1}
def _claim(owner,tool,approval_action_id,request_id):
    if not approval_action_id or not request_id:raise ValueError("Personal-life mutation requires an approved action-ledger claim")
    try:action=get_action_ledger().get_action(approval_action_id,owner)
    except ActionLedgerError as exc:raise ValueError("Approval evidence unavailable") from exc
    expiry=datetime.fromisoformat(str(action.get("expires_at") or "").replace("Z","+00:00"));expiry=expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
    if action.get("tool_name")!=tool or action.get("status")!="executing" or not action.get("approval_consumed_at") or action.get("request_id")!=request_id or expiry<=datetime.now(timezone.utc):raise ValueError("Approval evidence is invalid or mismatched")
async def do_query_life(content,owner=None):
    if _configured_auth_requires_owner(owner):return _error(ValueError("Authenticated owner is required"))
    try:
        a=_parse_tool_args(content);action=a.get("action");kind=a.get("kind");service=get_life_service()
        if action not in QUERY_LIFE_ACTIONS:raise ValueError("Unknown personal-life query action")
        result={"record":service.get(owner,kind,a.get("record_id"))} if action=="get" else {"records":service.list(owner,kind,status=a.get("status"),trip_id=a.get("trip_id"),limit=a.get("limit",100))}
        return {**result,"exit_code":0}
    except Exception as exc:return _error(exc)
async def do_manage_life(content,owner=None,*,approval_action_id=None,request_id=""):
    try:
        _claim(owner,"manage_life",approval_action_id,request_id);a=_parse_tool_args(content);service=get_life_service();action=a.get("action");kind=a.get("kind")
        if action not in MANAGE_LIFE_ACTIONS:raise ValueError("Unknown personal-life mutation action")
        record=service.create(owner,kind,a.get("record") or {}) if action=="create" else service.update(owner,kind,a.get("record_id"),a.get("record") or {},a.get("revision"))
        observed=service.get(owner,kind,record["id"]);return {"record":record,"verification":{"status":"verified" if observed["revision"]==record["revision"] else "mismatch","provider":"local_personal_life","read_back_id":record["id"]},"exit_code":0}
    except Exception as exc:return _error(exc)
async def do_delete_life(content,owner=None,*,approval_action_id=None,request_id=""):
    try:
        _claim(owner,"delete_life",approval_action_id,request_id);a=_parse_tool_args(content)
        if a.get("action") not in DELETE_LIFE_ACTIONS:raise ValueError("Unknown personal-life delete action")
        service=get_life_service();result=service.delete(owner,a.get("kind"),a.get("record_id"),a.get("revision"))
        try:service.get(owner,a.get("kind"),a.get("record_id"));absent=False
        except LifeNotFound:absent=True
        return {**result,"verification":{"status":"verified" if absent else "mismatch","provider":"local_personal_life","read_back_id":a.get("record_id")},"exit_code":0}
    except Exception as exc:return _error(exc)
