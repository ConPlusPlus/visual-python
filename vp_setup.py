"""
Visual Python - Setup wizard  (the OS-picker installer/updater)
===============================================================

A friendly GUI a user runs to GET Visual Python. They pick their computer
(Windows / Mac / Chromebook); it downloads the matching pre-built executable
from your GitHub Release, installs it, can re-check for newer executables, and
launches it.

This is a .py front-end (so it needs Python to run). The thing it downloads -
the native executable - bundles Python itself, so the program it installs needs
nothing. Updating works on two levels:
  - this wizard updates the EXECUTABLE when you publish a new build
    (version.json "launcher_version"),
  - the executable then keeps the APP CODE up to date on its own.

Edit GITHUB_USER / GITHUB_REPO below if they ever change.
"""

import os
import io
import sys
import json
import zipfile
import hashlib
import platform
import subprocess
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===========================================================================
# CONFIG
# ===========================================================================
GITHUB_USER = "ConPlusPlus"
GITHUB_REPO = "visual-python"
GITHUB_BRANCH = "main"
MANIFEST_URL = (f"https://raw.githubusercontent.com/{GITHUB_USER}/"
                f"{GITHUB_REPO}/{GITHUB_BRANCH}/version.json")

OS_KEYS = ["windows", "mac", "chromebook"]
OS_LABELS = {"windows": "Windows", "mac": "Mac", "chromebook": "Chromebook"}
# What the installed executable is called on disk, per OS.
INSTALLED_NAME = {"windows": "VisualPython.exe",
                  "mac": "VisualPython.app",
                  "chromebook": "VisualPython"}

COL_BG = "#1e1f26"
COL_PANEL = "#2d2f3a"
COL_TEXT = "#e6e6e6"
COL_ACCENT = "#4ea1ff"


# ===========================================================================
# Pure logic (no GUI) - testable
# ===========================================================================
def detect_os():
    s = platform.system()
    if s == "Windows":
        return "windows"
    if s == "Darwin":
        return "mac"
    return "chromebook"


def install_dir(os_key=None):
    home = Path.home()
    os_key = os_key or detect_os()
    if os_key == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", home))
    elif os_key == "mac":
        base = home / "Applications"
    else:
        base = home / ".local" / "share"
    base = base if base.exists() else home
    return base / "VisualPython"


