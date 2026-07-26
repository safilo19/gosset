"""export_report logic: renders prior structuredContent results to Markdown/xlsx.

Plain Python — no MCP or web-framework code.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage

# backend/core/reports.py -> backend/core -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

_TABLE_KEYS_PRIORITY = [
    "coefficients",
    "forecast",
    "segments",
    "strongest_pairs",
    "stats",
    "groups",
    "datasets",
    "preview",
]

# Fields that are never useful in a rendered key/value table: raw image bytes (the chart is already
# embedded as an actual image via chart_path) and anything else absurdly long for a table cell.
_SCALAR_EXCLUDE_KEYS = {"image_base64"}
_SCALAR_MAX_LEN = 300


@dataclass
class ReportSection:
    title: str
    data: dict[str, Any]
    chart_path: str | None = None


def default_stem(dataset_id: str) -> str:
    return f"report_{dataset_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def summarize_export(dataset_id: str, section_titles: list[str], paths: list[Path]) -> str:
    return f"Exported {len(section_titles)} section(s) for dataset '{dataset_id}' to: {', '.join(str(p) for p in paths)}."


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "section"


def _sheet_name(title: str, index: int, used_names: set[str]) -> str:
    cleaned = re.sub(r"[:\\/?*\[\]]", "-", title).strip()[:28] or f"Sheet{index}"
    name = cleaned
    suffix = 1
    while name in used_names:
        name = f"{cleaned[:25]}_{suffix}"
        suffix += 1
    return name


def _extract_table(data: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]], dict[str, Any]]:
    """Pull the first known list-of-dicts (or matrix-like dict) out of `data` as the main table;
    everything else scalar goes in a separate key/value table."""
    table_key: str | None = None
    rows: list[dict[str, Any]] = []

    for key in _TABLE_KEYS_PRIORITY:
        value = data.get(key)
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            table_key = key
            rows = value
            break

    if table_key is None:
        for key in ("matrix", "contingency_table"):
            value = data.get(key)
            if isinstance(value, dict) and value:
                table_key = key
                rows = [{"": row_key, **row_val} for row_key, row_val in value.items()]
                break

    scalars = {
        k: v
        for k, v in data.items()
        if k != table_key
        and k not in _SCALAR_EXCLUDE_KEYS
        and not isinstance(v, (list, dict))
        and len(str(v)) <= _SCALAR_MAX_LEN
    }
    return table_key, rows, scalars


def _xlsx_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _scalars_to_md(scalars: dict[str, Any]) -> str:
    if not scalars:
        return ""
    lines = ["| Field | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in scalars.items()]
    return "\n".join(lines)


def _rows_to_md(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(str(row.get(h, "")) for h in headers) + " |" for row in rows]
    return "\n".join(lines)


def render_markdown(dataset_id: str, sections: list[ReportSection], stem: str) -> Path:
    lines = [f"# Analysis Report — dataset `{dataset_id}`", ""]

    for i, section in enumerate(sections, start=1):
        lines.append(f"## {i}. {section.title}")
        lines.append("")
        table_key, rows, scalars = _extract_table(section.data)

        scalar_md = _scalars_to_md(scalars)
        if scalar_md:
            lines.append(scalar_md)
            lines.append("")
        if rows:
            lines.append(f"**{table_key}:**")
            lines.append("")
            lines.append(_rows_to_md(rows))
            lines.append("")
        if section.chart_path and Path(section.chart_path).exists():
            dest_name = f"{stem}_{i}_{_slugify(section.title)}.png"
            shutil.copyfile(section.chart_path, OUTPUT_DIR / dest_name)
            lines.append(f"![{section.title}]({dest_name})")
            lines.append("")

    md_path = OUTPUT_DIR / f"{stem}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# xlsx
# ---------------------------------------------------------------------------


def render_xlsx(dataset_id: str, sections: list[ReportSection], stem: str) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    used_names: set[str] = set()

    for i, section in enumerate(sections, start=1):
        sheet_name = _sheet_name(section.title, i, used_names)
        used_names.add(sheet_name)
        ws = wb.create_sheet(title=sheet_name)

        table_key, rows, scalars = _extract_table(section.data)

        row_cursor = 1
        for k, v in scalars.items():
            ws.cell(row=row_cursor, column=1, value=k)
            ws.cell(row=row_cursor, column=2, value=_xlsx_safe(v))
            row_cursor += 1

        if rows:
            row_cursor += 1
            headers = list(rows[0].keys())
            for col_idx, header in enumerate(headers, start=1):
                ws.cell(row=row_cursor, column=col_idx, value=header)
            row_cursor += 1
            for row in rows:
                for col_idx, header in enumerate(headers, start=1):
                    ws.cell(row=row_cursor, column=col_idx, value=_xlsx_safe(row.get(header)))
                row_cursor += 1

        if section.chart_path and Path(section.chart_path).exists():
            img = XLImage(section.chart_path)
            ws.add_image(img, f"A{row_cursor + 2}")

    xlsx_path = OUTPUT_DIR / f"{stem}.xlsx"
    wb.save(xlsx_path)
    return xlsx_path


def build_report(dataset_id: str, fmt: str, sections: list[ReportSection], stem: str) -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    if fmt in ("markdown", "both"):
        paths.append(render_markdown(dataset_id, sections, stem))
    if fmt in ("xlsx", "both"):
        paths.append(render_xlsx(dataset_id, sections, stem))
    return paths
