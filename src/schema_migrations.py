"""Small versioned migration runner for OM Automate's isolated domain databases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
import os
from pathlib import Path
import threading
from typing import Callable, Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine


_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def _engine_lock_key(engine: Engine) -> str:
    if engine.url.get_backend_name() == "sqlite":
        database = str(engine.url.database or ":memory:")
        if database == ":memory:":
            return ":memory:"
        return str(Path(database).expanduser().resolve())
    return str(engine.url.render_as_string(hide_password=True))


@contextmanager
def _migration_lock(engine: Engine):
    """Serialize migration discovery and application across threads/processes."""
    key = _engine_lock_key(engine)
    with _LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(key, threading.RLock())
    with process_lock:
        handle = None
        if engine.url.get_backend_name() == "sqlite" and key != ":memory:":
            lock_path = Path(f"{key}.om-migrate.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(lock_path, "a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except Exception:
                handle.close()
                raise
        try:
            yield
        finally:
            if handle is not None:
                try:
                    if os.name == "nt":
                        import msvcrt
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[Engine], None]


def run_migrations(engine: Engine, namespace: str, migrations: Iterable[Migration]) -> list[int]:
    """Run missing migrations in order and record each only after success."""
    with _migration_lock(engine):
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS om_schema_migrations ("
                "namespace VARCHAR(100) NOT NULL, version INTEGER NOT NULL, "
                "name VARCHAR(255) NOT NULL, applied_at VARCHAR(40) NOT NULL, "
                "PRIMARY KEY(namespace, version))"
            ))
            applied = {
                int(row[0]) for row in connection.execute(
                    text("SELECT version FROM om_schema_migrations WHERE namespace=:namespace"),
                    {"namespace": namespace},
                )
            }
        completed: list[int] = []
        previous = 0
        for migration in sorted(migrations, key=lambda item: item.version):
            if migration.version <= previous:
                raise RuntimeError(f"Migration versions for {namespace} must be strictly increasing")
            previous = migration.version
            if migration.version in applied:
                continue
            migration.upgrade(engine)
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO om_schema_migrations(namespace, version, name, applied_at) VALUES (:namespace, :version, :name, :applied_at)"),
                    {"namespace": namespace, "version": migration.version, "name": migration.name,
                     "applied_at": datetime.now(timezone.utc).isoformat()},
                )
            completed.append(migration.version)
            applied.add(migration.version)
        return completed
