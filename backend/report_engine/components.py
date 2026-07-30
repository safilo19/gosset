"""The report's flowables. Each one is a component the builder composes; none of them know about
pages, templates or files.

Two decisions run through the whole module:

* **A card is a single-cell Table, not a custom Flowable.** reportlab's Table already knows how to
  split across a page break and re-draw its own BOX on each fragment, which is exactly the "border
  continues" behaviour a card needs. Writing a Flowable with a correct `split()` would be a lot of
  code to reimplement that, badly. `ROUNDEDCORNERS` gives the 6pt radius.
* **Nothing parses prose.** A verdict comes from structured fields on the analysis result
  (`verdict_label` / `verdict_polarity` / `key_stat`); `verdict.py` derives them once, from numbers.
  Regex over a sentence would break the first time an analysis reworded its conclusion.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Iterable

from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, KeepTogether, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics

from backend.report_engine import theme

# ---------------------------------------------------------------------------
# paragraph styles
# ---------------------------------------------------------------------------


def _style(name: str, font: str, size: float, color, *, leading: float | None = None,
           align: int = TA_LEFT, space_before: float = 0, space_after: float = 0,
           left_indent: float = 0) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=size,
        leading=leading if leading is not None else size * theme.LEADING_RATIO,
        textColor=color,
        alignment=align,
        spaceBefore=space_before,
        spaceAfter=space_after,
        leftIndent=left_indent,
    )


def styles() -> dict[str, ParagraphStyle]:
    theme.ensure_fonts()
    return {
        "cover_title": _style("cover_title", theme.SERIF_BOLD, theme.SIZE_COVER_TITLE, theme.INK, leading=theme.SIZE_COVER_TITLE * 1.16),
        "cover_meta": _style("cover_meta", theme.MONO, theme.SIZE_META, theme.MUTED, space_before=5),
        "card_title": _style("card_title", theme.SERIF_BOLD, theme.SIZE_CARD_TITLE, theme.INK, leading=theme.SIZE_CARD_TITLE * 1.2),
        "card_meta": _style("card_meta", theme.MONO, theme.SIZE_META, theme.MUTED, space_before=2),
        "body": _style("body", theme.SERIF, theme.SIZE_BODY, theme.INK, space_after=4),
        "caption": _style("caption", theme.SANS, theme.SIZE_CAPTION, theme.INK_80, leading=theme.SIZE_CAPTION * 1.45, space_before=5),
        "note": _style("note", theme.SERIF, theme.SIZE_BODY + 0.5, theme.INK, leading=(theme.SIZE_BODY + 0.5) * 1.5, left_indent=10 * mm),
        "verdict": _style("verdict", theme.SANS_MEDIUM, theme.SIZE_BODY + 0.5, theme.INK),
        "cell": _style("cell", theme.SANS, theme.SIZE_TABLE, theme.INK, leading=theme.SIZE_TABLE * 1.25),
        "cell_num": _style("cell_num", theme.MONO, theme.SIZE_TABLE, theme.INK, leading=theme.SIZE_TABLE * 1.25, align=TA_RIGHT),
        "cell_head": _style("cell_head", theme.SANS_MEDIUM, theme.SIZE_TABLE, theme.INK, leading=theme.SIZE_TABLE * 1.25),
        "group_label": _style("group_label", theme.MONO, theme.SIZE_GROUP_LABEL, theme.MUTED),
        # "… 76 more rows — full table available in Gosset": mono and muted, so a truncated table's
        # last line reads as the document speaking rather than as one more row of data.
        "table_note": _style("table_note", theme.MONO, theme.SIZE_GROUP_LABEL, theme.MUTED, space_before=1),
        "empty": _style("empty", theme.SANS, theme.SIZE_CAPTION, theme.MUTED),
    }


# ---------------------------------------------------------------------------
# the logo, as vector
# ---------------------------------------------------------------------------

_MARK_SVG = Path(__file__).resolve().parent.parent.parent / "frontend" / "brand" / "mark.svg"
_mark_cache: dict[str, Any] = {}


def mark_drawing(color=theme.INK):
    """The Gosset mark from frontend/brand/mark.svg, as a reportlab Drawing (vector, not a raster).

    mark.svg strokes with `currentColor`, which has no meaning outside a document — svglib parses it
    but the resulting colour is not something to rely on, so it is substituted with a real one before
    parsing. That keeps ONE source of truth for the geometry: edit the SVG and the PDF follows.
    """
    key = color.hexval() if hasattr(color, "hexval") else str(color)
    if key in _mark_cache:
        return _mark_cache[key]
    if not _MARK_SVG.is_file():
        raise FileNotFoundError(f"The brand mark is missing: {_MARK_SVG}")
    from svglib.svglib import svg2rlg  # imported lazily: only the PDF path needs it

    hex_value = "#%02X%02X%02X" % (int(color.red * 255), int(color.green * 255), int(color.blue * 255))
    source = _MARK_SVG.read_text(encoding="utf-8").replace("currentColor", hex_value)
    drawing = svg2rlg(io.StringIO(source))
    if drawing is None:
        raise ValueError(f"svglib could not parse {_MARK_SVG}")
    _mark_cache[key] = drawing
    return drawing


def draw_mark(canvas, x: float, y: float, size: float, color=theme.INK) -> None:
    """Paint the mark with its bottom-left at (x, y), scaled to `size` square."""
    from reportlab.graphics import renderPDF

    drawing = mark_drawing(color)
    scale = size / max(drawing.width, drawing.height)
    canvas.saveState()
    canvas.translate(x, y)
    canvas.scale(scale, scale)
    renderPDF.draw(drawing, canvas, 0, 0)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# small drawn flowables
# ---------------------------------------------------------------------------


class Hairline(Flowable):
    """The thin rule inside a card header. Not the t-curve — that belongs to the page, not the card."""

    def __init__(self, width: float, color=theme.HAIRLINE, thickness: float = 0.5, space_before: float = 6, space_after: float = 8):
        super().__init__()
        self.width = width
        self.color = color
        self.thickness = thickness
        self._before = space_before
        self._after = space_after

    def wrap(self, available_width: float, available_height: float):
        self.width = available_width
        return available_width, self.thickness + self._before + self._after

    def draw(self) -> None:
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        y = self._after
        self.canv.line(0, y, self.width, y)


class CurveRule(Flowable):
    """The t-curve as an in-flow flowable, for the Word-parity image and any in-body divider."""

    def __init__(self, width: float, peak: float = theme.CURVE_PEAK, invert: bool = False, space: float = 4):
        super().__init__()
        self.width = width
        self.peak = peak
        self.invert = invert
        self._space = space

    def wrap(self, available_width: float, available_height: float):
        self.width = available_width
        return available_width, self.peak + self._space * 2

    def draw(self) -> None:
        theme.draw_t_curve(self.canv, 0, self._space, self.width, self.peak, invert=self.invert)


# ---------------------------------------------------------------------------
# the curve as a raster, for the formats that cannot draw
# ---------------------------------------------------------------------------


def curve_png(dest: Path, width_pt: float = 468, peak_pt: float = theme.CURVE_PEAK, *, invert: bool = False,
              color: str = "#161616", line_width_pt: float = theme.RULE_WIDTH, dpi: int = 300) -> Path:
    """The SAME t-curve, rasterised, so Word and PowerPoint carry the identical signature.

    Word cannot draw a vector path inline, so its header rule is an image — but it must be the same
    shape as the PDF's, not a hand-drawn approximation. This calls `theme.t_curve_points`, the one
    function that defines the curve, and would change with it.

    PIL draws no antialiasing on lines, so the curve is drawn at 4x and downsampled: at 0.6pt a hard
    aliased line looks like a dotted one at Word's rendering size.
    """
    from PIL import Image as PILImage
    from PIL import ImageDraw

    dest.parent.mkdir(parents=True, exist_ok=True)
    supersample = 4
    px_per_pt = dpi / 72.0 * supersample
    width_px = max(8, int(round(width_pt * px_per_pt)))
    stroke_px = max(1, int(round(line_width_pt * px_per_pt)))
    # Height leaves the stroke room at both ends so a round cap is never clipped.
    height_px = max(4, int(round(peak_pt * px_per_pt))) + stroke_px * 2

    canvas = PILImage.new("RGBA", (width_px, height_px), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)
    baseline = height_px - stroke_px if not invert else stroke_px
    points = theme.t_curve_points(width_pt, peak_pt, invert=invert)
    # y is measured UP from the baseline in PDF space and DOWN in image space, hence the subtraction.
    pixels = [(x * px_per_pt, baseline - y * px_per_pt) for x, y in points]
    draw.line(pixels, fill=color, width=stroke_px, joint="curve")

    final = canvas.resize((width_px // supersample, max(1, height_px // supersample)), PILImage.LANCZOS)
    final.save(dest, format="PNG", dpi=(dpi, dpi))
    return dest


def _mark_outline():
    """The mark's geometry as (xs, ys) in its 32x32 viewBox, y pointing DOWN as the SVG does.

    Imported from frontend/brand/make_favicons.py rather than re-typed: that script already owns the
    curve-and-arc arithmetic that turns mark.svg's path data into points, and a third copy of those
    numbers is a third thing to forget to update. mark.svg stays the vector source of truth — this is
    only for the formats that need pixels.
    """
    import importlib.util

    script = Path(__file__).resolve().parent.parent.parent / "frontend" / "brand" / "make_favicons.py"
    spec = importlib.util.spec_from_file_location("gosset_mark_geometry", script)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot load the mark geometry from {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.outline()


def mark_png(dest: Path, size_px: int = 128, color: str = "#161616", stroke_units: float = 2.2) -> Path:
    """The Gosset mark as a transparent PNG at `size_px` square, for Word and PowerPoint.

    matplotlib rather than reportlab's renderPM: renderPM needs the rlPyCairo backend, which is a
    compiled dependency this project deliberately avoids (the same reason the PDF path is reportlab and
    not weasyprint). matplotlib is already here for the server-rendered charts.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        return dest  # one raster per run is plenty; the geometry cannot change mid-process

    xs, ys = _mark_outline()
    dpi = 100
    fig = plt.figure(figsize=(size_px / dpi, size_px / dpi), dpi=dpi)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 32)
    ax.set_ylim(32, 0)  # y down, matching the SVG viewBox
    line_width = stroke_units * (size_px / 32) * (72 / dpi)  # units -> px -> points
    ax.plot(xs, ys, color=color, linewidth=line_width, solid_capstyle="round",
            solid_joinstyle="round", antialiased=True)
    fig.savefig(dest, dpi=dpi, transparent=True)
    plt.close(fig)
    return dest


