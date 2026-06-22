"""
Visual Python - bootstrap launcher  (build this into VisualPython.exe)
======================================================================

This is the program you turn into a single executable with PyInstaller and
hand to users. The .exe bundles Python, so users need NOTHING installed.

What it does every time it runs:
  1. Makes sure the latest app code (visual_python.py) is on the machine,
     seeding a bundled copy on first run so it works even offline.
  2. Checks your GitHub version.json and, if a newer app version is published,
     downloads it (tiny + instant - no rebuild, no reinstall).
  3. Runs the app *inside this same bundled Python* (so updates are just the
     small .py file changing - the .exe itself rarely needs rebuilding).

Build it (on Windows, with Python installed):
    pip install pyinstaller
    python build_exe.py
  -> produces dist/VisualPython.exe

To push an app update to everyone: edit visual_python.py, bump "version" in
version.json, commit + push to GitHub. Every user gets it next launch.

Other platforms: build the same way ON that OS (PyInstaller makes a Mac .app
on a Mac, a Linux binary on Linux). The app code is identical everywhere.

SECURITY: the launcher downloads + runs code from your GitHub repo, so keep it
under your control and https-only. version.json may carry a "sha256" map which
this launcher verifies before applying an update.
"""

import os
import sys
import json
import shutil
import hashlib
import platform
import urllib.request
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

# Imported so PyInstaller bundles everything the app code needs at runtime
# (the app is shipped as bundled data, so its imports aren't auto-detected).
import io            # noqa: F401
import contextlib    # noqa: F401
import traceback     # noqa: F401
import random        # noqa: F401
from tkinter import ttk, simpledialog, filedialog  # noqa: F401

# ===========================================================================
# CONFIG
# ===========================================================================
GITHUB_USER = "ConPlusPlus"
GITHUB_REPO = "visual-python"
GITHUB_BRANCH = "main"
MANIFEST_URL = (f"https://raw.githubusercontent.com/{GITHUB_USER}/"
                f"{GITHUB_REPO}/{GITHUB_BRANCH}/version.json")
APP_FILENAME = "visual_python.py"
# Version of THIS native launcher/exe. Bump it (and version.json's
# "launcher_version") only when you rebuild and publish new executables.
LAUNCHER_VERSION = "1.0.0"


# ===========================================================================
# Paths
# ===========================================================================
def os_key():
    s = platform.system()
    return {"Windows": "windows", "Darwin": "mac"}.get(s, "chromebook")


