"""Generate the Windows icons for the installed app, FROM mark.svg's geometry.

Two icons, both derived rather than drawn:

  build/icon.ico      the application: the G-mark, as the window icon, the taskbar button, the
                      Start Menu entry and the desktop shortcut
  build/gsp.ico       the .gsp document: the same mark on a page glyph, so a project file reads as
                      "a Gosset document" in Explorer and not as a second copy of the app

frontend/brand/make_favicons.py is imported for its outline() rather than re-deriving the path: it
already owns the cubic-and-arc arithmetic that turns mark.svg's single path into points, and the whole
point of that arrangement is that mark.svg stays the one vector source of truth. A third copy of those
numbers would be a third thing to forget to update.

Sizes: 16/24/32/48/64/128/256. Explorer picks per view, and a missing 256 is why an app looks crisp in
the taskbar and blurry on the desktop — Windows upscales the largest it finds.

Run: python desktop/scripts/make_app_icons.py   (or `npm run icons` in desktop/)
"""

from __future__ import annotations

import importlib.util
import io

import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BRAND_DIR = REPO_ROOT / "frontend" / "brand"
BUILD_DIR = REPO_ROOT / "desktop" / "build"

SIZES = [16, 24, 32, 48, 64, 128, 256]

# The brand's own tokens. The app icon is the accent blue used on a light surface, because a taskbar
# icon sits on whatever colour the user's theme is and the accent is the one colour that reads on both.
ACCENT = (15, 98, 254)       # --accent, light
INK = (22, 22, 22)           # --ink
PAPER = (255, 255, 255)      # --surface, light
PAGE_EDGE = (185, 192, 202)  # a hair darker than --border, so the page has an outline at 16px

# Per-size stroke weight, in mark.svg's own units. The same optical correction make_favicons.py
# applies: a 2-unit stroke is barely 1px at 16px output, which greys the mark out, so the small sizes
# are drawn heavier. The geometry is never touched — only the pen.
STROKE_UNITS = {16: 3.0, 24: 2.7, 32: 2.4, 48: 2.2, 64: 2.1, 128: 2.0, 256: 2.0}

