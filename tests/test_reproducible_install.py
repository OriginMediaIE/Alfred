import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _installer_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    root = tmp_path / "install"
    root.mkdir()
    shutil.copy2(ROOT / "install-om-automate.sh", root / "install-om-automate.sh")
    (root / ".env.example").write_text("APP_BIND=127.0.0.1\nAPP_PORT=7000\nAPP_DATA_DIR=./data\n", encoding="utf-8")
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "docker").mkdir()
    (root / "docker" / "gpu.nvidia.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "docker" / "gpu.amd.yml").write_text("services: {}\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "docker.log"
    _write_executable(fake_bin / "docker", f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{log}'\nexit 0\n")
    _write_executable(fake_bin / "curl", "#!/bin/sh\nexit 0\n")
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    return root, env, log


def test_posix_installer_check_is_network_free_and_idempotent(tmp_path):
    root, env, log = _installer_fixture(tmp_path)
    command = ["bash", str(root / "install-om-automate.sh"), "--check"]

    first = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr
    assert "No images were pulled, built, or started" in first.stdout
    env_file = root / ".env"
    original = env_file.read_bytes()

    second = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, check=False)
    assert second.returncode == 0, second.stderr
    assert env_file.read_bytes() == original
    docker_calls = log.read_text(encoding="utf-8")
    assert "compose version" in docker_calls
    assert "compose -f docker-compose.yml config --quiet" in docker_calls
    assert not re.search(r"\b(?:pull|build|up)\b", docker_calls)


def test_posix_installer_full_flow_is_readiness_gated_and_rerunnable(tmp_path):
    root, env, log = _installer_fixture(tmp_path)
    command = ["bash", str(root / "install-om-automate.sh"), "--no-open"]

    first = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr
    original = (root / ".env").read_bytes()
    assert "and ready at" in first.stdout
    assert not (root / ".om-automate-install.lock").exists()

    second = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, check=False)
    assert second.returncode == 0, second.stderr
    assert (root / ".env").read_bytes() == original
    docker_calls = log.read_text(encoding="utf-8")
    assert docker_calls.count("compose -f docker-compose.yml up -d --build") == 2
    assert docker_calls.count("compose -f docker-compose.yml ps") == 2


