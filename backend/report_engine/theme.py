"""Every constant the report engine draws with, plus the t-curve that is the report's fingerprint.

Nothing in this module renders a document. It owns the fonts, the palette, the metrics and the two
geometry functions, so `components.py` and `builder.py` never hard-code a colour or a size and the
whole look can be retuned from one file.

The palette is the app's own design tokens (the light set — paper is white whatever the screen is),
so a printed report and the screen are recognisably the same product.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

HERE = Path(__file__).parent
FONT_DIR = HERE / "fonts"

# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------

# Registered name -> file. The names are what every style in this engine asks for; if one is missing
# reportlab would silently substitute Helvetica and the report would look like a different product,
# so ensure_fonts() refuses to continue instead.
FONT_FILES: dict[str, str] = {
    "GossetSerif": "SourceSerif4-Regular.ttf",
    "GossetSerif-SemiBold": "SourceSerif4-Semibold.ttf",
    "GossetSans": "IBMPlexSans-Regular.ttf",
    "GossetSans-Medium": "IBMPlexSans-Medium.ttf",
    "GossetMono": "IBMPlexMono-Regular.ttf",
}

SERIF = "GossetSerif"
SERIF_BOLD = "GossetSerif-SemiBold"
SANS = "GossetSans"
SANS_MEDIUM = "GossetSans-Medium"
MONO = "GossetMono"

_registered = False


class ReportFontError(RuntimeError):
    """A bundled font is missing or unreadable."""


def ensure_fonts() -> None:
    """Register the five bundled faces with reportlab. Loud on failure, by design.

    reportlab's behaviour when a font name is unknown is to fall back to Helvetica WITHOUT a warning.
    That is the worst possible outcome here: the report renders, looks subtly wrong, and nobody knows
    why. So a missing file is a hard error naming the file and the fix.
    """
    global _registered
    if _registered:
        return
    missing = [name for name, filename in FONT_FILES.items() if not (FONT_DIR / filename).is_file()]
    if missing:
        wanted = ", ".join(FONT_FILES[name] for name in missing)
        raise ReportFontError(
            f"The report engine's bundled fonts are missing: {wanted}. "
            f"They belong in {FONT_DIR}. Run `python backend/report_engine/fonts/fetch_fonts.py` to "
            "download them from their official OFL sources. Refusing to render with Helvetica "
            "substitutes, which would silently change the look of every report."
        )
    for name, filename in FONT_FILES.items():
        try:
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))
        except Exception as exc:  # noqa: BLE001 - re-raise with the file that actually failed
            raise ReportFontError(f"Could not register {filename} as '{name}': {exc}") from exc
    # Register the serif as its own family so <b> inside a Paragraph reaches the SemiBold face rather
    # than reportlab synthesising a smeared fake bold.
    pdfmetrics.registerFontFamily(SERIF, normal=SERIF, bold=SERIF_BOLD, italic=SERIF, boldItalic=SERIF_BOLD)
    pdfmetrics.registerFontFamily(SANS, normal=SANS, bold=SANS_MEDIUM, italic=SANS, boldItalic=SANS_MEDIUM)
    pdfmetrics.registerFontFamily(MONO, normal=MONO, bold=MONO, italic=MONO, boldItalic=MONO)

    # reportlab's VECTOR GRAPHICS renderer seeds its state from shapes.STATE_DEFAULTS, whose fontName
    # is Times-Roman — and it declares that font in the page's resources the moment a Drawing is
    # rendered, even one containing no text at all. Drawing the logo therefore put /Times-Roman on
    # every page. Nothing in this engine ever puts text inside a Drawing, so pointing the default at a
    # bundled face is safe and keeps a font audit showing only the five faces actually used.
    from reportlab.graphics import shapes as _shapes

    _shapes.STATE_DEFAULTS["fontName"] = MONO

    _registered = True


def font_report() -> list[tuple[str, str, int]]:
    """(registered name, file, bytes) for each bundled face — used by the verification test."""
    return [(name, filename, (FONT_DIR / filename).stat().st_size) for name, filename in FONT_FILES.items()]


# ---------------------------------------------------------------------------
# palette — the app's light tokens
# ---------------------------------------------------------------------------

INK = colors.HexColor("#161616")
MUTED = colors.HexColor("#6F6F6F")
ACCENT = colors.HexColor("#0F62FE")
SUCCESS = colors.HexColor("#24A148")
DANGER = colors.HexColor("#DA1E28")
BORDER = colors.HexColor("#DDDDDD")
HAIRLINE = colors.HexColor("#E5E8EC")
HEADER_BG = colors.HexColor("#F0F3F8")
ROW_ALT_BG = colors.HexColor("#FAFBFC")
SURFACE = colors.white

# Captions and secondary prose sit at 80% ink rather than at --muted: muted is for metadata, and a
# sentence someone is meant to READ needs more contrast than a timestamp does.
INK_80 = colors.HexColor("#454545")

# ---------------------------------------------------------------------------
# page metrics
# ---------------------------------------------------------------------------

PAGE_MARGIN_X = 18 * mm
HEADER_HEIGHT = 22 * mm  # from the top edge down to the top of the text frame
FOOTER_HEIGHT = 18 * mm

MARK_SIZE = 7 * mm  # the logo in the header
CARD_PADDING = 14  # points, per the spec
CARD_RADIUS = 6
CARD_BORDER_WIDTH = 0.75
RULE_WIDTH = 0.6  # the t-curve rule

# Type sizes, in points.
SIZE_COVER_TITLE = 25
SIZE_CARD_TITLE = 13.5
SIZE_BODY = 9.5
SIZE_CAPTION = 8.5
SIZE_META = 7.5
SIZE_FOOTER = 7
SIZE_TABLE = 8.5
SIZE_TABLE_SMALL = 7.5  # the one step down a wide table takes before going landscape
SIZE_GROUP_LABEL = 7

LEADING_RATIO = 1.35

# ---------------------------------------------------------------------------
# THE SIGNATURE: the t-curve rule
# ---------------------------------------------------------------------------


# The shape of the rule, as three numbers so it can be retuned in one place.
#
# CURVE_SPAN is the one that matters and the one that was wrong. It says how far into the tails the
# rule travels, and therefore how much of the rule's width the bell occupies. The rule is ~180mm wide
# and ~3mm tall — 55:1 — so a bell stretched across all of it cannot read as a distribution at any
# peak height. At span 3.4 it read as a line that had sagged in the middle, which is exactly what a
# reader called it. At span 14 the tails run out visibly FLAT, and the flat is what gives the peak
# something to be a peak against: a straight rule with a distribution sitting in it, deliberately.
#
# CURVE_DF stays at Student's t rather than a Gaussian for the sake of the shoulders, though honesty
# demands the note that at 0.6pt and this size the two are near indistinguishable — rendered side by
# side, the difference only shows above about 3x. It is the right curve for the product's namesake and
# it costs nothing; it is not a difference a reader will see.
CURVE_DF = 2.2
CURVE_SPAN = 14.0
CURVE_PEAK = 3.2 * mm


def t_curve_points(width: float, peak: float, samples: int = 200, invert: bool = False,
                   half_span: float = CURVE_SPAN, df: float = CURVE_DF) -> list[tuple[float, float]]:
    """The brand's t-distribution as a polyline, from (0, 0) to (width, 0).

    The report's fingerprint, and the ONE definition of the curve: the page furniture strokes it as a
    vector, and `components.curve_png` rasterises this same function for Word and PowerPoint, so the two
    cannot drift. The density is evaluated directly rather than approximated with a bezier —

        f(x) = (1 + x^2 / v) ^ -((v + 1) / 2)        (the t kernel, unnormalised)

    — which is what makes `half_span` a meaningful dial: it is a real distance in x, so widening it
    genuinely walks further into the tails instead of just squashing a picture.

    The mark's crossbar is the same *idea* but not this function: `brand/mark.svg` fits its bell with
    two cubics to sit inside a 32-unit G at roughly 2.4:1. A rule 55 times wider than it is tall cannot
    use those proportions, so the two are drawn to suit their own sizes and are not interchangeable.

    Returns points in PDF user space with y measured UP from the baseline, so a caller draws it at
    whatever y it likes. `invert` flips it for the footer rule, which is the same curve upside down.

    `samples` is spread over the WHOLE width while the bell occupies only its middle sixth, so the apex
    gets a small fraction of them. Magnified 6x, 96 samples is already smooth — round line joins do the
    rest at 0.6pt — so the default is not chasing a visible defect; 200 is margin for the 300dpi raster
    in `components.curve_png` and costs about 1.5kB per rule.
    """
    if samples < 8:
        samples = 8
    points: list[tuple[float, float]] = []
    for i in range(samples + 1):
        t = i / samples
        x = (t * 2 - 1) * half_span
        density = (1.0 + (x * x) / df) ** (-(df + 1) / 2)
        y = density * peak
        points.append((t * width, -y if invert else y))
    return points


def draw_t_curve(canvas, x: float, y: float, width: float, peak: float, *, invert: bool = False,
                 color=INK, line_width: float = RULE_WIDTH) -> None:
    """Stroke the t-curve rule with its baseline at (x, y).

    Drawn as one path so the join between segments is continuous; at 0.6pt a polyline of ~96 segments
    is indistinguishable from a curve and needs no control-point fitting.
    """
    canvas.saveState()
    canvas.setStrokeColor(color)
    canvas.setLineWidth(line_width)
    canvas.setLineCap(1)
    canvas.setLineJoin(1)
    path = canvas.beginPath()
    points = t_curve_points(width, peak, invert=invert)
    path.moveTo(x + points[0][0], y + points[0][1])
    for px, py in points[1:]:
        path.lineTo(x + px, y + py)
    canvas.drawPath(path, stroke=1, fill=0)
    canvas.restoreState()


