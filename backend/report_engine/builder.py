"""Assembles the document: page templates, the branded furniture, and the section-to-card mapping.

Page furniture is drawn by one `_furniture()` callback used by BOTH page templates, so the header and
footer are identical in portrait and landscape and there is one place to change them.

Page totals need the count before the first page is written, which is impossible in one pass. reportlab
offers two ways out; this uses the canvasmaker trick — collect each page's state, then write them all
at the end with the total known — because it renders the story ONCE. The alternative (build twice into
a throwaway buffer) doubles the work and, worse, would run every chart image and font subset twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
)

from backend.report_engine import components, theme, verdict as verdict_mod

APP_NAME = "Gosset"


# ---------------------------------------------------------------------------
# what the engine is given
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """One card's worth of content, already reduced to the pieces the engine draws."""

    # A note carries only `note`, so title is optional: a note is the author speaking, not a result.
    title: str = ""
    analysis_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    tables: list[tuple[str, list[dict[str, Any]]]] = field(default_factory=list)
    chart: Path | None = None
    caption: str = ""
    note: str = ""  # set for a Report-pane note; renders outside a card
    columns: str = ""  # the input columns, for the card's metadata line
    timestamp: str = ""


@dataclass
class ReportMeta:
    title: str
    dataset_label: str = ""
    row_count: int | None = None
    column_count: int | None = None
    decimals: int = 3
    version: str = "1.0.0-dev"
    generated_at: datetime = field(default_factory=datetime.now)
    # Whoever prepared the report, when the app knows. The engine stays statistics-free and brand-free
    # about this: it is handed a string and prints it, and an empty string prints nothing at all.
    prepared_by: str = ""

    # Filled in by render_pdf once the note/card split is known, so the cover can say "5 results".
    result_count: int = 0

    @property
    def meta_line(self) -> str:
        """The mono line under the cover title: N results · dataset · shape · generated <datetime>."""
        bits: list[str] = []
        if self.result_count:
            bits.append(f"{self.result_count} result{'s' if self.result_count != 1 else ''}")
        if self.dataset_label:
            bits.append(self.dataset_label)
        if self.row_count is not None and self.column_count is not None:
            bits.append(f"{self.row_count} rows × {self.column_count} columns")
        bits.append(self.generated_at.strftime("generated %d %B %Y at %H:%M"))
        # Last, and only when there is a name: Gosset needs no account, so an unsigned report is the
        # normal case and must not carry a dangling "prepared by".
        if self.prepared_by.strip():
            bits.append(f"prepared by {self.prepared_by.strip()}")
        return "  ·  ".join(bits)


# ---------------------------------------------------------------------------
# page furniture
# ---------------------------------------------------------------------------


def _furniture(canvas, doc) -> None:
    """Header, both t-curve rules and the footer — on EVERY page, portrait or landscape."""
    page_width, page_height = canvas._pagesize
    left = theme.PAGE_MARGIN_X
    right = page_width - theme.PAGE_MARGIN_X
    text_width = right - left
    report_title = getattr(doc, "gosset_title", "")
    version = getattr(doc, "gosset_version", "")

    canvas.saveState()

    # --- header: mark + wordmark left, title right ---
    mark_y = page_height - 14 * mm
    components.draw_mark(canvas, left, mark_y, theme.MARK_SIZE, theme.INK)
    canvas.setFillColor(theme.INK)
    canvas.setFont(theme.SERIF_BOLD, 13)
    canvas.drawString(left + theme.MARK_SIZE + 3 * mm, mark_y + 1.6 * mm, APP_NAME)

    if report_title:
        canvas.setFont(theme.MONO, theme.SIZE_META)
        canvas.setFillColor(theme.MUTED)
        canvas.drawRightString(right, mark_y + 2.2 * mm, _fit(report_title, theme.MONO, theme.SIZE_META, text_width * 0.55))

    # --- THE SIGNATURE: the t-curve rule under the header ---
    theme.draw_t_curve(canvas, left, page_height - theme.HEADER_HEIGHT, text_width, theme.CURVE_PEAK, color=theme.INK)

    # --- footer: the same curve inverted, with the two lines above it ---
    footer_baseline = 12 * mm
    # 6.5mm of lift, not 4.5: the curve DIPS towards the text by CURVE_PEAK at its centre, so the
    # clearance to the footer text's ascenders is (lift - peak), and at 4.5 that arithmetic came out
    # negative. It happened not to collide only because the credit line and the page number sit at the
    # two margins while the dip is in the middle — which is luck, not clearance.
    theme.draw_t_curve(canvas, left, footer_baseline + 6.5 * mm, text_width, theme.CURVE_PEAK, invert=True, color=theme.INK)
    canvas.setFont(theme.MONO, theme.SIZE_FOOTER)
    canvas.setFillColor(theme.MUTED)
    canvas.drawString(left, footer_baseline, f"Generated with {APP_NAME} v{version}")
    # "page X of Y" is NOT drawn here. onPage runs during the first pass, when the total is still
    # unknown — drawing it now would emit "1" into the content stream and no amount of replaying state
    # afterwards would change it. _TotallingCanvas stamps it in the second pass instead.

    canvas.restoreState()


