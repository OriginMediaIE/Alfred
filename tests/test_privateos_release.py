from datetime import date, timedelta
import sqlite3

from services.release_service import ReleaseService


def test_release_preflight_and_fresh_install_rehearsal(tmp_path):
    (tmp_path/".app_key").write_text("private-instance-key",encoding="utf-8")
    (tmp_path/".app_key").chmod(0o600)
    with sqlite3.connect(tmp_path/"private.db") as connection:
        connection.execute("CREATE TABLE facts (value TEXT)")
        connection.execute("INSERT INTO facts VALUES ('kept')")
        connection.commit()
    service=ReleaseService(tmp_path)
    assert service.preflight("alice")["passed"] is True
    result=service.rehearse_restore()
    assert result["passed"] is True
    assert result["fresh_install_portable"] is True
    assert result["database_count"]==1


def test_soak_requires_seven_consecutive_real_dates(tmp_path):
    service=ReleaseService(tmp_path);start=date(2026,8,1)
    for offset in range(6):service.record_soak_day("alice",day=start+timedelta(days=offset))
    assert service.soak_status()["acceptance_met"] is False
    status=service.record_soak_day("alice",day=start+timedelta(days=6))
    assert status["acceptance_met"] is True
    assert status["longest_consecutive_days"]==7


def test_soak_duplicate_date_does_not_inflate_evidence(tmp_path):
    service=ReleaseService(tmp_path);observed=date(2026,8,1)
    service.record_soak_day("alice",day=observed)
    status=service.record_soak_day("alice",day=observed,note="second run")
    assert status["recorded_days"]==1
