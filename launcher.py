# launcher.py
"""Dedicated entrypoint for the standalone OM Automate launcher.

Handles:
- Immediate GUI splash screen creation using tkinter.
- Suppressing console stream crashes in windowed GUI mode via NullWriter.
- Spawning system tray icon via pystray and Pillow (lazy-loaded).
- Auto-opening default browser pointing to the running backend.
- Launching the FastAPI server (importing and running app.py).
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from src.branding import get_brand_config
from src.constants import STATIC_DIR


BRAND = get_brand_config()
PRODUCT_NAME = BRAND.product_name
LAUNCHER_LABEL = BRAND.native_labels["launcher"]


def _brand_icon_path() -> Path:
    """Resolve the validated public icon URL to its bundled filesystem path."""
    public_path = BRAND.assets.apple_touch_icon
    static_prefix = "/static/"
    if not public_path.startswith(static_prefix):
        raise ValueError("native icon must be served from /static/")
    return Path(STATIC_DIR) / public_path.removeprefix(static_prefix)


def create_tray_image(size: int = 64):
    """Load the central OM icon, with a small geometric fallback for recovery."""
    from PIL import Image, ImageDraw

    try:
        with Image.open(_brand_icon_path()) as source:
            return source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    except (FileNotFoundError, OSError):
        # Keep the launcher usable if a manually assembled portable bundle is
        # missing its icon. The fallback is still the OM signal mark, not the
        # retired legacy artwork.
        background = BRAND.theme["background"]
        accent = BRAND.theme["accent"]
        signal = BRAND.theme["signal"]
        image = Image.new("RGBA", (size, size), background)
        draw = ImageDraw.Draw(image)
        scale = size / 64
        width = max(2, round(6 * scale))
        draw.ellipse(
            tuple(round(value * scale) for value in (8, 8, 56, 56)),
            outline=accent,
            width=width,
        )
        mark_points = ((23, 43), (23, 25), (32, 36), (41, 25), (41, 43))
        draw.line(
            [(round(x * scale), round(y * scale)) for x, y in mark_points],
            fill=signal,
            width=max(2, round(5 * scale)),
            joint="curve",
        )
        draw.ellipse(
            tuple(round(value * scale) for value in (46, 13, 54, 21)),
            fill=signal,
        )
        return image

# Define a dummy NullWriter to suppress standard stream crashes (isatty etc.) in GUI mode
class NullWriter:
    def write(self, text):
        pass
    def flush(self):
        pass
    def isatty(self):
        return False

if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()


splash_root = None

# If running from a frozen PyInstaller bundle, launch the splash screen IMMEDIATELY
if getattr(sys, 'frozen', False):
    import tkinter as tk

    def show_splash_instantly():
        global splash_root
        try:
            splash_root = tk.Tk()
            splash_root.title(PRODUCT_NAME)
            splash_root.overrideredirect(True)
            splash_root.configure(bg=BRAND.theme["background"])

            # Accented borders
            splash_root.config(
                highlightbackground=BRAND.theme["accent"],
                highlightcolor=BRAND.theme["accent"],
                highlightthickness=1,
            )

            w, h = 390, 182
            ws = splash_root.winfo_screenwidth()
            hs = splash_root.winfo_screenheight()
            x = (ws - w) // 2
            y = (hs - h) // 2
            splash_root.geometry(f"{w}x{h}+{x}+{y}")

            header = tk.Frame(splash_root, bg=BRAND.theme["background"])
            header.pack(pady=(20, 3))
            try:
                from PIL import ImageTk

                photo = ImageTk.PhotoImage(create_tray_image(48))
                splash_root._om_brand_photo = photo
                tk.Label(
                    header,
                    image=photo,
                    bg=BRAND.theme["background"],
                    borderwidth=0,
                ).pack(side=tk.LEFT, padx=(0, 10))
            except Exception:
                tk.Label(
                    header,
                    text=BRAND.assistant_name,
                    font=("Segoe UI", 18, "bold"),
                    bg=BRAND.theme["background"],
                    fg=BRAND.theme["signal"],
                ).pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(
                header,
                text=PRODUCT_NAME,
                font=("Segoe UI", 21, "bold"),
                bg=BRAND.theme["background"],
                fg=BRAND.theme["foreground"],
            ).pack(side=tk.LEFT)
            tk.Label(
                splash_root,
                text=BRAND.positioning,
                font=("Segoe UI", 10),
                bg=BRAND.theme["background"],
                fg=BRAND.theme["accent"],
            ).pack(pady=2)
            tk.Label(
                splash_root,
                text="Launching private services…",
                font=("Segoe UI", 8, "italic"),
                bg=BRAND.theme["background"],
                fg=BRAND.theme["foreground"],
            ).pack(pady=(9, 0))

            splash_root.attributes("-topmost", True)
            splash_root.mainloop()
        except Exception:
            pass

    # Launch the GUI splash screen immediately on a background thread
    threading.Thread(target=show_splash_instantly, daemon=True).start()

def on_open_browser(icon, item, url):
    webbrowser.open(url)


def on_exit(icon, item):
    icon.stop()
    os._exit(0)


def setup_system_tray(url):
    try:
        import pystray
        icon_img = create_tray_image()
        menu = (
            pystray.MenuItem(LAUNCHER_LABEL, lambda icon, item: on_open_browser(icon, item, url), default=True),
            pystray.MenuItem(f"Quit {PRODUCT_NAME}", on_exit),
        )
        tray_icon = pystray.Icon(
            "om-automate",
            icon_img,
            PRODUCT_NAME,
            menu,
        )
        tray_icon.run()
    except Exception:
        pass


def open_browser(url):
    # Allow uvicorn and app lifecycles to complete warmups
    time.sleep(3.5)

    # Safely close the splash screen
    try:
        global splash_root
        if splash_root:
            splash_root.after(0, splash_root.destroy)
    except Exception:
        pass

    webbrowser.open(url)


if __name__ == "__main__":
    import uvicorn
    # Import the FastAPI app from app.py
    from app import app

    bind_host = os.getenv("APP_BIND", "127.0.0.1")
    bind_port = int(os.getenv("APP_PORT", "7000"))
    url = f"http://{bind_host}:{bind_port}"

    if getattr(sys, 'frozen', False):
        # Start browser manager thread
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()
        # Start system tray manager thread
        threading.Thread(target=setup_system_tray, args=(url,), daemon=True).start()

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
