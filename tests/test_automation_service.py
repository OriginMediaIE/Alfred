"""Safety and history coverage for structured automations."""

import asyncio, hashlib, hmac, json
from datetime import datetime, timedelta, timezone
import httpx, pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from routes.automation_routes import setup_automation_routes, setup_automation_webhook_routes
import services.automation_service as automation_module
from services.automation_service import AutomationLoopDetected, AutomationRateLimited, AutomationService, AutomationStateError, AutomationValidationError
from services.automation_worker import AutomationWorker
from src.auth_helpers import require_user
from src.automation_models import AutomationBase, AutomationDeadLetter, ensure_automation_schema


class Runner:
    def __init__(self, fail=False): self.calls=[];self.fail=fail
    async def __call__(self, owner, action, context):
        self.calls.append((owner,action,context))
        if self.fail: raise RuntimeError("provider unavailable")
        if action["type"]=="draft_email" and not context.get("approved"): return {"approval_required":True,"requested_action":"draft_email"}
        return {"ok":True,"action":action["type"]}


@pytest.fixture
def env():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);ensure_automation_schema(engine);factory=sessionmaker(bind=engine,autocommit=False,autoflush=False);runner=Runner();service=AutomationService(session_factory=factory,action_runner=runner,approval_proposer=lambda owner,automation_id,run_id,step_index:{"id":f"approval-{run_id}-{step_index}"})
    try:yield service,runner,factory
    finally:AutomationBase.metadata.drop_all(engine);engine.dispose()


def definition(**overrides):
    value={"name":"Meeting preparation","trigger":{"type":"meeting_completed"},"conditions":[{"field":"meeting.attendee_count","operator":"greater_than","value":0}],"actions":[{"type":"query_knowledge","parameters":{"query":"agenda"}},{"type":"notify_user","parameters":{"message":"Brief ready"}}],"limits":{"max_steps":10,"max_runs_per_hour":20,"disable_after_failures":3}}
    value.update(overrides);return value


def test_definition_validation_rejects_unknown_triggers_actions_and_fields(env):
    service,_,_=env
    with pytest.raises(AutomationValidationError): service.create("alice",{**definition(),"surprise":True})
    with pytest.raises(AutomationValidationError): service.create("alice",definition(trigger={"type":"arbitrary"}))
    with pytest.raises(AutomationValidationError): service.create("alice",definition(actions=[{"type":"shell","parameters":{}}]))


@pytest.mark.asyncio
async def test_manual_run_history_conditions_idempotency_and_approval_state(env):
    service,runner,_=env;automation=service.create("alice",definition())
    skipped=await service.run("alice",automation["id"],inputs={"meeting":{"attendee_count":0}},dedupe_key="zero")
    assert skipped["status"]=="skipped" and runner.calls==[]
    success=await service.run("alice",automation["id"],inputs={"meeting":{"attendee_count":2}},dedupe_key="event-1")
    replay=await service.run("alice",automation["id"],inputs={"meeting":{"attendee_count":2}},dedupe_key="event-1")
    assert success["id"]==replay["id"] and success["status"]=="success"
    assert len(success["steps"])==2 and success["correlation_id"]
    assert success["duration_ms"]>=0 and success["tool_calls"][0]["action"]=="query_knowledge"
    approval_def=service.create("alice",definition(name="Draft follow-up",conditions=[],actions=[{"type":"draft_email","parameters":{"to":"person@example.test","subject":"Follow-up","body":"Draft body"}}]))
    approval=await service.run("alice",approval_def["id"],dedupe_key="draft-1")
    assert approval["status"]=="approval_required" and approval["approval_state"]=="pending"
    assert approval["steps"][0]["status"]=="approval_required"
    assert approval["steps"][0]["result"]["approval_id"].startswith("approval-")


@pytest.mark.asyncio
async def test_exact_approved_step_resumes_remaining_actions(env):
    service,runner,_=env
    automation=service.create("alice",definition(name="Approved sequence",conditions=[],actions=[{"type":"draft_email","parameters":{"to":"person@example.test","subject":"Review","body":"Draft body"}},{"type":"notify_user","parameters":{"message":"Ready"}}]))
    waiting=await service.run("alice",automation["id"],dedupe_key="approval-sequence")
    completed=await service.approve_step("alice",automation["id"],waiting["id"],0)
    assert completed["status"]=="success" and completed["approval_state"]=="approved"
    assert [step["status"] for step in completed["steps"]]==["success","success"]
    with pytest.raises(AutomationStateError):
        await service.approve_step("alice",automation["id"],waiting["id"],0)


