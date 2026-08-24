#!/usr/bin/env python3
"""Generate deterministic raster/native icons from the canonical brand tokens."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "static" / "brand"
COMPAT_ICON_DIR = ROOT / "static" / "icons"
MANIFEST = ROOT / "static" / "manifest.json"


def _render(size: int, *, maskable: bool = False) -> Image.Image:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tokens = manifest["om_automate"]["theme"]
    scale = 4
    canvas_size = size * scale
    image = Image.new("RGBA", (canvas_size, canvas_size), tokens["background"])
    draw = ImageDraw.Draw(image)

    def point(value: float) -> int:
        return round(value * canvas_size)

    if not maskable:
        pad = point(0.03)
        draw.rounded_rectangle(
            (pad, pad, canvas_size - pad, canvas_size - pad),
            radius=point(0.23),
            fill=tokens["background"],
        )

    inset = 0.235 if maskable else 0.205
    ring_box = (point(inset), point(inset), point(1 - inset), point(1 - inset))
    draw.arc(ring_box, 38, 326, fill=tokens["accent"], width=max(2, point(0.082)))
    draw.line(
        [
            (point(0.30), point(0.66)),
            (point(0.30), point(0.36)),
            (point(0.49), point(0.55)),
            (point(0.68), point(0.36)),
            (point(0.68), point(0.66)),
        ],
        fill=tokens["signal"],
        width=max(2, point(0.067)),
        joint="curve",
    )
    radius = point(0.045)
    cx, cy = point(0.75), point(0.245)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=tokens["signal"])
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    COMPAT_ICON_DIR.mkdir(parents=True, exist_ok=True)
    icon_192 = _render(192)
    icon_512 = _render(512)
    icon_maskable = _render(512, maskable=True)
    icon_192.save(BRAND_DIR / "om-icon-192.png", optimize=True)
    icon_512.save(BRAND_DIR / "om-icon-512.png", optimize=True)
    icon_maskable.save(BRAND_DIR / "om-icon-maskable-512.png", optimize=True)
    # Preserve old public asset paths for installed PWAs/bookmarks while
    # replacing their visible pixels. New manifests use the canonical paths.
    icon_192.save(COMPAT_ICON_DIR / "icon-192.png", optimize=True)
    icon_512.save(COMPAT_ICON_DIR / "icon-512.png", optimize=True)
    icon_maskable.save(COMPAT_ICON_DIR / "icon-maskable-512.png", optimize=True)
    icon = _render(256)
    icon.save(ROOT / "static" / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
