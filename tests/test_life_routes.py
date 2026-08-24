from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.life_routes import setup_life_routes
from services.life_service import LifeService
from src.auth_helpers import require_user


def _client(tmp_path):
    app=FastAPI();service=LifeService(database_url=f"sqlite:///{tmp_path/'life-routes.db'}")
    app.dependency_overrides[require_user]=lambda:"alice";app.include_router(setup_life_routes(service));return TestClient(app)


def test_life_routes_create_list_update_delete(tmp_path):
    client=_client(tmp_path)
    created=client.post("/api/life",json={"kind":"relationship","record":{"name":"Morgan","user_approved":True}})
    assert created.status_code==200
    record=created.json()["record"]
    assert client.get("/api/life",params={"kind":"relationship"}).json()["records"][0]["id"]==record["id"]
    updated=client.put(f"/api/life/relationship/{record['id']}",json={"record":{"follow_up_status":"due"},"revision":record["revision"]})
    assert updated.json()["record"]["follow_up_status"]=="due"
    revision=updated.json()["record"]["revision"]
    deleted=client.request("DELETE",f"/api/life/relationship/{record['id']}",json={"revision":revision,"confirm":True})
    assert deleted.json()["ok"] is True


def test_life_routes_forbid_unknown_fields_and_unconfirmed_delete(tmp_path):
    client=_client(tmp_path)
    assert client.post("/api/life",json={"kind":"trip","record":{"title":"Paris"},"extra":True}).status_code==422
    record=client.post("/api/life",json={"kind":"trip","record":{"title":"Paris"}}).json()["record"]
    assert client.request("DELETE",f"/api/life/trip/{record['id']}",json={"revision":record["revision"],"confirm":False}).status_code==422
