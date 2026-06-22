"""
Visual Python - Installer / Launcher / Updater wizard
=====================================================

This is the small program you give to your users. They run it once; it:
  1. asks which computer they're on (Windows / Mac / Chromebook),
  2. downloads the right app build from your GitHub repo,
  3. installs it locally with a double-click launcher for their OS,
  4. can re-check GitHub any time to pull updates you push out.

It needs only Python's standard library (tkinter + urllib), so it runs the
same on all three platforms.

---------------------------------------------------------------------------
HOW YOU (the developer) PUBLISH AND PUSH UPDATES
---------------------------------------------------------------------------
1. Create a public GitHub repo, e.g. github.com/<you>/visual-python.
2. Put `visual_python.py` in it.
3. Add a `version.json` next to it (see make_template_manifest() below):

   {
     "version": "1.0.0",
     "notes": "First release!",
     "assets": {
       "windows":    "https://raw.githubusercontent.com/<you>/visual-python/main/visual_python.py",
       "mac":        "https://raw.githubusercontent.com/<you>/visual-python/main/visual_python.py",
       "chromebook": "https://raw.githubusercontent.com/<you>/visual-python/main/visual_python.py"
     }
   }

4. Fill in GITHUB_USER / GITHUB_REPO below and ship THIS file to users.
5. To push an update: edit visual_python.py, bump "version" in version.json,
   commit + push. Every user's "Check for updates" now sees the new version.
   (Later you can point "windows" at a real .exe, "mac" at an .app, etc. -
    the launcher just downloads whatever URL each OS points to.)

SECURITY NOTE: the launcher downloads and runs code from the URLs in your
version.json. Keep the repo under your control and use https only - anyone who
can change those files can run code on every user's machine. Optionally add a
"sha256" map to version.json and the launcher will verify each download.
"""

import os
import sys
import json
import hashlib
import platform
import subprocess
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

# ===========================================================================
# CONFIG - edit these two lines, then ship this file.
# ===========================================================================
GITHUB_USER = "ConPlusPlus"
GITHUB_REPO = "visual-python"
GITHUB_BRANCH = "main"

MANIFEST_URL = (f"https://raw.githubusercontent.com/{GITHUB_USER}/"
                f"{GITHUB_REPO}/{GITHUB_BRANCH}/version.json")
APP_FILENAME = "visual_python.py"
OS_KEYS = ["windows", "mac", "chromebook"]
OS_LABELS = {"windows": "Windows", "mac": "Mac", "chromebook": "Chromebook"}

COL_BG = "#1e1f26"
COL_PANEL = "#2d2f3a"
COL_TEXT = "#e6e6e6"
COL_ACCENT = "#4ea1ff"


# ===========================================================================
# Pure logic (no GUI) - kept separate so it can be tested headlessly
# ===========================================================================
def detect_os():
    """Best guess at the user's platform key."""
    s = platform.system()
    if s == "Windows":
        return "windows"
    if s == "Darwin":
        return "mac"
    return "chromebook"     # Linux / ChromeOS Crostini


def install_dir(os_key=None):
    """Where the app gets installed for this user."""
    home = Path.home()
    os_key = os_key or detect_os()
    if os_key == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", home))
    elif os_key == "mac":
        base = home / "Library" / "Application Support"
    else:
        base = home / ".local" / "share"
    base = base if base.exists() else home
    return base / "VisualPython"


