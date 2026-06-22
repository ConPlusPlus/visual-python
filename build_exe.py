"""
Build VisualPython.exe (or a Mac .app / Linux binary) from vp_launcher.py.

Run this ON the OS you want to build for (PyInstaller can't cross-compile):
    pip install pyinstaller
    python build_exe.py

Output:  dist/VisualPython(.exe)
The app code (visual_python.py) is bundled inside so first run works offline;
after that the launcher auto-updates it from GitHub.
"""

import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "visual_python.py")
LAUNCHER = os.path.join(HERE, "vp_launcher.py")


def build():
    if not os.path.exists(APP):
        sys.exit(f"Missing {APP}")
    if not os.path.exists(LAUNCHER):
        sys.exit(f"Missing {LAUNCHER}")

    # --add-data uses ';' on Windows, ':' elsewhere (os.pathsep handles it)
    add_data = f"{APP}{os.pathsep}."
    args = [
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", "VisualPython",
        "--add-data", add_data,
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", HERE,
        LAUNCHER,
    ]
    icon = os.path.join(HERE, "icon.ico")
    if os.path.exists(icon):
        args += ["--icon", icon]

    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("PyInstaller not found - installing it…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        import PyInstaller.__main__ as pyi

    print("Building with args:", " ".join(args))
    pyi.run(args)
    out = os.path.join(HERE, "dist",
                       "VisualPython.exe" if os.name == "nt" else "VisualPython")
    print("\nDone." if os.path.exists(out) else "\nFinished (check dist/).")
    if os.path.exists(out):
        print("Executable:", out)


if __name__ == "__main__":
    build()