@pytest.mark.asyncio
async def test_event_dedupe_loop_depth_rate_limit_and_worker_stop(env):
    service,_,_=env;automation=service.create("alice",definition(conditions=[]))
    first=await service.emit("alice","meeting_completed",{"meeting":{}},dedupe_key="meeting-1")
    duplicate=await service.emit("alice","meeting_completed",{"meeting":{}},dedupe_key="meeting-1")
    assert len(first["runs"])==1 and duplicate=={"duplicate":True,"runs":[]}
    with pytest.raises(AutomationLoopDetected): await service.run("alice",automation["id"],depth=1,lineage=(automation["id"],))
    limited=service.create("alice",definition(name="limited",conditions=[],limits={"max_runs_per_hour":1},trigger={"type":"manual"}))
    await service.run("alice",limited["id"],dedupe_key="one")
    with pytest.raises(AutomationRateLimited): await service.run("alice",limited["id"],dedupe_key="two")
    worker=AutomationWorker(service,poll_seconds=.01);task=asyncio.create_task(worker.run());await asyncio.sleep(.02);worker.stop();await asyncio.wait_for(task,1)


@pytest.mark.asyncio
async def test_proactive_task_due_uses_stable_reminder_dedupe(env,monkeypatch):
    service,runner,_=env
    automation=service.create("alice",definition(name="Due task",conditions=[],trigger={"type":"task_due"},actions=[{"type":"notify_user","parameters":{"message":"Due"}}]))
    fake_work=type("FakeWork",(),{"pending_reminders":lambda self,owner,due_before,limit:[{"id":"reminder-1","message":"Due"}]})()
    monkeypatch.setattr(automation_module,"get_work_service",lambda:fake_work)
    first=await service.run_proactive(now=datetime.now(timezone.utc));second=await service.run_proactive(now=datetime.now(timezone.utc))
    assert len(first)==1 and len(second)==1 and first[0]["id"]==second[0]["id"]
    assert first[0]["trigger"]["type"]=="task_due" and runner.calls


def test_calendar_trigger_requires_bounded_notice_window(env):
    service,_,_=env
    with pytest.raises(AutomationValidationError,match="minutes_before"):
        service.create("alice",definition(conditions=[],trigger={"type":"calendar_before_event"}))


@pytest.mark.asyncio
async def test_repeated_failure_disables_and_dead_letters(env):
    _service,_runner,factory=env;clock={"now":datetime.now(timezone.utc)};failing=AutomationService(session_factory=factory,action_runner=Runner(fail=True),clock=lambda:clock["now"],approval_proposer=lambda *args:{"id":"unused"});automation=failing.create("alice",definition(conditions=[],trigger={"type":"manual"},limits={"disable_after_failures":3,"cooldown_seconds":0,"max_runs_per_hour":20}))
    for index in range(3):
        run=await failing.run("alice",automation["id"],dedupe_key=f"failure-{index}");assert run["status"]=="failed";clock["now"]+=timedelta(seconds=1)
    assert failing.get("alice",automation["id"])["status"]=="disabled_failure"
    db=factory()
    try:assert db.query(AutomationDeadLetter).count()==1
    finally:db.close()


@pytest.mark.asyncio
async def test_failed_run_can_be_retried_and_records_recovery_link(env):
    service,runner,_=env
    automation=service.create("alice",definition(conditions=[],trigger={"type":"manual"}))
    runner.fail=True
    failed=await service.run("alice",automation["id"],dedupe_key="first-failure")
    assert failed["status"]=="failed"
    runner.fail=False
    retried=await service.retry_run("alice",failed["id"])
    assert retried["status"]=="success" and retried["id"]!=failed["id"]
    original=service.get_run("alice",failed["id"])
    assert original["retry_status"]=="retried"
    assert retried["trigger"]["retry_of"]==failed["id"]
    with pytest.raises(AutomationStateError):
        await service.retry_run("alice",retried["id"])


def test_approval_waiting_run_can_be_cancelled_owner_safely(env):
    service,_,_=env
    automation=service.create("alice",definition(conditions=[]))
    db=service.sessions()
    try:
        from src.automation_models import AutomationRun
        waiting=AutomationRun(id="waiting",automation_id=automation["id"],owner="alice",trigger_json="{}",inputs_json="{}",correlation_id="c",idempotency_key="waiting-key",status="approval_required",approval_state="pending")
        db.add(waiting);db.commit()
    finally:db.close()
    cancelled=service.cancel_run("alice","waiting")
    assert cancelled["status"]=="cancelled" and cancelled["approval_state"]=="cancelled"
    with pytest.raises(Exception): service.cancel_run("bob","waiting")


