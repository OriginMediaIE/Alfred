import pytest

from services.life_service import LifeConflict, LifeNotFound, LifeService, LifeValidationError


@pytest.fixture
def service(tmp_path):
    return LifeService(database_url=f"sqlite:///{tmp_path / 'life.db'}")


def test_relationship_profiles_require_approval_and_are_owner_scoped(service):
    with pytest.raises(LifeValidationError, match="explicit user approval"):
        service.create("alice", "relationship", {"name": "Morgan"})
    profile = service.create("alice", "relationship", {
        "name": "Morgan", "organization": "Example", "role": "Director",
        "contact_methods": [{"type": "email", "value": "m@example.test"}],
        "communication_style": "Concise email", "follow_up_status": "due",
        "user_approved": True,
    })
    assert service.get("alice", "relationship", profile["id"])["organization"] == "Example"
    with pytest.raises(LifeNotFound):
        service.get("bob", "relationship", profile["id"])


def test_financial_admin_is_opt_in_sensitive_and_revision_checked(service):
    with pytest.raises(LifeValidationError, match="explicit opt-in"):
        service.create("alice", "admin", {"title": "Electricity", "category": "bill"})
    record = service.create("alice", "admin", {
        "title": "Electricity", "category": "bill", "financial_opt_in": True,
        "sensitive": True, "details": {"provider": "Utility Co"},
    })
    updated = service.update("alice", "admin", record["id"], {"status": "paid"}, record["revision"])
    assert updated["revision"] == 2
    with pytest.raises(LifeConflict):
        service.update("alice", "admin", record["id"], {"status": "active"}, record["revision"])


def test_travel_framework_rejects_booking_and_supports_trip_items(service):
    trip = service.create("alice", "trip", {"title": "Dublin to Berlin", "destination": "Berlin", "destination_timezone": "Europe/Berlin"})
    flight = service.create("alice", "travel_item", {
        "trip_id": trip["id"], "item_type": "flight", "title": "Outbound flight",
        "details": {"flight_number": "OM123"},
    })
    assert service.list("alice", "travel_item", trip_id=trip["id"])[0]["id"] == flight["id"]
    with pytest.raises(LifeValidationError, match="Purchasing"):
        service.create("alice", "travel_item", {"trip_id": trip["id"], "item_type": "reservation", "title": "Buy hotel", "details": {"book": True}})
    with pytest.raises(LifeConflict, match="trip items"):
        service.delete("alice", "trip", trip["id"], trip["revision"])


def test_travel_items_require_an_owned_existing_trip(service):
    alice_trip = service.create("alice", "trip", {"title": "Alice trip"})
    with pytest.raises(LifeValidationError, match="requires trip_id"):
        service.create("alice", "travel_item", {"trip_id": "", "item_type": "flight", "title": "Orphan"})
    with pytest.raises(LifeValidationError, match="owner's trips"):
        service.create("bob", "travel_item", {"trip_id": alice_trip["id"], "item_type": "flight", "title": "Cross-owner"})
    item = service.create("alice", "travel_item", {"trip_id": alice_trip["id"], "item_type": "flight", "title": "Valid"})
    bob_trip = service.create("bob", "trip", {"title": "Bob trip"})
    with pytest.raises(LifeValidationError, match="owner's trips"):
        service.update("alice", "travel_item", item["id"], {"trip_id": bob_trip["id"]}, item["revision"])
