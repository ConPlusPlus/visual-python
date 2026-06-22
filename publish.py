"""
publish.py - ship a Visual Python update to the PUBLIC distribution repo.

Run this from your PRIVATE source folder. It bumps the version, copies the
files users actually download into a local clone of your PUBLIC repo, commits,
and (optionally) pushes. Your private history never leaves the private repo.

Usage:
    python publish.py --public C:\\VisualPython-public --bump patch --notes "..." --push

  --public  path to a local clone of the PUBLIC distribution repo  (required)
  --bump    patch | minor | major   (bumps version.json "version")
  --notes   release notes shown to users in the update prompt
  --push    actually run `git push` (otherwise it just commits locally)

Level B (executables only): pass --no-code to skip copying visual_python.py.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def bump_version(v, kind):
    nums = [int(x) for x in str(v).split(".")[:3]] + [0, 0, 0]
    major, minor, patch = nums[0], nums[1], nums[2]
    if kind == "major":
        major, minor, patch = major + 1, 0, 0
    elif kind == "minor":
        minor, patch = minor + 1, 0
    elif kind == "patch":
        patch += 1
    return f"{major}.{minor}.{patch}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", required=True,
                    help="local clone of the PUBLIC distribution repo")
    ap.add_argument("--bump", choices=["patch", "minor", "major"])
    ap.add_argument("--notes")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--no-code", action="store_true",
                    help="don't publish visual_python.py (Level B)")
    a = ap.parse_args(argv)

    pub = Path(a.public)
    if not (pub / ".git").exists():
        sys.exit(f"{pub} is not a git clone (no .git). Clone your public repo there.")

    manifest = json.loads((HERE / "version.json").read_text(encoding="utf-8"))
    if a.bump:
        manifest["version"] = bump_version(manifest.get("version", "0.0.0"), a.bump)
    if a.notes:
        manifest["notes"] = a.notes
    (HERE / "version.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    files = ["version.json"]
    if not a.no_code:
        files.append("visual_python.py")
    for f in files:
        shutil.copyfile(HERE / f, pub / f)

    version = manifest.get("version", "0.0.0")
    msg = f"Publish app v{version}" + (f": {a.notes}" if a.notes else "")
    subprocess.run(["git", "-C", str(pub), "add", *files], check=True)
    subprocess.run(["git", "-C", str(pub), "commit", "-m", msg], check=True)
    if a.push:
        subprocess.run(["git", "-C", str(pub), "push"], check=True)
        print(f"Published and pushed v{version} -> {pub}")
    else:
        print(f"Committed v{version} in {pub} (run again with --push, "
              "or push it yourself).")


if __name__ == "__main__":
    main()
