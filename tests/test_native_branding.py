"""Focused contract tests for native OM Automate entry points."""

from pathlib import Path
import subprocess

from PIL import Image, ImageChops

import launcher
from src.branding import get_brand_config


ROOT = Path(__file__).resolve().parents[1]
NATIVE_SURFACES = (
    "launcher.py",
    "setup.py",
    "launch-windows.ps1",
    "start-macos.sh",
    "build-windows-portable.ps1",
    "build-macos-app.sh",
    "Odysseus.spec",
    "install-service.sh",
    "odysseus-ui.service",
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_launcher_uses_central_brand_and_generated_icon():
    brand = get_brand_config()
    assert launcher.BRAND == brand
    assert launcher.PRODUCT_NAME == brand.product_name
    assert launcher.LAUNCHER_LABEL == brand.native_labels["launcher"]
    assert launcher._brand_icon_path() == ROOT / "static" / "brand" / "om-icon-192.png"

    tray_image = launcher.create_tray_image()
    with Image.open(launcher._brand_icon_path()) as source:
        expected = source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    assert tray_image.mode == "RGBA"
    assert tray_image.size == (64, 64)
    assert ImageChops.difference(tray_image, expected).getbbox() is None


def test_native_surfaces_do_not_show_retired_product_or_persona():
    prohibited = ("Odysseus", "Ithaca", "Odyssey", "Homer", "Penelope", "Telemachus", "⛵")
    for path in NATIVE_SURFACES:
        text = _read(path)
        for term in prohibited:
            assert term not in text, f"{path} still exposes retired branding: {term}"


def test_native_entry_points_read_the_central_brand_contract():
    assert "get_brand_config" in _read("launcher.py")
    assert "get_brand_config" in _read("setup.py")
    assert "om_automate.product_name" in _read("launch-windows.ps1")
    assert "om_automate.product_name" in _read("start-macos.sh")
    assert "om_automate.native_labels.application" in _read("build-windows-portable.ps1")
    assert "om_automate.native_labels.application" in _read("build-macos-app.sh")
    assert "manifest['om_automate']['native_labels']['application']" in _read("Odysseus.spec")
    assert "Description=OM Automate" in _read("odysseus-ui.service")


def test_native_dependency_installs_use_the_exact_core_profile():
    for path in ("setup.py", "launch-windows.ps1", "start-macos.sh", "build-windows-portable.ps1", "build-macos-app.sh"):
        text = _read(path)
        assert "requirements-om.lock" in text
        assert "pip install -r requirements.txt" not in text
    assert 'chromadb==1.5.9' in _read("start-macos.sh")
    assert 'pyinstaller==6.21.0' in _read("build-windows-portable.ps1")
    assert 'pystray==0.19.5' in _read("build-windows-portable.ps1")


def test_native_shell_entry_points_parse():
    result = subprocess.run(
        ["bash", "-n", "start-macos.sh", "build-macos-app.sh", "install-service.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
