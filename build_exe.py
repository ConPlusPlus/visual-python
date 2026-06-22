"""
Build the native Visual Python executable for THIS operating system.

PyInstaller can't cross-compile, so run this once on each OS you support:
    pip install pyinstaller
    python build_exe.py

Produces, in dist/, the file you upload to your GitHub Release:
    Windows           -> VisualPython.exe
    Mac (Darwin)      -> VisualPython-mac.zip   (a zipped VisualPython.app)
    Chromebook/Linux  -> VisualPython-linux     (an executable binary)

The asset names above are exactly what version.json's "launchers" URLs and
download.html expect, so users always get the right type for their computer.
The app code (visual_python.py) is bundled inside for an offline first run;
after that the launcher auto-updates it from GitHub.
"""

import os
import sys
import shutil
import platform
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "visual_python.py")
LAUNCHER = os.path.join(HERE, "vp_launcher.py")
DIST = os.path.join(HERE, "dist")


def targets(sysname, dist=DIST):
    """What PyInstaller produces and what to ship, per OS."""
    if sysname == "Windows":
        return {"built": os.path.join(dist, "VisualPython.exe"),
                "asset": "VisualPython.exe", "package": "as-is"}
    if sysname == "Darwin":
        return {"built": os.path.join(dist, "VisualPython.app"),
                "asset": "VisualPython-mac.zip", "package": "zip-app"}
    return {"built": os.path.join(dist, "VisualPython"),
            "asset": "VisualPython-linux", "package": "copy-binary"}


def build():
    for path in (APP, LAUNCHER):
        if not os.path.exists(path):
            sys.exit(f"Missing {path}")

    args = [
        "--noconfirm", "--onefile", "--windowed",
        "--name", "VisualPython",
        "--add-data", f"{APP}{os.pathsep}.",   # ';' Windows / ':' elsewhere
        "--distpath", DIST,
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", HERE,
    ]
    for ic in ("icon.ico", "icon.icns"):
        p = os.path.join(HERE, ic)
        if os.path.exists(p):
            args += ["--icon", p]
            break
    args.append(LAUNCHER)

    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("PyInstaller not found - installing it…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        import PyInstaller.__main__ as pyi

    print("Building with args:", " ".join(args))
    pyi.run(args)

    t = targets(platform.system())
    built = t["built"]
    if not os.path.exists(built):
        sys.exit(f"\nBuild finished but {built} is missing - check dist/.")

    # package into the named asset users will download
    asset_path = os.path.join(DIST, t["asset"])
    if t["package"] == "as-is":
        asset_path = built
    elif t["package"] == "zip-app":
        base = os.path.join(DIST, "VisualPython-mac")
        if os.path.exists(base + ".zip"):
            os.remove(base + ".zip")
        shutil.make_archive(base, "zip", root_dir=DIST, base_dir="VisualPython.app")
        asset_path = base + ".zip"
    elif t["package"] == "copy-binary":
        shutil.copyfile(built, asset_path)
        os.chmod(asset_path, 0o755)

    print("\nDone.")
    print("Built:          ", built)
    print("Upload to Release as:", t["asset"])
    print("Asset file:     ", asset_path)


if __name__ == "__main__":
    build()