def app_dir():
    """Per-user folder where the live app code + version marker live."""
    home = Path.home()
    s = platform.system()
    if s == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", home))
    elif s == "Darwin":
        base = home / "Library" / "Application Support"
    else:
        base = home / ".local" / "share"
    d = (base if base.exists() else home) / "VisualPython"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_seed_path():
    """Where the app copy baked into the exe (or sitting next to this script)
    can be found."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, APP_FILENAME)


def local_app_path(appdir=None):
    return Path(appdir or app_dir()) / APP_FILENAME


def installed_path(appdir=None):
    return Path(appdir or app_dir()) / "installed.json"


# ===========================================================================
# Version helpers
# ===========================================================================
def parse_version(text):
    parts = []
    for chunk in str(text).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def read_installed(appdir=None):
    p = installed_path(appdir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_installed(version, appdir=None):
    installed_path(appdir).write_text(
        json.dumps({"version": version}, indent=2), encoding="utf-8")


def _version_in_code(text):
    for line in text.splitlines():
        if line.strip().startswith("__version__"):
            try:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                return None
    return None


# ===========================================================================
# Seed + update
# ===========================================================================
def seed_if_missing(appdir=None, seed_src=None):
    """On first run, copy the bundled app code into appdir."""
    dst = local_app_path(appdir)
    if dst.exists():
        return False
    src = seed_src or bundled_seed_path()
    if not os.path.exists(src):
        return False
    shutil.copyfile(src, dst)
    write_installed(_version_in_code(dst.read_text(encoding="utf-8")) or "0.0.0",
                    appdir)
    return True


def fetch_bytes(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "VisualPython-Launcher"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_manifest(fetch=fetch_bytes):
    return json.loads(fetch(MANIFEST_URL).decode("utf-8"))


def _asset_url(manifest):
    assets = manifest.get("assets", {})
    return assets.get(os_key()) or assets.get("all") or manifest.get("app")


def update_if_available(appdir=None, fetch=fetch_bytes):
    """Check GitHub and update the local app code if newer.

    Returns (updated: bool, version: str, message: str). Network problems are
    swallowed so the app still launches from the local copy when offline.
    """
    local = read_installed(appdir).get("version", "0.0.0")
    try:
        manifest = get_manifest(fetch)
    except Exception:
        return (False, local, "offline")
    remote = manifest.get("version", "0.0.0")
    if not is_newer(remote, local) and local_app_path(appdir).exists():
        return (False, local, "up-to-date")
    url = _asset_url(manifest)
    if not url:
        return (False, local, "no asset for this OS")
    try:
        data = fetch(url)
    except Exception:
        return (False, local, "download failed")
    expected = manifest.get("sha256", {}).get(os_key())
    if expected and hashlib.sha256(data).hexdigest().lower() != expected.lower():
        return (False, local, "failed security check")
    local_app_path(appdir).write_bytes(data)
    write_installed(remote, appdir)
    return (True, remote, manifest.get("notes", ""))


# ===========================================================================
# Native-installer (exe/app/binary) update notice, per OS
# ===========================================================================
def launcher_update_for(manifest):
    """If the manifest advertises a newer native installer for this OS, return
    (version, download_url); otherwise (None, None)."""
    remote = manifest.get("launcher_version")
    if remote and is_newer(remote, LAUNCHER_VERSION):
        return remote, manifest.get("launchers", {}).get(os_key())
    return None, None


def check_launcher_update(fetch=fetch_bytes):
    """Tell the user (and open the download page) if a newer installer exists
    for their OS. The app code itself updates silently, so this is rare."""
    try:
        manifest = get_manifest(fetch)
    except Exception:
        return
    version, url = launcher_update_for(manifest)
    if not version or not url:
        return
    r = tk.Tk()
    r.withdraw()
    try:
        if messagebox.askyesno(
                "New installer available",
                f"A newer Visual Python installer ({version}) is available "
                "for your computer.\n\nThe app itself already updates "
                "automatically — you only need this occasionally.\n\n"
                "Open the download page now?"):
            webbrowser.open(url)
    finally:
        r.destroy()


# ===========================================================================
# Run the app inside this interpreter (the bundled Python)
# ===========================================================================
def run_app(appdir=None):
    path = local_app_path(appdir)
    if not path.exists():
        raise FileNotFoundError(path)
    code = path.read_text(encoding="utf-8")
    g = {"__name__": "__main__", "__file__": str(path)}
    exec(compile(code, str(path), "exec"), g)


# ===========================================================================
# Tiny splash so the exe doesn't look frozen while it checks for updates
# ===========================================================================
def _splash():
    root = tk.Tk()
    root.overrideredirect(True)
    root.configure(bg="#1e1f26")
    w, h = 360, 110
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    tk.Label(root, text="Visual Python", bg="#1e1f26", fg="#e6e6e6",
             font=("Helvetica", 16, "bold")).pack(pady=(24, 4))
    msg = tk.Label(root, text="Starting…", bg="#1e1f26", fg="#4ea1ff",
                   font=("Helvetica", 10))
    msg.pack()
    root.update()
    return root, msg


def main():
    try:
        seed_if_missing()
    except Exception:
        pass

    root, msg = None, None
    try:
        root, msg = _splash()
        msg.config(text="Checking for updates…")
        root.update()
        updated, version, note = update_if_available()
        if updated:
            msg.config(text=f"Updated to {version} ✓")
            root.update()
    except Exception:
        pass
    finally:
        if root is not None:
            root.destroy()

    try:
        check_launcher_update()
    except Exception:
        pass

    try:
        run_app()
    except Exception as e:
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(
                "Visual Python",
                "Couldn't start the app.\n\n"
                "If this is the first run, connect to the internet once so it "
                f"can download the app.\n\nDetails: {e}")
            r.destroy()
        except Exception:
            print("Could not start Visual Python:", e)


if __name__ == "__main__":
    main()