def fetch_bytes(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "VisualPython-Setup"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_manifest(fetch=fetch_bytes):
    return json.loads(fetch(MANIFEST_URL).decode("utf-8"))


def launcher_url(manifest, os_key):
    return manifest.get("launchers", {}).get(os_key)


def parse_version(text):
    parts = []
    for chunk in str(text).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def exe_path(os_key, dest):
    return Path(dest) / INSTALLED_NAME[os_key]


def installed_info(dest):
    f = Path(dest) / "installed.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_installed(version, os_key, target, dest):
    info = {"launcher_version": version, "os": os_key, "exe": str(target)}
    (Path(dest) / "installed.json").write_text(json.dumps(info, indent=2),
                                               encoding="utf-8")


def install_launcher(os_key, dest, fetch=fetch_bytes):
    """Download + install the native executable for os_key. Returns
    (version, exe_path)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = get_manifest(fetch)
    url = launcher_url(manifest, os_key)
    if not url:
        raise ValueError(f"version.json has no download for '{os_key}'.")
    data = fetch(url)
    expected = manifest.get("launcher_sha256", {}).get(os_key)
    if expected and hashlib.sha256(data).hexdigest().lower() != expected.lower():
        raise ValueError("Download failed a security check (hash mismatch).")

    if os_key == "mac":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(dest)
        target = dest / "VisualPython.app"
        macos = target / "Contents" / "MacOS"
        if macos.exists():
            for f in macos.iterdir():
                try:
                    os.chmod(f, 0o755)
                except OSError:
                    pass
    elif os_key == "chromebook":
        target = dest / "VisualPython"
        target.write_bytes(data)
        try:
            os.chmod(target, 0o755)
        except OSError:
            pass
    else:  # windows
        target = dest / "VisualPython.exe"
        target.write_bytes(data)

    version = manifest.get("launcher_version", "0.0.0")
    write_installed(version, os_key, target, dest)
    return version, target


def check_update(dest, fetch=fetch_bytes):
    """Returns (has_update, remote_version, notes) for the executable."""
    local = installed_info(dest).get("launcher_version", "0.0.0")
    manifest = get_manifest(fetch)
    remote = manifest.get("launcher_version", "0.0.0")
    return is_newer(remote, local), remote, manifest.get("notes", "")


def launch(os_key, dest):
    t = exe_path(os_key, dest)
    if not t.exists():
        raise FileNotFoundError(t)
    if os_key == "mac":
        subprocess.Popen(["open", str(t)])
    else:
        subprocess.Popen([str(t)])


# ===========================================================================
# GUI wizard
# ===========================================================================
class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Visual Python - Setup")
        self.geometry("560x430")
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

    # ---- step 1: pick OS ----
    def show_welcome(self):
        self._clear()
        self._title("Get Visual Python")
        tk.Label(self.body,
                 text="Build Python by connecting blocks.\n"
                      "Which computer are you installing on?",
                 bg=COL_BG, fg="#b9c0d4", font=("Helvetica", 11),
                 justify="left").pack(anchor="w", pady=(8, 16))
        for key in OS_KEYS:
            tk.Radiobutton(self.body, text=OS_LABELS[key], value=key,
                           variable=self.os_key, command=self._os_changed,
                           bg=COL_BG, fg=COL_TEXT, selectcolor=COL_PANEL,
                           activebackground=COL_BG, activeforeground="#fff",
                           font=("Helvetica", 12)).pack(anchor="w", pady=2)
        tk.Label(self.body, text=f"(detected: {OS_LABELS[detect_os()]})",
                 bg=COL_BG, fg="#5b6075",
                 font=("Helvetica", 9)).pack(anchor="w", pady=(6, 0))
        nav = tk.Frame(self.body, bg=COL_BG)
        nav.pack(side="bottom", fill="x", pady=(20, 0))
        self._btn(nav, "Next  ›", self.show_install, primary=True).pack(side="right")

    def _os_changed(self):
        self.dest = install_dir(self.os_key.get())

    # ---- step 2: location + download ----
    def show_install(self):
        self._clear()
        self._title("Install")
        os_key = self.os_key.get()
        self.loc = tk.StringVar(value=str(self.dest))
        tk.Label(self.body, text=f"Computer:  {OS_LABELS[os_key]}",
                 bg=COL_BG, fg="#b9c0d4",
                 font=("Helvetica", 11)).pack(anchor="w", pady=(8, 6))
        row = tk.Frame(self.body, bg=COL_BG)
        row.pack(fill="x")
        tk.Label(row, text="Folder:", bg=COL_BG, fg="#b9c0d4",
                 font=("Helvetica", 10)).pack(side="left")
        tk.Entry(row, textvariable=self.loc, bg="#101117", fg=COL_TEXT,
                 insertbackground="#fff", relief="flat", width=42).pack(
                     side="left", padx=6)
        self._btn(row, "Change…", self._pick_dir).pack(side="left")

        tips = {
            "windows": "Downloads VisualPython.exe - just double-click to run.",
            "mac": "Downloads VisualPython.app - right-click > Open the 1st time.",
            "chromebook": "Downloads a Linux binary (needs Linux turned on).",
        }
        tk.Label(self.body, text=tips[os_key], bg=COL_BG, fg="#8a90a6",
                 font=("Helvetica", 10), justify="left").pack(anchor="w",
                                                              pady=(12, 8))
        self.status = tk.Label(self.body, text="", bg=COL_BG, fg=COL_ACCENT,
                               font=("Helvetica", 10), wraplength=500,
                               justify="left")
        self.status.pack(anchor="w")

        nav = tk.Frame(self.body, bg=COL_BG)
        nav.pack(side="bottom", fill="x", pady=(16, 0))
        self._btn(nav, "‹  Back", self.show_welcome).pack(side="left")
        self._btn(nav, "Download & Install", self._do_install,
                  primary=True).pack(side="right")

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.loc.get() or str(Path.home()))
        if d:
            self.loc.set(d)

    def _do_install(self):
        self.dest = Path(self.loc.get())
        self.status.config(text="Downloading from GitHub…", fg=COL_ACCENT)
        self.update_idletasks()
        try:
            version, target = install_launcher(self.os_key.get(), self.dest)
        except Exception as e:
            self.status.config(
                text=f"Couldn't install: {e}\n\nMake sure you're online and that "
                     "the developer has published the executables on a GitHub "
                     "Release.", fg="#ff6b6b")
            return
        self.show_done(version, target)

    # ---- step 3: done ----
    def show_done(self, version, target):
        self._clear()
        self._title("Installed!")
        tk.Label(self.body,
                 text=f"Visual Python {version} for {OS_LABELS[self.os_key.get()]}\n"
                      f"is installed at:\n{target}",
                 bg=COL_BG, fg="#b9c0d4", font=("Helvetica", 11),
                 justify="left").pack(anchor="w", pady=(8, 14))
        self.status2 = tk.Label(self.body, text="", bg=COL_BG, fg=COL_ACCENT,
                                font=("Helvetica", 10), wraplength=500,
                                justify="left")
        self.status2.pack(anchor="w")
        row = tk.Frame(self.body, bg=COL_BG)
        row.pack(side="bottom", fill="x", pady=(20, 0))
        self._btn(row, "Launch Visual Python", self._launch,
                  primary=True).pack(side="left")
        self._btn(row, "Check for updates", self._check).pack(side="left", padx=8)

    def _launch(self):
        try:
            launch(self.os_key.get(), self.dest)
        except Exception as e:
            messagebox.showerror("Could not launch", str(e))

    def _check(self):
        self.status2.config(text="Checking GitHub…", fg=COL_ACCENT)
        self.update_idletasks()
        try:
            has, remote, notes = check_update(self.dest)
        except Exception as e:
            self.status2.config(text=f"Couldn't check: {e}", fg="#ff6b6b")
            return
        if not has:
            self.status2.config(text="You have the latest version. ✓", fg="#7dd77d")
            return
        if messagebox.askyesno("Update available",
                               f"A newer version ({remote}) is available.\n\n"
                               f"{notes}\n\nDownload it now?"):
            try:
                version, target = install_launcher(self.os_key.get(), self.dest)
                self.status2.config(text=f"Updated to {version}. ✓", fg="#7dd77d")
            except Exception as e:
                self.status2.config(text=f"Update failed: {e}", fg="#ff6b6b")


if __name__ == "__main__":
    Wizard().mainloop()
