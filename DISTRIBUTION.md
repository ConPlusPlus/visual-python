# Distribution: private source, public updates

You want your repo private but the app's updates to keep working. The clean way
(no secret ever ships) is to **split into two repos**:

```
  PRIVATE  ConPlusPlus/visual-python-dev   <- your real work, history, extras
  PUBLIC   ConPlusPlus/visual-python        <- only what users download
```

**Why split?** Anything the app downloads — the manifest, the executables, and
(if you keep instant app-code updates) `visual_python.py` — is readable by
anyone who has the app. You cannot hand someone a program *and* keep the bytes
it runs secret; even a compiled `.exe` can be unpacked. So "private" here means
your **development repo** (work-in-progress, notes, unreleased features, the
launcher/build tooling) stays private, while a tiny **public repo** serves the
release artifacts. No token, no password, nothing leaks.

If you embed a token in the launcher instead, that token is extractable from the
app — so it isn't really private. That's why splitting is the recommended route.

---

## What goes where

**PUBLIC repo `visual-python` (the distribution repo)** — keep it public:
- `version.json`           (the update manifest)
- `visual_python.py`       (the app code — only if you keep instant updates; see below)
- `download.html`          (the OS-picker download page)
- `README.md`, `LICENSE`
- **Releases**: the built executables (`VisualPython.exe`, `VisualPython-mac.zip`,
  `VisualPython-linux`)

**PRIVATE repo `visual-python-dev`** — make it private:
- `visual_python.py`       (your canonical source)
- `vp_launcher.py`, `vp_setup.py`, `build_exe.py`, `publish.py`
- anything you don't want public

You develop in the private repo and **publish** to the public one when you ship.

---

## Two privacy levels — pick one

**Level A — dev private, app distributed publicly (recommended, keeps instant updates)**
The public repo includes `visual_python.py`, so the bundled exe keeps pulling
app-code updates instantly. Your *dev work* is private; the shipped app is open
(fine for a learning tool). This is the least disruptive — nothing about the
running app changes.

**Level B — app code not published openly (executables only)**
The public repo holds *only* `version.json` + the executables (no
`visual_python.py`, drop the `assets` block from the manifest). Updates ship by
rebuilding the exe and publishing a new Release; users get them via the setup
wizard / download page (`launcher_version`). The app `.py` never sits in a
public repo (it's still inside the exe, just not openly browsable). Trade-off:
every update means a rebuild + Release, not an instant file swap.

---

## One-time setup

1. On GitHub, create a **new private repo** `visual-python-dev`.
2. Push your full working folder there (everything in `C:\VisualPython`).
3. Keep `ConPlusPlus/visual-python` **public** as the distribution repo
   (it already has `version.json` + `visual_python.py`).
4. Keep a local clone of the public repo somewhere, e.g. `C:\VisualPython-public`.

## Publishing an update (Level A)

From your private dev folder:
```
python publish.py --public C:\VisualPython-public --bump patch --notes "what changed" --push
```
That bumps the version, copies `visual_python.py` + `version.json` into the
public clone, commits, and pushes. Every user gets it on next launch.

## Publishing a new executable (either level)

1. `python build_exe.py` on each OS.
2. On the **public** repo, create a Release (tag e.g. `v1.0.1`) and upload the
   built files using these exact names so the manifest/links resolve:
   `VisualPython.exe`, `VisualPython-mac.zip`, `VisualPython-linux`.
3. Bump `launcher_version` in the public `version.json` so the setup wizard
   offers the new installer.
