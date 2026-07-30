"""Exercise every heavy dependency in a running sidecar, over HTTP.

Run against a source checkout and against the PyInstaller bundle; the point is that the two answer
identically. A frozen build's failures are almost all missing hidden imports, and they only surface
when the code path actually runs — importing the app proves nothing about scikit-learn, and a passing
ANOVA proves nothing about reportlab. So each check below is chosen to be the FIRST thing that drags
a whole library in:

    /health                 the app object serves at all
    /                       the static frontend is bundled, not just importable
    basic-stats             pandas + scipy.stats
    anova (GLM)             statsmodels + patsy formula machinery
    regression-model        statsmodels again, plus the safe-id predictor path
    segmentation            scikit-learn (and joblib's process pool under it)
    chart                   matplotlib, its font cache and the Agg backend
    reports (pdf)           reportlab AND svglib -> the vector brand mark
    reports (docx/xlsx/pptx) python-docx, openpyxl, python-pptx, Pillow

Usage:  python desktop/scripts/smoke_sidecar.py http://127.0.0.1:8123
"""

from __future__ import annotations

import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE = REPO_ROOT / "sample_factorial.csv"

_results: list[tuple[bool, str, str]] = []


def _call(method: str, url: str, body: dict | None = None, timeout: float = 180.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def _upload(url: str, path: Path) -> dict:
    """Multipart by hand — this script must not need `requests` installed to test a build."""
    boundary = f"----gosset{uuid.uuid4().hex}"
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for name, value in (("source_type", "csv"),):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n".encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    payload = b"".join(parts)

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def check(label: str):
    """Record a pass/fail without letting one broken library hide the state of the others."""

    def run(fn):
        try:
            detail = fn() or "ok"
            _results.append((True, label, str(detail)))
        except urllib.error.HTTPError as exc:
            _results.append((False, label, f"HTTP {exc.code}: {exc.read()[:300].decode(errors='replace')}"))
        except Exception as exc:  # noqa: BLE001 - a smoke test reports every failure, never raises
            _results.append((False, label, f"{type(exc).__name__}: {exc}"))
        return fn

    return run


def main(base: str) -> int:
    base = base.rstrip("/")

    @check("health")
    def _health():
        got = _call("GET", f"{base}/health")
        assert got.get("status") == "ok", got
        return f"v{got.get('version')} pid {got.get('pid')}"

    @check("static frontend")
    def _static():
        with urllib.request.urlopen(f"{base}/", timeout=30) as r:
            html = r.read().decode(errors="replace")
        assert "<title>" in html.lower(), "index.html did not come back"
        # The bundle has to carry the ES modules and the brand assets, not just index.html.
        for asset in ("/app.js", "/brand/mark.svg", "/brand/version.js", "/style.css"):
            with urllib.request.urlopen(f"{base}{asset}", timeout=30) as r:
                assert r.status == 200 and r.read(), f"{asset} is empty"
        return "index + app.js + mark.svg + version.js + style.css"

    if not SAMPLE.is_file():
        _results.append((False, "sample data", f"missing {SAMPLE}"))
        return _report()

    loaded = _upload(f"{base}/datasets", SAMPLE)
    did = loaded["dataset_id"]
    cols = [c["name"] if isinstance(c, dict) else c for c in loaded.get("columns", [])]
    _results.append((True, "csv upload", f"{did} — {len(cols)} columns"))

    # Every dispatching endpoint takes the same shape: an ordered `columns` list whose response comes
    # first, with the split between kinds declared in `options` (n_factors / n_continuous) so the
    # backend never has to guess a column's role from its dtype. The result is nested under `result`.
    @check("pandas + scipy (basic-stats)")
    def _basic():
        got = _call("POST", f"{base}/datasets/{did}/basic-stats",
                    {"procedure": "display_descriptives", "columns": ["strength"]})
        assert got["result"]["tables"], got
        return f"{len(got['result']['tables'])} table(s)"

    @check("statsmodels + patsy (ANOVA GLM)")
    def _anova():
        got = _call("POST", f"{base}/datasets/{did}/anova", {
            "procedure": "glm",
            "columns": ["strength", "machine", "shift", "temp_c"],
            "options": {"n_factors": 2, "interactions": True},
        })
        tables = got["result"]["tables"]
        assert any("Variance" in t["title"] for t in tables), tables
        return f"{len(tables)} table(s)"

    @check("statsmodels (regression)")
    def _reg():
        got = _call("POST", f"{base}/datasets/{did}/regression-model", {
            "procedure": "fit_model",
            "columns": ["strength", "temp_c", "pressure_bar"],
            "options": {"n_continuous": 2},
        })
        tables = got["result"]["tables"]
        assert any("Coefficients" in t["title"] for t in tables), tables
        return f"{len(tables)} table(s)"

    @check("scikit-learn (segmentation)")
    def _seg():
        got = _call("POST", f"{base}/datasets/{did}/segmentation",
                    {"columns": ["strength", "temp_c"], "n_segments": 3})
        assert got.get("segments"), got
        return f"{len(got['segments'])} segments"

    @check("matplotlib (server-side chart)")
    def _chart():
        got = _call("POST", f"{base}/datasets/{did}/chart",
                    {"chart_type": "histogram", "columns": ["strength"]})
        assert got.get("chart_path") or got.get("image_base64"), got
        return Path(str(got.get("chart_path", "inline"))).name

    section = {
        "title": "Smoke: descriptive statistics",
        "data": {
            "tables": [{"title": "Summary", "rows": [{"Statistic": "N", "Value": 96}]}],
            "highlights": [{"label": "Rows", "value": 96}],
            "conclusion": "A smoke-test section, rendered by every exporter.",
            "p_value": 0.012,
        },
    }

    @check("reportlab + svglib (PDF)")
    def _pdf():
        got = _call("POST", f"{base}/reports",
                    {"dataset_id": did, "format": "pdf", "analyses": [section],
                     "report_name": "gosset_smoke"})
        files = got.get("files") or []
        assert files and files[0].lower().endswith(".pdf"), got
        return Path(files[0]).name

    for fmt, lib in (("docx", "python-docx"), ("xlsx", "openpyxl"), ("pptx", "python-pptx"),
                     ("markdown", "stdlib")):
        @check(f"{lib} ({fmt})")
        def _doc(fmt=fmt):
            got = _call("POST", f"{base}/reports",
                        {"dataset_id": did, "format": fmt, "analyses": [section],
                         "report_name": f"gosset_smoke_{fmt}"})
            files = got.get("files") or []
            assert files, got
            return Path(files[0]).name

    return _report()


def _report() -> int:
    width = max(len(label) for _, label, _ in _results) + 2
    failed = 0
    print()
    for ok, label, detail in _results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label.ljust(width)} {detail}")
        failed += 0 if ok else 1
    print()
    if failed:
        print(f"{failed} of {len(_results)} checks FAILED")
    else:
        print(f"all {len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