@pytest.mark.asyncio
async def test_routes_are_strict_owner_scoped_and_show_run_history(env):
    service,_,_=env;owner={"value":"alice"};app=FastAPI();app.dependency_overrides[require_user]=lambda:owner["value"];app.include_router(setup_automation_routes(service))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        created=await client.post("/api/automations",json=definition(conditions=[],trigger={"type":"manual"}));assert created.status_code==200;automation=created.json()
        run=await client.post(f"/api/automations/{automation['id']}/run",json={"inputs":{},"dedupe_key":"route-run"});assert run.status_code==200
        assert (await client.get("/api/automations/runs")).json()["runs"][0]["id"]==run.json()["id"]
        owner["value"]="bob";assert (await client.get(f"/api/automations/{automation['id']}")).status_code==404
        strict=await client.post("/api/automations",json={**definition(),"unexpected":True});assert strict.status_code==422


@pytest.mark.asyncio
async def test_routine_templates_install_once_survive_service_restart_and_measure_time(env):
    service, _runner, factory = env
    templates = service.routine_templates("alice")
    assert {item["key"] for item in templates} >= {"renewals", "follow-ups", "weekly-review", "inbox-triage", "backup-reminder", "meeting-follow-up"}
    installed = service.install_routine("alice", "weekly-review")
    assert installed["routine_key"] == "weekly-review" and installed["next_run_at"]
    assert service.install_routine("alice", "weekly-review")["already_installed"] is True
    restarted = AutomationService(session_factory=factory, action_runner=_runner, approval_proposer=lambda *args: {"id": "approval-test"})
    assert restarted.get("alice", installed["id"])["routine_key"] == "weekly-review"
    completed = await restarted.run("alice", installed["id"], dedupe_key="routine-proof")
    assert completed["status"] == "success"
    metrics = restarted.operating_metrics("alice", since=datetime.now(timezone.utc) - timedelta(days=1))
    assert metrics["successful_routine_runs"] == 1
    assert metrics["attention_returned_minutes"] == 20


@pytest.mark.asyncio
async def test_routine_template_routes_are_static_and_owner_scoped(env):
    service, _, _ = env; owner = {"value": "alice"}; app = FastAPI(); app.dependency_overrides[require_user] = lambda: owner["value"]; app.include_router(setup_automation_routes(service))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/automations/templates")
        assert listed.status_code == 200 and len(listed.json()["templates"]) == 6
        installed = await client.post("/api/automations/templates/renewals", json={"confirm": True})
        assert installed.status_code == 200 and installed.json()["routine_key"] == "renewals"
        assert (await client.get("/api/automations/metrics")).status_code == 200
        owner["value"] = "bob"
        assert all(item["installed_automation_id"] is None for item in (await client.get("/api/automations/templates")).json()["templates"])


@pytest.mark.asyncio
async def test_webhook_signature_timestamp_size_and_replay_protection(env, monkeypatch):
    service,_,_=env;monkeypatch.setattr(automation_module,"encrypt",lambda value:value);monkeypatch.setattr(automation_module,"decrypt",lambda value:value)
    created=service.create("alice",definition(name="Inbound",conditions=[],trigger={"type":"webhook"}))
    secret=created["webhook_secret"];assert created["webhook_secret_shown_once"] is True
    assert "webhook_secret" not in service.get("alice",created["id"])
    app=FastAPI();app.include_router(setup_automation_webhook_routes(service));body=json.dumps({"meeting":{"id":"m1"}},separators=(",",":")).encode();stamp=str(int(datetime.now(timezone.utc).timestamp()));signature="sha256="+hmac.new(secret.encode(),stamp.encode()+b"."+body,hashlib.sha256).hexdigest();headers={"X-OM-Timestamp":stamp,"X-OM-Signature":signature,"X-OM-Delivery-ID":"delivery-1","Content-Type":"application/json"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        accepted=await client.post(f"/api/automation-hooks/{created['id']}",content=body,headers=headers);assert accepted.status_code==200 and len(accepted.json()["runs"])==1
        replay=await client.post(f"/api/automation-hooks/{created['id']}",content=body,headers=headers);assert replay.status_code==200 and replay.json()["duplicate"] is True
        bad=await client.post(f"/api/automation-hooks/{created['id']}",content=body,headers={**headers,"X-OM-Signature":"sha256=bad"});assert bad.status_code==422
        old=str(int((datetime.now(timezone.utc)-timedelta(minutes=6)).timestamp()));old_sig="sha256="+hmac.new(secret.encode(),old.encode()+b"."+body,hashlib.sha256).hexdigest();stale=await client.post(f"/api/automation-hooks/{created['id']}",content=body,headers={**headers,"X-OM-Timestamp":old,"X-OM-Signature":old_sig,"X-OM-Delivery-ID":"delivery-2"});assert stale.status_code==422
