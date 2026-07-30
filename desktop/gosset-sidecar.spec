# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Gosset backend sidecar.

Build from the REPO ROOT so the relative data paths below mean what they say:

    .venv\\Scripts\\pyinstaller --noconfirm --clean desktop/gosset-sidecar.spec

--onedir (the `COLLECT` at the bottom), not --onefile. A onefile build unpacks the whole ~400 MB
bundle into a temp directory on every launch before the first line of Python runs, which costs
several seconds each time and is exactly the startup the desktop shell is trying to hide.

Two families of problem this file exists to solve, both of which fail SILENTLY in a frozen build:

1. **Imports PyInstaller's static analysis cannot see.** uvicorn resolves its loop and protocol
   implementations from strings at runtime; svglib is imported lazily inside the PDF path;
   statsmodels and sklearn reach for submodules through their own lazy-loading shims. None of them
   appear in an import graph, so each is collected explicitly below.
2. **Files read by path rather than imported.** The app is a web app, so the entire frontend has to
   travel; the report engine reads its own bundled fonts, and reads frontend/brand/mark.svg and
   make_favicons.py (the latter through importlib.util.spec_from_file_location, which no analyser
   will ever follow). They are laid out at the same RELATIVE paths they occupy in a checkout, which
   is what lets `Path(__file__).parent.parent.parent / "frontend"` in backend/ keep working verbatim
   when __file__ points inside the bundle instead of the repo.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REPO_ROOT = Path(SPECPATH).parent

# ---------------------------------------------------------------------------
# data: everything read from disk rather than imported
# ---------------------------------------------------------------------------

datas = [
    # The whole UI. It is served by StaticFiles, so it must exist as real files, and it must keep its
    # directory shape: app.js imports './brand/brand.js' and that import is resolved by the browser.
    (str(REPO_ROOT / "frontend"), "frontend"),
    # The five bundled OFL faces the PDF registers by filename, plus their licences (a redistributed
    # font without its licence is the licence being broken).
    (str(REPO_ROOT / "backend" / "report_engine" / "fonts"), "backend/report_engine/fonts"),
]

# Sample data, so a fresh install has something to open without the user finding a CSV first.
datas += [(str(p), "samples") for p in sorted(REPO_ROOT.glob("sample_*.csv"))]

# reportlab ships its own font metrics and unicode tables; python-docx and python-pptx each carry a
# default template .docx/.pptx that they open to create a document. Missing any of these is a
# FileNotFoundError from deep inside the library, at export time, on the user's machine.
for package in ("reportlab", "docx", "pptx", "svglib", "matplotlib", "sklearn", "statsmodels", "patsy"):
    try:
        datas += collect_data_files(package)
    except Exception:  # a package with no data files is not an error
        pass

# ---------------------------------------------------------------------------
# hidden imports: resolved at runtime, invisible to static analysis
# ---------------------------------------------------------------------------

hiddenimports = [
    # The app itself. sidecar.py imports backend.api inside main(), which defers it past the
    # analyser's reach on some PyInstaller versions.
    "backend.api",
    "backend.version",
    # uvicorn picks these up by name from its config strings — the single most common reason a
    # frozen FastAPI app starts and then serves nothing.
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # Lazily imported by report_engine/components.py for the vector brand mark.
    "svglib",
    "svglib.svglib",
    # svglib parses CSS on the way in.
    "cssselect2",
    "tinycss2",
    # Multipart upload parsing, imported by Starlette only when a form actually arrives.
    "python_multipart",
    "multipart",
    # scipy.stats reaches this one conditionally. (scipy.special._cdflib was also listed here until
    # PyInstaller reported it as not found — scipy removed that module, so naming it only produced a
    # scary ERROR line in a build that was fine.)
    "scipy._lib.array_api_compat.numpy.fft",
    # matplotlib's backend is selected by string (matplotlib.use("Agg")).
    "matplotlib.backends.backend_agg",
    # joblib's loky backend re-executes the interpreter for a process pool; sklearn reaches it
    # through a string too.
    "joblib.externals.loky.backend.spawn",
]

# statsmodels and sklearn both use lazy-loading module shims, so their submodule graph is not
# discoverable. Collecting whole trees is heavy-handed and costs disk, but the alternative is
# discovering a missing formula family or estimator from a user's bug report.
for package in ("statsmodels", "sklearn", "patsy", "scipy.stats", "pandas"):
    hiddenimports += collect_submodules(package)

a = Analysis(
    [str(REPO_ROOT / "sidecar.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(REPO_ROOT / "desktop" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here renders a GUI: the interface is a browser window Electron owns. Dropping the GUI
    # toolkits and the test suites is ~60 MB and removes matplotlib's ability to pick a backend that
    # would need a display.
    excludes=[
        # setuptools/pkg_resources are a BUILD dependency here, never a runtime one — the only
        # importers in site-packages are pip and PyInstaller's own hook, and the three library files
        # that mention pkg_resources do so in a comment or a test helper. Collecting it makes
        # PyInstaller inject its pyi_rth_pkgres runtime hook, which imports pkg_resources, which
        # imports its vendored jaraco.context, which imports `backports` — a module that is not
        # installed and is not a dependency of anything here. The bundle then dies on the FIRST line
        # of its bootstrap with ModuleNotFoundError: No module named 'backports', before any of this
        # app's code runs. Excluding it drops the hook with it.
        "pkg_resources",
        "setuptools",
        "pip",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "wx",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "sphinx",
        "matplotlib.backends.backend_qtagg",
        "matplotlib.backends.backend_tkagg",
        "matplotlib.backends.backend_webagg",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gosset-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressed Python extensions are a reliable source of mystery import failures
    # A CONSOLE build, deliberately, even though the user must never see a console. A windowed
    # (console=False) build leaves sys.stdout/sys.stderr as None, and uvicorn's logger writes to
    # stderr — which turns any log line into an exception. The shell spawns this with
    # windowsHide: true (CREATE_NO_WINDOW) and pipes both streams, so the streams are real, the
    # output reaches Electron's log, and no window ever appears.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="gosset-sidecar",
)
