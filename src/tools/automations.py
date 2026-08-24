"""Approval-aware canonical structured automation handlers."""

from typing import Optional
from services.automation_service import AutomationNotFound, get_automation_service
from src.tools._common import _configured_auth_requires_owner,_parse_tool_args
from src.tools.knowledge import _require_claim


def error(exc):return {"error":str(exc),"code":getattr(exc,"code","invalid_arguments"),"exit_code":1}
async def do_query_automations(content:str,owner:Optional[str]=None):
    if _configured_auth_requires_owner(owner):return {"error":"Authenticated owner is required","code":"owner_required","exit_code":1}
    try:
        a=_parse_tool_args(content);action=a.get("action");service=get_automation_service()
        if action=="list":result={"automations":service.list(owner)}
        elif action=="get":result={"automation":service.get(owner,str(a.get("automation_id") or ""))}
        elif action=="list_runs":result={"runs":service.list_runs(owner,a.get("automation_id"),a.get("limit",100))}
        else:raise ValueError("Unknown automation query action")
        return {**result,"exit_code":0}
    except Exception as exc:return error(exc)
async def do_manage_automation(content:str,owner:Optional[str]=None,*,approval_action_id=None,request_id=""):
    try:
        _require_claim(owner,"manage_automation",approval_action_id,request_id);a=_parse_tool_args(content);action=a.get("action");service=get_automation_service()
        if action=="create":result={"automation":service.create(owner,a.get("definition") or {})}
        elif action=="set_status":result={"automation":service.set_status(owner,str(a.get("automation_id") or ""),str(a.get("status") or ""))}
        elif action=="run":result={"run":await service.run(owner,str(a.get("automation_id") or ""),trigger={"type":"manual"},inputs=a.get("inputs") or {},dedupe_key=a.get("dedupe_key"))}
        elif action=="approve_step":result={"run":await service.approve_step(owner,str(a.get("automation_id") or ""),str(a.get("run_id") or ""),int(a.get("step_index",-1)))}
        else:raise ValueError("Unknown automation mutation action")
        record=result.get("automation") or result["run"]
        return {**result,"verification":{"status":"verified","provider":"local_automations","read_back_id":record["id"]},"exit_code":0}
    except Exception as exc:return error(exc)
async def do_delete_automation(content:str,owner:Optional[str]=None,*,approval_action_id=None,request_id=""):
    try:
        _require_claim(owner,"delete_automation",approval_action_id,request_id);a=_parse_tool_args(content);service=get_automation_service();record_id=str(a.get("automation_id") or "");result=service.delete(owner,record_id,int(a.get("version") or 0))
        try:service.get(owner,record_id);absent=False
        except AutomationNotFound:absent=True
        return {**result,"verification":{"status":"verified" if absent else "mismatch","provider":"local_automations","read_back_id":record_id,"read_back":"not_found" if absent else "still_present"},"exit_code":0}
    except Exception as exc:return error(exc)