# The mark is stroked by MATPLOTLIB, not by PIL.
#
# PIL was the first attempt and it cannot do this. ImageDraw has no antialiased line, so the mark has
# to be supersampled and downscaled; and its wide-stroke path (`draw.line(joint="curve")`) builds the
# stroke from one ellipse per vertex. The bowl is a 360-vertex arc, so at any stroke wide enough to
# matter those ellipses stop overlapping cleanly and the arc renders as a hatched ribbon. Supersampling
# does not fix it — it moves it: at an 8x downscale the artefacts average away, at 4x they survive, so
# the 128px frame came out clean and the 256px frame came out visibly furry, from the same code.
#
# matplotlib draws a real stroked path with round caps and joins and proper antialiasing, which is
# exactly what mark.svg specifies, at any size, with no supersampling. It is already a dependency, and
# it is already how the favicons are generated — so this now matches them by construction.
def _render_mark(size_px: int, stroke_units: float, *, color: str = "#0f62fe",
                 span_units: float = 32.0, inset_units: float = 0.0) -> Image.Image:
    """The mark alone as a transparent RGBA image, `size_px` square.

    `span_units` / `inset_units` place the 32-unit viewBox inside the output box, so the document icon
    can draw the same mark smaller and offset without a second renderer.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs, ys = _outline()
    dpi = 100
    fig = plt.figure(figsize=(size_px / dpi, size_px / dpi), dpi=dpi)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.patch.set_alpha(0.0)
    # The viewBox, expanded by the inset so the drawing occupies `span_units` of a wider frame.
    lo = -inset_units
    hi = span_units + inset_units
    ax.set_xlim(lo, hi)
    ax.set_ylim(hi, lo)  # y down, matching the SVG viewBox
    # linewidth is in points: units -> px is size/(hi-lo), px -> pt is 72/dpi.
    lw = stroke_units * (size_px / (hi - lo)) * (72 / dpi)
    ax.plot(xs, ys, color=color, linewidth=lw, solid_capstyle="round",
            solid_joinstyle="round", antialiased=True)

    buf = io.BytesIO()
    fig.savefig(buf, dpi=dpi, transparent=True, format="png")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


def _outline() -> tuple[list[float], list[float]]:
    """mark.svg's path as (xs, ys) in its 32x32 viewBox, via make_favicons.outline()."""
    script = BRAND_DIR / "make_favicons.py"
    if not script.is_file():
        raise FileNotFoundError(f"The mark geometry script is missing: {script}")
    spec = importlib.util.spec_from_file_location("gosset_mark_geometry", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.outline()


def app_icon(size: int, xs=None, ys=None) -> Image.Image:
    """The mark alone, accent-coloured, on transparency."""
    # ~1.2 units of breathing room so the round cap cannot touch the edge of the frame.
    return _render_mark(size, STROKE_UNITS[size], inset_units=1.2)


def document_icon(size: int, xs=None, ys=None) -> Image.Image:
    """The mark on a page with a folded corner — Explorer's convention for "a document of this app".

    The page is flat geometry (straight edges, one triangle) so PIL draws it perfectly well; only the
    MARK needs a real stroked path, and that is composited in from _render_mark. Supersampling the page
    by 4x and downscaling is what keeps the fold's diagonal from stairstepping.
    """
    ss = 4 if size <= 64 else 2
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # A page is taller than it is wide, centred, with room for the fold.
    margin_x = big * 0.17
    margin_y = big * 0.07
    left, right = margin_x, big - margin_x
    top, bottom = margin_y, big - margin_y
    fold = (right - left) * 0.34

    edge = max(1, int(round(big * 0.012)))

    # The page, with the top-right corner cut off.
    draw.polygon(
        [(left, top), (right - fold, top), (right, top + fold), (right, bottom), (left, bottom)],
        fill=(*PAPER, 255), outline=(*PAGE_EDGE, 255), width=edge,
    )
    # The fold itself, drawn as a slightly grey triangle so it reads as turned-over paper.
    draw.polygon(
        [(right - fold, top), (right, top + fold), (right - fold, top + fold)],
        fill=(228, 232, 238, 255), outline=(*PAGE_EDGE, 255), width=edge,
    )

    page = img.resize((size, size), Image.LANCZOS)

    # The mark, sized to the page's width and sitting on its lower two-thirds — below the fold, so the
    # two never collide. Rendered at its own size and composited, rather than drawn into the page.
    mark_px = max(8, int(round(size * 0.46)))
    # Heavier at small sizes for the same reason the app icon is, and a little heavier again: a mark
    # inside a white page has less room to read than one on its own.
    stroke = STROKE_UNITS.get(size, 2.0) * 1.15
    mark = _render_mark(mark_px, stroke, inset_units=1.0)

    x = int(round((size - mark_px) / 2))
    y = int(round(size * 0.40))
    page.alpha_composite(mark, (x, y))
    return page


def write_ico(path: Path, frames: list[Image.Image]) -> None:
    """One .ico carrying every size.

    Pillow's save(sizes=...) DOWNSCALES a single image, which would put a 256px drawing into a 16px
    frame and lose the geometry to mush. Each frame here is drawn at its own size — the 16px document
    icon needs a heavier stroke and a simpler page than the 256px one to read at all — so they are
    appended explicitly instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    largest, *rest = sorted(frames, key=lambda im: im.width, reverse=True)
    largest.save(path, format="ICO", sizes=[(f.width, f.height) for f in frames],
                 append_images=rest)


def main() -> int:
    xs, ys = _outline()
    if not xs:
        print("outline() returned no points — check frontend/brand/make_favicons.py", file=sys.stderr)
        return 1

    write_ico(BUILD_DIR / "icon.ico", [app_icon(s) for s in SIZES])
    write_ico(BUILD_DIR / "gsp.ico", [document_icon(s) for s in SIZES])

    # A PNG for the Linux/dev window icon and for the README, at the one size both want.
    app_icon(256).save(BUILD_DIR / "icon.png")

    for name in ("icon.ico", "gsp.ico", "icon.png"):
        print(f"  {name:10} {(BUILD_DIR / name).stat().st_size:>7,} bytes")
    print(f"\nwrote {BUILD_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
