"""Meeting action-item bridge into the canonical personal-work domain."""

from services.meeting_integrations import WorkMeetingTaskSink
from tests.work_support import make_work_service


def test_reviewed_meeting_action_is_durable_idempotent_and_source_linked():
    work, _factory, bind = make_work_service()
    sink = WorkMeetingTaskSink(work)
    source = {
        "type": "meeting",
        "meeting_id": "meeting-1",
        "claim_id": "claim-1",
        "transcript_revision": 3,
        "evidence": [
            {
                "segment_id": "segment-2",
                "start_ms": 2200,
                "end_ms": 3100,
                "speaker_label": "SPEAKER_01",
                "excerpt": "Action: prepare the release notes.",
            }
        ],
        "trust_classification": "untrusted_user_content",
    }
    try:
        first = sink.create_task_from_meeting(
            owner="alice",
            title="Prepare the release notes",
            description="Approved meeting action",
            source=source,
            idempotency_key="meeting-claim:claim-1",
        )
        second = sink.create_task_from_meeting(
            owner="alice",
            title="Prepare the release notes",
            description="Approved meeting action",
            source=source,
            idempotency_key="meeting-claim:claim-1",
        )

        assert second["id"] == first["id"]
        assert first["source"]["type"] == "meeting"
        assert first["source"]["id"] == "meeting-claim:claim-1"
        assert first["created_by"] == "integration"
        assert first["references"][0]["external_id"] == "meeting-1"
        assert first["references"][0]["metadata"]["evidence"][0]["start_ms"] == 2200
        receipts = work.list_receipts("alice", entity_id=first["id"])
        assert len(receipts) == 1
        assert receipts[0]["actor_kind"] == "integration"
    finally:
        bind.dispose()


def test_meeting_task_source_is_owner_scoped():
    work, _factory, bind = make_work_service()
    sink = WorkMeetingTaskSink(work)
    try:
        source = {"meeting_id": "meeting-shared", "claim_id": "claim-shared"}
        alice = sink.create_task_from_meeting(
            owner="alice",
            title="Alice action",
            description="",
            source=source,
            idempotency_key="meeting-claim:shared",
        )
        bob = sink.create_task_from_meeting(
            owner="bob",
            title="Bob action",
            description="",
            source=source,
            idempotency_key="meeting-claim:shared",
        )
        assert alice["id"] != bob["id"]
        assert work.find_task_by_source(
            "mallory", source_type="meeting", source_id="meeting-claim:shared"
        ) is None
    finally:
        bind.dispose()