def fetch_bytes(url, timeout=20):
    """Download a URL and return its bytes. (Patched out in tests.)"""
    req = urllib.request.Request(url, headers={"User-Agent": "VisualPython-Launcher"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_manifest(fetch=fetch_bytes):
    return json.loads(fetch(MANIFEST_URL).decode("utf-8"))


def choose_asset(manifest, os_key):
    assets = manifest.get("assets", {})
    return assets.get(os_key) or assets.get("all")


def parse_version(text):
    parts = []
    for chunk in str(text).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def installed_info(dest):
    f = Path(dest) / "installed.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def launcher_script(os_key, dest):
    """(filename, contents, make_executable) for the OS double-click launcher."""
    app = Path(dest) / APP_FILENAME
    if os_key == "windows":
        return ("Launch Visual Python.bat",
                f'@echo off\r\npython "{app}"\r\nif errorlevel 1 pause\r\n',
                False)
    if os_key == "mac":
        return ("Launch Visual Python.command",
                f'#!/bin/bash\ncd "$(dirname "$0")"\npython3 "{APP_FILENAME}"\n',
                True)
    return ("launch.sh",
            f'#!/bin/bash\ncd "$(dirname "$0")"\npython3 "{APP_FILENAME}"\n',
            True)


def install(os_key, dest=None, fetch=fetch_bytes):
    """Download the app for os_key into dest. Returns the installed version."""
    dest = Path(dest) if dest else install_dir(os_key)
    manifest = get_manifest(fetch)
    url = choose_asset(manifest, os_key)
    if not url:
        raise ValueError(f"version.json has no download for '{os_key}'.")
    data = fetch(url)
    expected = manifest.get("sha256", {}).get(os_key)
    if expected:
        actual = hashlib.sha256(data).hexdigest()
        if actual.lower() != expected.lower():
            raise ValueError("Download failed a security check (hash mismatch).")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / APP_FILENAME).write_bytes(data)
    fname, contents, make_exec = launcher_script(os_key, dest)
    path = dest / fname
    path.write_text(contents, encoding="utf-8")
    if make_exec:
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
    info = {"version": manifest.get("version", "0.0.0"), "os": os_key,
            "notes": manifest.get("notes", "")}
    (dest / "installed.json").write_text(json.dumps(info, indent=2),
                                         encoding="utf-8")
    return info["version"]


def check_update(dest, fetch=fetch_bytes):
    """Returns (has_update, remote_version, notes)."""
    local = installed_info(dest).get("version", "0.0.0")
    manifest = get_manifest(fetch)
    remote = manifest.get("version", "0.0.0")
    return is_newer(remote, local), remote, manifest.get("notes", "")


def make_template_manifest():
    raw = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{APP_FILENAME}"
    return {
        "version": "1.0.0",
        "notes": "First release!",
        "assets": {k: raw for k in OS_KEYS},
    }


# ===========================================================================
# GUI wizard
# ===========================================================================
class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Visual Python - Setup")
        self.geometry("560x420")
        self.configure(bg=COL_BG)
        self.resizable(False, False)

        self.os_key = tk.StringVar(value=detect_os())
        self.dest = install_dir(self.os_key.get())

        self.body = tk.Frame(self, bg=COL_BG)
        self.body.pack(fill="both", expand=True, padx=24, pady=20)
        self.show_welcome()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _title(self, text):
        tk.Label(self.body, text=text, bg=COL_BG, fg=COL_TEXT,
                 font=("Helvetica", 16, "bold")).pack(anchor="w")

    def _btn(self, parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd,
                         bg=(COL_ACCENT if primary else COL_PANEL),
                         fg=("#0b1020" if primary else COL_TEXT),
                         activebackground="#6fb4ff", relief="flat",
                         padx=18, pady=8, font=("Helvetica", 11, "bold"))

    # ---- step 1: welcome + OS choice ----
    def show_welcome(self):
        self._clear()
        self._title("Welcome to Visual Python")
        tk.Label(self.body,
                 text="Build Python programs by connecting blocks.\n"
                      "First, which computer are you using?",
                 bg=COL_BG, fg="#b9c0d4", font=("Helvetica", 11),
                 justify="left").pack(anchor="w", pady=(8, 16))
        for key in OS_KEYS:
            tk.Radiobutton(self.body, text=OS_LABELS[key], value=key,
                           variable=self.os_key, command=self._os_changed,
                           bg=COL_BG, fg=COL_TEXT, selectcolor=COL_PANEL,
                           activebackground=COL_BG, activeforeground="#fff",
                           font=("Helvetica", 12)).pack(anchor="w", pady=2)
        if detect_os() == self.os_key.get():
            tk.Label(self.body, text=f"(detected: {OS_LABELS[detect_os()]})",
                     bg=COL_BG, fg="#5b6075",
                     font=("Helvetica", 9)).pack(anchor="w", pady=(6, 0))
        nav = tk.Frame(self.body, bg=COL_BG)
        nav.pack(side="bottom", fill="x", pady=(20, 0))
        self._btn(nav, "Next  ›", self.show_install, primary=True).pack(side="right")

    def _os_changed(self):
        self.dest = install_dir(self.os_key.get())

    # ---- step 2: review + install ----
    def show_install(self):
        self._clear()
        self._title("Install")
        os_key = self.os_key.get()
        tk.Label(self.body,
                 text=f"Computer:  {OS_LABELS[os_key]}\n"
                      f"Install to:  {self.dest}",
                 bg=COL_BG, fg="#b9c0d4", font=("Helvetica", 11),
                 justify="left").pack(anchor="w", pady=(8, 6))

        tips = {
            "windows": "Needs Python from python.org (it includes Tkinter).",
            "mac": "Needs Python from python.org (avoid the built-in one).",
            "chromebook": "Turn on Linux (Crostini), then:\n"
                          "    sudo apt install python3 python3-tk",
        }
        tk.Label(self.body, text="Before running the app:\n  " + tips[os_key],
                 bg=COL_BG, fg="#8a90a6", font=("Helvetica", 10),
                 justify="left").pack(anchor="w", pady=(0, 12))

        self.status = tk.Label(self.body, text="", bg=COL_BG, fg=COL_ACCENT,
                               font=("Helvetica", 10), justify="left",
                               wraplength=500)
        self.status.pack(anchor="w")

        nav = tk.Frame(self.body, bg=COL_BG)
        nav.pack(side="bottom", fill="x", pady=(20, 0))
        self._btn(nav, "‹  Back", self.show_welcome).pack(side="left")
        self._btn(nav, "Download & Install", self._do_install,
                  primary=True).pack(side="right")

    def _do_install(self):
        self.status.config(text="Downloading from GitHub…", fg=COL_ACCENT)
        self.update_idletasks()
        try:
            version = install(self.os_key.get(), self.dest)
        except Exception as e:
            self.status.config(
                text=f"Couldn't install: {e}\n\nCheck your internet "
                     "connection, or that the developer has published "
                     "version.json on GitHub.", fg="#ff6b6b")
            return
        self.show_done(version)

    # ---- step 3: done + launch + updates ----
    def show_done(self, version):
        self._clear()
        self._title("All set!")
        tk.Label(self.body,
                 text=f"Visual Python {version} is installed in:\n{self.dest}",
                 bg=COL_BG, fg="#b9c0d4", font=("Helvetica", 11),
                 justify="left").pack(anchor="w", pady=(8, 4))
        fname, _, _ = launcher_script(self.os_key.get(), self.dest)
        tk.Label(self.body,
                 text=f"Double-click  “{fname}”  in that folder to start it,\n"
                      "or use the Launch button below.",
                 bg=COL_BG, fg="#8a90a6", font=("Helvetica", 10),
                 justify="left").pack(anchor="w", pady=(0, 14))

        self.status2 = tk.Label(self.body, text="", bg=COL_BG, fg=COL_ACCENT,
                                font=("Helvetica", 10), wraplength=500,
                                justify="left")
        self.status2.pack(anchor="w")

        row = tk.Frame(self.body, bg=COL_BG)
        row.pack(side="bottom", fill="x", pady=(20, 0))
        self._btn(row, "Launch Visual Python", self._launch,
                  primary=True).pack(side="left")
        self._btn(row, "Check for updates", self._check_updates).pack(side="left",
                                                                      padx=8)

    def _launch(self):
        app = self.dest / APP_FILENAME
        if not app.exists():
            messagebox.showerror("Not found", f"{app} is missing - reinstall.")
            return
        try:
            subprocess.Popen([sys.executable, str(app)])
        except Exception as e:
            messagebox.showerror("Could not launch", str(e))

    def _check_updates(self):
        self.status2.config(text="Checking GitHub…", fg=COL_ACCENT)
        self.update_idletasks()
        try:
            has_update, remote, notes = check_update(self.dest)
        except Exception as e:
            self.status2.config(text=f"Couldn't check: {e}", fg="#ff6b6b")
            return
        if not has_update:
            self.status2.config(text="You're on the latest version. ✓",
                                fg="#7dd77d")
            return
        if messagebox.askyesno("Update available",
                               f"Version {remote} is available.\n\n{notes}\n\n"
                               "Download it now?"):
            try:
                version = install(self.os_key.get(), self.dest)
                self.status2.config(text=f"Updated to {version}. ✓", fg="#7dd77d")
            except Exception as e:
                self.status2.config(text=f"Update failed: {e}", fg="#ff6b6b")


if __name__ == "__main__":
    Wizard().mainloop()