# ---------------------------------------------------------------------------
# VerdictBadge
# ---------------------------------------------------------------------------

_POLARITY_COLOR = {"positive": theme.SUCCESS, "negative": theme.DANGER, "neutral": theme.MUTED}


class _Dot(Flowable):
    """The badge's coloured dot, DRAWN rather than typeset.

    None of the five bundled faces contains U+25CF (BLACK CIRCLE) — checked with fontTools — so setting
    "●" as text produced a silent blank: a missing glyph renders as nothing at all, and the badge lost
    the one element carrying its meaning. U+2022 (•) exists everywhere but is a bullet, noticeably
    smaller and vertically off-centre for this job. A filled circle on the canvas is exact, immune to
    whatever the font happens to cover, and scales with the type size.
    """

    def __init__(self, radius: float, color, line_height: float):
        super().__init__()
        self.radius = radius
        self.color = color
        self._line_height = line_height

    def wrap(self, available_width: float, available_height: float):
        return self.radius * 2, self._line_height

    def draw(self) -> None:
        self.canv.setFillColor(self.color)
        # Sit on the text's optical centre rather than its baseline.
        self.canv.circle(self.radius, self._line_height * 0.38, self.radius, stroke=0, fill=1)


def verdict_badge(label: str, polarity: str = "neutral", key_stat: str = "") -> Flowable:
    """"● Significant   p = 0.003" — the dot carries the colour, the label the meaning, the stat the number.

    A two-cell table rather than one Paragraph, because the dot is a drawn circle (see _Dot) and
    reportlab cannot place a flowable inline in a Paragraph. The text cell is still a Paragraph, so a
    long verdict wraps instead of running off the card.
    """
    css = styles()
    color = _POLARITY_COLOR.get(polarity, theme.MUTED)
    size = css["verdict"].fontSize
    leading = css["verdict"].leading

    bits = [f"<b>{_escape(label)}</b>"]
    if key_stat:
        bits.append(
            f'<font name="{theme.MONO}" size="{size - 0.5}" color="{theme.INK_80.hexval()}">{_escape(key_stat)}</font>'
        )
    text = Paragraph("&nbsp;&nbsp;&nbsp;".join(bits), css["verdict"])

    dot_width = size * 0.62
    badge = Table([[_Dot(size * 0.26, color, leading), text]], colWidths=[dot_width + 5, None], hAlign="LEFT")
    badge.setStyle(
        TableStyle([
            ("FONT", (0, 0), (-1, -1), theme.SANS, size),  # see stat_table: keeps Helvetica out
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    return badge


def _escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# StatTable
# ---------------------------------------------------------------------------

# A table wider than this fraction of the frame gets the smaller size; wider still and its card goes
# landscape. Truncating a column is never an option — a report that hides a number is worse than a
# report that turns sideways.
SHRINK_AT = 1.0
LANDSCAPE_AT = 1.0


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def format_cells(rows: list[dict[str, Any]], headers: list[str], decimals: int,
                 formatter) -> dict[tuple[int, str], str]:
    """Every cell's text, with each numeric column given a CONSISTENT number of decimals.

    The app's `cell_text` drops the decimals from a whole number, which is right for a lone scalar and
    wrong inside a column: a P column reading `0.003 / 0.117 / 0` lines up on nothing and reads as three
    different precisions. So if any value in a column is fractional, every number in that column is
    formatted to `decimals` — which is what makes a right-aligned mono column scan as one quantity.
    """
    text: dict[tuple[int, str], str] = {}
    for header in headers:
        values = [row.get(header) for row in rows]
        numbers = [v for v in values if _is_number(v)]
        fractional = any(not float(v).is_integer() for v in numbers)
        for index, value in enumerate(values):
            if fractional and _is_number(value):
                text[(index, header)] = f"{float(value):.{decimals}f}"
            else:
                text[(index, header)] = formatter(value, decimals)
    return text


def _measure(rows: list[dict[str, Any]], headers: list[str], font: str, size: float,
             cells: dict[tuple[int, str], str]) -> list[float]:
    """Natural width of each column: the widest of its header and its cells, plus padding."""
    widths = []
    for header in headers:
        widest = pdfmetrics.stringWidth(str(header), theme.SANS_MEDIUM, size)
        for index, row in enumerate(rows):
            text = cells[(index, header)]
            widest = max(widest, pdfmetrics.stringWidth(text, theme.MONO if _is_number(row.get(header)) else font, size))
        widths.append(widest + 12)
    return widths


def stat_table(rows: list[dict[str, Any]], available_width: float, decimals: int, formatter,
               *, group_labels: dict[int, str] | None = None) -> tuple[Table | Paragraph, bool]:
    """A results table in the house style, and whether its card needs landscape.

    No vertical rules, thin horizontal ones, a shaded header row, numbers right-aligned in mono with
    consistent decimals. `group_labels` maps a row index to a small-caps mono band ("SETUP",
    "MODEL QUALITY") for grouped key/value model output.

    Returns (flowable, needs_landscape). The caller decides what to do with the second value, because
    only the builder can change the page template.
    """
    css = styles()
    if not rows:
        return Paragraph("No rows.", css["empty"]), False

    headers: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in headers:
                headers.append(key)

    cells = format_cells(rows, headers, decimals, formatter)
    size = theme.SIZE_TABLE
    widths = _measure(rows, headers, theme.SANS, size, cells)
    total = sum(widths)
    needs_landscape = False
    if total > available_width * SHRINK_AT:
        size = theme.SIZE_TABLE_SMALL
        widths = _measure(rows, headers, theme.SANS, size, cells)
        total = sum(widths)
        if total > available_width * LANDSCAPE_AT:
            needs_landscape = True

    # Scale to the frame once the size is settled. In landscape the caller passes the wider width, so
    # this is a final safety fit rather than a squeeze.
    if total > available_width:
        factor = available_width / total
        widths = [w * factor for w in widths]

    cell = ParagraphStyle("c", parent=css["cell"], fontSize=size, leading=size * 1.25)
    cell_num = ParagraphStyle("cn", parent=css["cell_num"], fontSize=size, leading=size * 1.25)
    cell_head = ParagraphStyle("ch", parent=css["cell_head"], fontSize=size, leading=size * 1.25)

    data: list[list[Any]] = [[Paragraph(_escape(h), cell_head) for h in headers]]
    style: list[tuple] = [
        # An explicit FONT on every table is NOT redundant even though every cell is a Paragraph with
        # its own font: reportlab's CellStyle.fontname defaults to Helvetica, and a table without this
        # command declares Helvetica in the page's font resources — where a PDF font audit sees it.
        ("FONT", (0, 0), (-1, -1), theme.SANS, size),
        ("BACKGROUND", (0, 0), (-1, 0), theme.HEADER_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, theme.BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]

    labels = group_labels or {}
    table_row = 1
    for index, row in enumerate(rows):
        if index in labels:
            # A group band spans every column; it is a label, not data, so it gets no rules.
            data.append([Paragraph(_escape(labels[index]).upper(), css["group_label"])] + [""] * (len(headers) - 1))
            style += [
                ("SPAN", (0, table_row), (-1, table_row)),
                ("TOPPADDING", (0, table_row), (-1, table_row), 9),
                ("BOTTOMPADDING", (0, table_row), (-1, table_row), 2),
            ]
            table_row += 1
        data.append([
            Paragraph(_escape(cells[(index, header)]), cell_num if _is_number(row.get(header)) else cell)
            for header in headers
        ])
        style.append(("LINEBELOW", (0, table_row), (-1, table_row), 0.25, theme.HAIRLINE))
        table_row += 1

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(style))
    return table, needs_landscape


# ---------------------------------------------------------------------------
# ChartFigure
# ---------------------------------------------------------------------------


def chart_figure(png_path: Path, available_width: float, *, max_height: float | None = None) -> Flowable | None:
    """The block's PNG, centred, at its correct aspect ratio.

    The image arrives already rendered at 2x with the LIGHT palette (the frontend re-renders for report
    capture regardless of the active theme), so there is nothing to correct here beyond fitting it.
    """
    if not png_path or not Path(png_path).is_file():
        return None
    from PIL import Image as PILImage

    with PILImage.open(png_path) as img:
        iw, ih = img.size
    if not iw or not ih:
        return None
    width = min(available_width, iw * 0.5)  # a 2x capture is half its pixel size in points
    height = width * ih / iw
    if max_height and height > max_height:
        height = max_height
        width = height * iw / ih
    image = Image(str(png_path), width=width, height=height)
    image.hAlign = "CENTER"
    return image


def caption(text: str) -> Paragraph | None:
    """The analysis's own plain-language summary, under its chart or table."""
    if not text:
        return None
    return Paragraph(_escape(text), styles()["caption"])


def table_note(text: str) -> Paragraph | None:
    """The mono line under a table that was cut short ("… 76 more rows — full table available in …").

    Mono and muted, so it reads as machinery rather than as data: it is the document telling you the
    table continues elsewhere, and it must not look like another row.
    """
    if not str(text or "").strip():
        return None
    return Paragraph(_escape(str(text).strip()), styles()["table_note"])


def note_block(text: str) -> Flowable | None:
    """A Report-pane note: the user's own words, so it is set in the body serif and indented in.

    Deliberately NOT in a card. A note is the author speaking; a card is the app reporting. Keeping
    them visually separate is the whole point of letting someone annotate a report.
    """
    if not str(text or "").strip():
        return None
    css = styles()
    bar = Table(
        [[Paragraph(_escape(text).replace("\n", "<br/>"), css["note"])]],
        colWidths=["100%"],
        hAlign="LEFT",
    )
    bar.setStyle(
        TableStyle([
            ("FONT", (0, 0), (-1, -1), theme.SERIF, theme.SIZE_BODY),  # see stat_table
            ("LINEBEFORE", (0, 0), (0, -1), 1.2, theme.BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])
    )
    return bar


# ---------------------------------------------------------------------------
# ResultCard
# ---------------------------------------------------------------------------


def result_card(title: str, meta: str, body: Iterable[Flowable], available_width: float,
                *, keep_together: bool = True) -> Flowable:
    """One analysis block, in a bordered card.

    The card is a Table with ONE ROW PER CONTENT FLOWABLE, not a single cell holding a list. That is
    load-bearing: reportlab splits a table between its ROWS, so a one-row card cannot split at all and
    a card taller than a page raises LayoutError instead of flowing. Row-per-flowable lets it break at
    a sensible boundary, and because reportlab re-applies the style to each fragment the BOX is stroked
    again — which is the "border continues onto the next page" behaviour.

    `splitInRow` additionally lets a single over-tall row (an 80-row inner table) split inside itself,
    so one long table does not have to fit a page either.

    Vertical padding is per-row so the 14pt card padding lands once at the top and once at the bottom
    rather than around every element.

    `KeepTogether` is applied only when the card plausibly fits a page; wrapping a taller-than-a-page
    card in it makes reportlab move the whole thing to a fresh page where it still does not fit.
    """
    inner_width = available_width - 2 * theme.CARD_PADDING
    css = styles()
    rows: list[Flowable] = [Paragraph(_escape(title), css["card_title"])]
    if meta:
        rows.append(Paragraph(_escape(meta), css["card_meta"]))
    rows.append(Hairline(inner_width))
    rows.extend([f for f in body if f is not None])

    data = [[flowable] for flowable in rows]
    last = len(data) - 1
    card = Table(data, colWidths=[available_width], hAlign="LEFT", splitByRow=1, splitInRow=1)
    card.setStyle(
        TableStyle([
            ("FONT", (0, 0), (-1, -1), theme.SERIF, theme.SIZE_BODY),  # see stat_table: keeps Helvetica out
            ("BOX", (0, 0), (-1, -1), theme.CARD_BORDER_WIDTH, theme.BORDER),
            ("ROUNDEDCORNERS", [theme.CARD_RADIUS] * 4),
            ("BACKGROUND", (0, 0), (-1, -1), theme.SURFACE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), theme.CARD_PADDING),
            ("RIGHTPADDING", (0, 0), (-1, -1), theme.CARD_PADDING),
            # the card's own 14pt padding, once at each end; rows in between just breathe
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("TOPPADDING", (0, 0), (0, 0), theme.CARD_PADDING),
            ("BOTTOMPADDING", (0, last), (0, last), theme.CARD_PADDING),
        ])
    )
    if not keep_together:
        return card
    return KeepTogether(card)


def spacer(height: float) -> Spacer:
    return Spacer(1, height)
