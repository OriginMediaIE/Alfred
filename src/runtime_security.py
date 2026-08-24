"""Owner-only defaults for the local PrivateOS runtime store."""

from __future__ import annotations

import os
from pathlib import Path


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def apply_private_umask() -> None:
    """Ensure newly created runtime files are private on POSIX hosts."""

    if os.name != "nt":
        os.umask(0o077)


def _chmod(path: Path, mode: int) -> bool:
    if os.name == "nt" or path.is_symlink() or not path.exists():
        return False
    try:
        path.chmod(mode)
        return True
    except OSError:
        return False


def private_runtime_paths(
    data_dir: str | Path,
    env_path: str | Path | None = None,
) -> tuple[list[Path], list[Path]]:
    """Return runtime directories and files that must remain owner-only.

    This deliberately avoids recursively changing model caches and executable
    tools. Top-level databases/configuration plus dedicated secret stores carry
    the principal's sensitive state and are safe to normalize on every start.
    """

    root = Path(data_dir).expanduser()
    directories = [root, root / "logs", root / "mcp_oauth", root / "ssh"]
    files: list[Path] = []
    if root.exists():
        for candidate in root.iterdir():
            if not candidate.is_file() or candidate.is_symlink():
                continue
            name = candidate.name
            if (
                name.startswith(".app_key")
                or name.endswith(
                    (".db", ".db-shm", ".db-wal", ".json", ".jsonl", ".lock")
                )
            ):
                files.append(candidate)
    for secret_dir in (root / "mcp_oauth", root / "ssh"):
        if secret_dir.is_dir():
            files.extend(
                path
                for path in secret_dir.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
            directories.extend(
                path
                for path in secret_dir.rglob("*")
                if path.is_dir() and not path.is_symlink()
            )
    if env_path is not None:
        files.append(Path(env_path).expanduser())
    return directories, files


def secure_runtime_storage(
    data_dir: str | Path,
    env_path: str | Path | None = None,
) -> dict[str, int]:
    """Create core runtime directories and normalize private POSIX modes."""

    apply_private_umask()
    root = Path(data_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    (root / "logs").mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    directories, files = private_runtime_paths(root, env_path)
    return {
        "directories": sum(
            _chmod(path, PRIVATE_DIRECTORY_MODE) for path in set(directories)
        ),
        "files": sum(_chmod(path, PRIVATE_FILE_MODE) for path in set(files)),
    }


def audit_private_runtime_paths(
    data_dir: str | Path,
    env_path: str | Path | None = None,
) -> list[str]:
    """Return non-sensitive issue codes for runtime paths with broad modes."""

    if os.name == "nt":
        return []
    directories, files = private_runtime_paths(data_dir, env_path)
    issues: list[str] = []
    for path in set(directories):
        if path.exists() and (path.stat().st_mode & 0o077):
            issues.append("directory_permissions")
    for path in set(files):
        if path.exists() and (path.stat().st_mode & 0o077):
            issues.append("file_permissions")
    return sorted(set(issues))


__all__ = [
    "PRIVATE_DIRECTORY_MODE",
    "PRIVATE_FILE_MODE",
    "apply_private_umask",
    "audit_private_runtime_paths",
    "private_runtime_paths",
    "secure_runtime_storage",
]