def _fit(text: str, font: str, size: float, max_width: float) -> str:
    """Trim with an ellipsis so a long title never collides with the wordmark."""
    from reportlab.pdfbase import pdfmetrics

    if pdfmetrics.stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and pdfmetrics.stringWidth(trimmed + ellipsis, font, size) > max_width:
        trimmed = trimmed[:-1]
    return trimmed + ellipsis


class _TotallingCanvas(pdfcanvas.Canvas):
    """Defers writing pages until the total is known, so the footer can say "3 of 7".

    Each showPage() stashes the page's state instead of emitting it; save() then replays them all with
    `gosset_total_pages` set. This is reportlab's documented approach and it renders the story once.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 - reportlab's API
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def _stamp_page_number(self, index: int, total: int) -> None:
        """Draw "3 of 7" bottom-right, in the second pass, onto the page being replayed."""
        page_width = self._pagesize[0]
        self.saveState()
        self.setFont(theme.MONO, theme.SIZE_FOOTER)
        self.setFillColor(theme.MUTED)
        self.drawRightString(page_width - theme.PAGE_MARGIN_X, 12 * mm, f"{index} of {total}")
        self.restoreState()

    def save(self) -> None:
        total = len(self._saved_pages)
        for index, state in enumerate(self._saved_pages, start=1):
            self.__dict__.update(state)
            # The replayed state restores this page's content; appending to it now is what lets the
            # footer know the total. `_pagesize` comes back with the state, so a landscape page stamps
            # in the right place.
            self._stamp_page_number(index, total)
            super().showPage()
        super().save()


def _templates(doc: BaseDocTemplate) -> list[PageTemplate]:
    """A portrait and a landscape template sharing one furniture callback."""
    made = []
    for name, size in (("portrait", LETTER), ("landscape", landscape(LETTER))):
        width, height = size
        frame = Frame(
            theme.PAGE_MARGIN_X,
            theme.FOOTER_HEIGHT,
            width - 2 * theme.PAGE_MARGIN_X,
            height - theme.HEADER_HEIGHT - theme.FOOTER_HEIGHT - 4 * mm,
            id=name,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        made.append(PageTemplate(id=name, frames=[frame], onPage=_furniture, pagesize=size))
    return made


# ---------------------------------------------------------------------------
# sections -> flowables
# ---------------------------------------------------------------------------


def _card_meta(section: Section) -> str:
    bits = [b for b in (section.timestamp, section.columns) if b]
    return "  ·  ".join(bits)


def _section_flowables(section: Section, meta: ReportMeta, width: float, formatter: Callable) -> tuple[list[Flowable], bool]:
    """The body of one card, and whether it needs a landscape page."""
    body: list[Flowable] = []
    needs_landscape = False

    fields = verdict_mod.derive(section.data, section.analysis_id)
    if fields:
        body.append(components.verdict_badge(fields["verdict_label"], fields["verdict_polarity"], fields["key_stat"]))
        body.append(components.spacer(7))

    inner = width - 2 * theme.CARD_PADDING
    for entry in section.tables:
        # (label, rows) or (label, rows, truncation note) — the note is optional so a caller that
        # builds two-element pairs still works.
        table_title, rows = entry[0], entry[1]
        row_note = entry[2] if len(entry) > 2 else ""
        if table_title:
            body.append(Paragraph(components._escape(table_title).upper(), components.styles()["group_label"]))
            body.append(components.spacer(3))
        table, landscape_needed = components.stat_table(rows, inner, meta.decimals, formatter)
        needs_landscape = needs_landscape or landscape_needed
        body.append(table)
        cut = components.table_note(row_note)
        if cut is not None:
            body.append(components.spacer(2))
            body.append(cut)
        body.append(components.spacer(6))

    figure = components.chart_figure(section.chart, inner) if section.chart else None
    if figure is not None:
        body.append(figure)

    cap = components.caption(section.caption)
    if cap is not None:
        body.append(cap)

    return body, needs_landscape


def build_story(sections: Iterable[Section], meta: ReportMeta, formatter: Callable, width: float) -> list[Flowable]:
    """The whole document as a flat list of flowables, cover block included.

    Landscape is handled by bracketing the card with NextPageTemplate: switch, break, draw the card,
    switch back, break. A wide table therefore gets a whole sideways page to itself and the reader is
    never asked to guess at a truncated column.
    """
    css = components.styles()
    story: list[Flowable] = []

    # --- cover block: on the first page, above the first card, not a page of its own ---
    story.append(Paragraph(components._escape(meta.title), css["cover_title"]))
    story.append(Paragraph(components._escape(meta.meta_line), css["cover_meta"]))
    story.append(components.spacer(14 * mm))

    section_list = list(sections)
    for index, section in enumerate(section_list):
        if section.note:
            note = components.note_block(section.note)
            if note is not None:
                story.append(note)
                story.append(components.spacer(9))
            continue

        body, needs_landscape = _section_flowables(section, meta, width, formatter)
        card_meta = _card_meta(section)

        if needs_landscape:
            story.append(NextPageTemplate("landscape"))
            story.append(PageBreak())
            wide = landscape(LETTER)[0] - 2 * theme.PAGE_MARGIN_X
            body, _ = _section_flowables(section, meta, wide, formatter)
            story.append(components.result_card(section.title, card_meta, body, wide, keep_together=False))
            story.append(NextPageTemplate("portrait"))
            story.append(PageBreak())
            continue

        # KeepTogether only when the card plausibly fits a page: wrapping a taller-than-a-page card in
        # it makes reportlab move it to a fresh page where it still does not fit, and the split it then
        # performs is the ugly kind.
        story.append(components.result_card(section.title, card_meta, body, width, keep_together=True))
        if index != len(section_list) - 1:
            story.append(components.spacer(9))

    return story



# ---------------------------------------------------------------------------
# the entry point
# ---------------------------------------------------------------------------


def render_pdf(dest: Path, sections: Iterable[Section], meta: ReportMeta, formatter: Callable) -> Path:
    """Write the branded PDF. Raises ReportFontError if the bundled fonts are not present."""
    theme.ensure_fonts()
    section_list = list(sections)
    described = len([s for s in section_list if not s.note])
    meta.result_count = described
    doc = BaseDocTemplate(
        str(dest),
        pagesize=LETTER,
        leftMargin=theme.PAGE_MARGIN_X,
        rightMargin=theme.PAGE_MARGIN_X,
        topMargin=theme.HEADER_HEIGHT,
        bottomMargin=theme.FOOTER_HEIGHT,
        title=meta.title,
        author=APP_NAME,
        subject=f"{described} analysis result(s)",
        creator=f"{APP_NAME} v{meta.version}",
    )
    doc.gosset_title = meta.title
    doc.gosset_version = meta.version
    # Every page's content stream opens with a preamble that SETS A FONT. reportlab's default for that
    # is Helvetica, which forces a /BaseFont /Helvetica declaration into the resources of every page
    # even though no glyph is ever drawn in it — and the brief is no Helvetica anywhere. This is the
    # supported knob (BaseDocTemplate passes it straight to the canvas), so the preamble references one
    # of the bundled faces instead.
    doc.initialFontName = theme.MONO
    doc.initialFontSize = theme.SIZE_BODY
    doc.addPageTemplates(_templates(doc))

    width = LETTER[0] - 2 * theme.PAGE_MARGIN_X
    story = build_story(section_list, meta, formatter, width)
    doc.build(story, canvasmaker=_TotallingCanvas)
    return dest
