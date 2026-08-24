from sqlalchemy import create_engine, inspect, text

from src.automation_models import ensure_automation_schema
from src.knowledge_models import ensure_knowledge_schema
from src.meeting_models import ensure_meeting_schema
from src.life_models import ensure_life_schema
from src.schema_migrations import Migration, run_migrations
from src.schema_migrations import _engine_lock_key
from src.work_models import ensure_work_schema


def test_automation_upgrade_adds_webhook_secret_to_legacy_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-automations.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE automation_definitions ("
            "id VARCHAR(36) PRIMARY KEY, owner VARCHAR(255) NOT NULL, name VARCHAR(300) NOT NULL, "
            "definition_json TEXT NOT NULL, status VARCHAR(30) NOT NULL, version INTEGER NOT NULL, "
            "next_run_at DATETIME, last_run_at DATETIME, consecutive_failures INTEGER NOT NULL, "
            "cooldown_until DATETIME, run_count INTEGER NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
    assert ensure_automation_schema(engine) == [1, 2]
    assert "webhook_secret_enc" in {item["name"] for item in inspect(engine).get_columns("automation_definitions")}
    assert ensure_automation_schema(engine) == []


def test_domain_migrations_are_versioned_and_rerunnable(tmp_path):
    for name, ensure in (("knowledge", ensure_knowledge_schema), ("meetings", ensure_meeting_schema)):
        engine = create_engine(f"sqlite:///{tmp_path / (name + '.db')}")
        assert ensure(engine) == [1]
        assert ensure(engine) == []
        with engine.begin() as connection:
            versions = connection.execute(text("SELECT version FROM om_schema_migrations WHERE namespace=:name"), {"name": name}).scalars().all()
        assert versions == [1]


def test_personal_work_schema_uses_versioned_migration(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'work.db'}")
    assert ensure_work_schema(bind=engine)==[1]
    assert ensure_work_schema(bind=engine)==[]


def test_personal_life_schema_uses_versioned_migration(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'life.db'}")
    assert ensure_life_schema(engine)==[1]
    assert ensure_life_schema(engine)==[]


def test_concurrent_migration_callers_apply_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    engine=create_engine(
        f"sqlite:///{tmp_path/'concurrent.db'}",
        connect_args={"check_same_thread":False},
    )
    calls=[];calls_lock=threading.Lock()
    def upgrade(target):
        with calls_lock:calls.append(1)
        with target.begin() as connection:
            connection.execute(text("CREATE TABLE shared_value(id INTEGER PRIMARY KEY)"))
    def invoke():
        return run_migrations(engine,"concurrent",(Migration(1,"create_shared",upgrade),))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:invoke(),range(4)))
    assert calls==[1]
    assert sorted(results,key=len)==[[],[],[],[1]]


def test_in_memory_sqlite_never_creates_a_filesystem_lock():
    for url in ("sqlite://", "sqlite:///:memory:"):
        engine = create_engine(url)
        assert _engine_lock_key(engine) == ":memory:"
        assert run_migrations(
            engine,
            "memory",
            (Migration(1, "noop", lambda _engine: None),),
        ) == [1]
