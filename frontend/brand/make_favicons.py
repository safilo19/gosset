"""Generate the favicon PNGs and the .ico from mark.svg's path data.

Run from the repo root:  python frontend/brand/make_favicons.py

Why a script and not exported blobs: the favicons are DERIVED from the mark, and the only way to keep
them from drifting after the mark is edited is to regenerate them from the same numbers. PATH below
is the same geometry as mark.svg — if you change one, change both and re-run this.

Rendering goes through matplotlib (already a dependency of the chart code) rather than a browser or
an SVG rasteriser, so this works offline and identically on any machine.
"""

from __future__ import annotations

import math
from pathlib import Path as FsPath

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

OUT = FsPath(__file__).parent
ACCENT = "#0f62fe"  # --accent (light). The favicon is the one place the accent is baked in: a
# browser tab has no theme to inherit from, so currentColor has nothing to resolve against.

# ---------------------------------------------------------------------------
# the mark, as mark.svg draws it (viewBox 0 0 32 32, y down)
# ---------------------------------------------------------------------------

BAR_Y, PEAK_Y = 17.4, 12.0
LEFT_X, PEAK_X = 8.4, 14.9
CX, CY, R = 16.0, 16.0, 11.5
BELL_END = 21.4
BAR_RIGHT = 27.41
TERM = (23.7, 7.45)

# cubic control points, matching mark.svg exactly
RISE = ((LEFT_X, BAR_Y), (11.26, BAR_Y), (11.52, PEAK_Y), (PEAK_X, PEAK_Y))
FALL = ((PEAK_X, PEAK_Y), (18.28, PEAK_Y), (18.54, BAR_Y), (BELL_END, BAR_Y))

# Per-size stroke weight. A 2-unit stroke is only 1px at 16px output, which greys the mark out, so the
# small sizes are drawn heavier. A normal optical correction — the geometry is untouched.
STROKE_UNITS = {16: 2.9, 32: 2.3, 48: 2.1}
SIZES = (16, 32, 48)


def cubic(p0, p1, p2, p3, steps: int):
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        yield (
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        )


def bowl(steps: int):
    """The A11.5 11.5 0 1 1 arc: from the bar's right end round to the top-right terminal.

    large-arc-flag=1 and sweep-flag=1 means the positive-angle direction (clockwise on screen, since
    y points down) taking the long way round — bottom, left, top — which is 305 degrees, not the 55
    the short way. Getting this backwards draws the aperture on the wrong side.
    """
    start = math.degrees(math.atan2(BAR_Y - CY, BAR_RIGHT - CX))
    end = math.degrees(math.atan2(TERM[1] - CY, TERM[0] - CX))
    while end <= start:
        end += 360
    for i in range(steps + 1):
        a = math.radians(start + (end - start) * i / steps)
        yield (CX + R * math.cos(a), CY + R * math.sin(a))


def outline() -> tuple[list[float], list[float]]:
    pts = list(cubic(*RISE, steps=48))
    pts += list(cubic(*FALL, steps=48))[1:]
    pts.append((BAR_RIGHT, BAR_Y))
    pts += list(bowl(steps=360))[1:]
    return [p[0] for p in pts], [p[1] for p in pts]


def render(size: int) -> FsPath:
    dpi = 100
    xs, ys = outline()
    fig = plt.figure(figsize=(size / dpi, size / dpi), dpi=dpi)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.patch.set_alpha(0.0)
    ax.set_xlim(0, 32)
    ax.set_ylim(32, 0)  # y down, matching the SVG viewBox
    # linewidth is in points: units -> px is size/32, px -> pt is 72/dpi
    lw = STROKE_UNITS[size] * (size / 32) * (72 / dpi)
    ax.plot(xs, ys, color=ACCENT, linewidth=lw, solid_capstyle="round", solid_joinstyle="round", antialiased=True)
    dest = OUT / f"favicon-{size}.png"
    fig.savefig(dest, dpi=dpi, transparent=True)
    plt.close(fig)
    return dest


def main() -> None:
    paths = [render(s) for s in SIZES]
    for p, s in zip(paths, SIZES):
        img = Image.open(p)
        assert img.size == (s, s), f"{p.name} came out {img.size}, expected {(s, s)}"
        assert img.mode == "RGBA", f"{p.name} has no alpha channel (mode {img.mode})"
    # One multi-resolution .ico, which is what a browser and a Windows shortcut both prefer.
    Image.open(OUT / "favicon-48.png").save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("wrote " + ", ".join(p.name for p in paths) + ", favicon.ico")


if __name__ == "__main__":
    main()