def test_posix_installer_can_pull_published_images_without_building(tmp_path):
    root, env, log = _installer_fixture(tmp_path)
    result = subprocess.run(
        ["bash", str(root / "install-om-automate.sh"), "--pull", "--no-open"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    docker_calls = log.read_text(encoding="utf-8")
    assert "compose -f docker-compose.yml pull" in docker_calls
    assert "compose -f docker-compose.yml up -d --no-build" in docker_calls
    assert "up -d --build" not in docker_calls


def test_posix_installer_readiness_timeout_fails_and_releases_lock(tmp_path):
    root, env, log = _installer_fixture(tmp_path)
    fake_curl = Path(env["PATH"].split(os.pathsep, 1)[0]) / "curl"
    _write_executable(fake_curl, "#!/bin/sh\nexit 22\n")

    result = subprocess.run(
        ["bash", str(root / "install-om-automate.sh"), "--no-open", "--timeout", "1"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Readiness verification timed out" in result.stderr
    assert "compose -f docker-compose.yml ps" in log.read_text(encoding="utf-8")
    assert not (root / ".om-automate-install.lock").exists()


def test_posix_installer_rejects_broad_data_path(tmp_path):
    root, env, _ = _installer_fixture(tmp_path)
    (root / ".env").write_text("APP_BIND=127.0.0.1\nAPP_DATA_DIR=.\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(root / "install-om-automate.sh"), "--check"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "broad data path" in result.stderr


def test_posix_installer_accepts_quoted_safe_env_values(tmp_path):
    root, env, _ = _installer_fixture(tmp_path)
    (root / ".env").write_text(
        "APP_BIND=\"127.0.0.1\"\nAPP_PORT='7000'\nAPP_DATA_DIR=\"./safe data\"\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(root / "install-om-automate.sh"), "--check"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (root / "safe data").is_dir()


def test_posix_installer_fails_closed_for_insecure_network_binding(tmp_path):
    root, env, _ = _installer_fixture(tmp_path)
    env["OM_AUTOMATE_ALLOW_NETWORK"] = "1"
    (root / ".env").write_text(
        "APP_BIND=0.0.0.0\nAUTH_ENABLED=true\nLOCALHOST_BYPASS=false\n"
        "SECURE_COOKIES=false\nALLOWED_ORIGINS=https://om.example\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(root / "install-om-automate.sh"), "--check"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SECURE_COOKIES=true" in result.stderr


def test_posix_installer_accepts_explicit_hardened_network_binding(tmp_path):
    root, env, _ = _installer_fixture(tmp_path)
    env["OM_AUTOMATE_ALLOW_NETWORK"] = "1"
    (root / ".env").write_text(
        "APP_BIND=0.0.0.0\nAUTH_ENABLED=true\nLOCALHOST_BYPASS=false\n"
        "SECURE_COOKIES=true\nALLOWED_ORIGINS=https://om.example\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(root / "install-om-automate.sh"), "--check"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_and_service_images_are_exactly_versioned():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    lock = (ROOT / "requirements-om.lock").read_text(encoding="utf-8")

    assert dockerfile.count("python:3.14.7-slim-bookworm") == 2
    assert "requirements-om.lock" in dockerfile
    assert "chromadb/chroma:1.5.9" in compose
    assert "binwiederhier/ntfy:v2.26.0" in compose
    assert "ghcr.io/originmediaie/alfred:1.0.2" in compose
    assert ":latest" not in compose
    active = [line for line in lock.splitlines() if line and not line.startswith("#")]
    assert active and all("==" in line for line in active)


def test_installers_expose_preflight_and_health_contracts():
    shell = (ROOT / "install-om-automate.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "install-om-automate.ps1").read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(ROOT / "install-om-automate.sh")], check=True)
    for source in (shell, powershell):
        assert "api/health" in source
        assert "api/ready" in source
        assert "APP_DATA_DIR" in source
        assert "APP_BIND" in source
        assert "config --quiet" in source
        assert "No images were pulled, built, or started" in source
    assert "#Requires -Version 5.1" in powershell
    assert "??" not in powershell
    assert "SECURE_COOKIES=true" in shell and "SECURE_COOKIES=true" in powershell
    assert (ROOT / "install-om-automate.command").stat().st_mode & stat.S_IXUSR
    assert (ROOT / "install-om-automate.cmd").is_file()


def test_beginner_installers_and_launchers_are_release_ready():
    mac_installer = ROOT / "installers" / "Install-Alfred.command"
    windows_installer = ROOT / "installers" / "Install-Alfred.ps1"
    workflow = ROOT / ".github" / "workflows" / "release-installers.yml"

    subprocess.run(["bash", "-n", str(mac_installer)], check=True)
    subprocess.run(["bash", "-n", str(ROOT / "Start-Alfred.command")], check=True)
    subprocess.run(["bash", "-n", str(ROOT / "scripts" / "install-docker-launcher.sh")], check=True)
    assert mac_installer.stat().st_mode & stat.S_IXUSR
    assert "OriginMediaIE/Alfred" in mac_installer.read_text(encoding="utf-8")
    assert "--exclude='.env'" in mac_installer.read_text(encoding="utf-8")
    assert "--pull" in mac_installer.read_text(encoding="utf-8")
    assert "OriginMediaIE/Alfred" in windows_installer.read_text(encoding="utf-8")
    assert "/XF .env" in windows_installer.read_text(encoding="utf-8")
    assert "-Pull" in windows_installer.read_text(encoding="utf-8")
    assert "Alfred-macOS-Installer.zip" in workflow.read_text(encoding="utf-8")
    assert "Alfred-Windows-Installer.zip" in workflow.read_text(encoding="utf-8")
    assert "gh release create" in workflow.read_text(encoding="utf-8")
    assert "tags:" in workflow.read_text(encoding="utf-8")
    assert (ROOT / "Start-Alfred.ps1").is_file()
