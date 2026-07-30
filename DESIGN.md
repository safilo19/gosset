# Design

How Gosset looks and why, for anyone changing it. The visual language is **locked** — this document
exists so that a change either fits it deliberately or is recognised as a departure, rather than drifting
by accident one component at a time.

The single source of truth for every value here is `frontend/style.css`. Where this document and that file
disagree, the file is right and this document is stale.

---

## 1. The register

**A precision instrument, not a dashboard.** Gosset is a tool people do statistical work in for hours. The
interface should read like a well-made measuring device: quiet, dense where density helps, and completely
uninterested in impressing anyone. Nothing decorates. Every visual difference means something.

Three consequences that decide most arguments:

- **The data is the only thing that should attract the eye.** Chrome recedes. If a border, shadow or
  colour is not distinguishing one thing from another, it should not be there.
- **Density is a feature.** A worksheet showing 15 rows is worse than one showing 30. Padding is spent
  where it buys legibility and nowhere else.
- **Nothing moves without a reason.** See §6.

### The ban list

Treat any of these as a regression, not a style choice:

| Banned | Why |
|---|---|
| Dark purple / indigo themes | The 2020s SaaS default. Reads as a startup landing page, not an instrument. |
| Gradients, in backgrounds or text | Nothing in the data is a gradient. |
| Glassmorphism, backdrop blur | Costs legibility over a dense grid and buys nothing. |
| Glow shadows | Shadows communicate elevation. A glow communicates mood. |
| Decorative background animation | See §6. |
| Emoji as icons | They render differently per platform, cannot inherit `currentColor`, and cannot be themed. |
| Marketing copy in the UI | A button says what it does. |

---

## 2. Colour

Two complete themes, light and dark. **Both define every token.** A raw hex value anywhere in
`style.css` outside the two `:root` blocks is a bug, because it will be wrong in one of them.

### Structure

| Token | Light | Dark | Role |
|---|---|---|---|
| `--workspace` | `#edeff2` | `#161616` | The desk. Windows sit on it; it is never content. |
| `--surface` | `#ffffff` | `#262626` | Paper. Windows, panels, cards. |
| `--surface-2` | `#f6f7f9` | `#393939` | Recessed: table headers, inputs, troughs. |
| `--ink` | `#161616` | `#f4f4f4` | Body text and every number. |
| `--muted` | `#6f6f6f` | `#a8a8a8` | Labels, metadata, units — never a value. |
| `--border` | `#d5dae1` | `#4a4a4a` | The frame around a thing. |
| `--border-strong` | `#b9c0ca` | — | Hover on buttons and pickable cards. |
| `--gridline` | `#d5dae1` | `#383838` | Table and worksheet cell edges — deliberately softer than `--border`. |

**Gridlines are softer than frames on purpose.** At full strength a dense grid reads as a cage. The frame
says "this is a table"; the gridlines only need to say "this is a different cell".

### Meaning

| Token | Light | Dark | Means |
|---|---|---|---|
| `--accent` | `#0f62fe` | `#78a9ff` | Interactive, selected, or the primary action. |
| `--success` | `#24a148` | `#42be65` | A result that needs no attention. |
| `--danger` | `#da1e28` | `#fa4d56` | Destructive, or a result that demands attention. |

**The accent differs between themes because it has to.** `#0f62fe` fails contrast on `#161616`. Dark mode
is not light mode with inverted greys; the accent is re-chosen for its background.

**`--on-accent` is the ink for text on a filled accent surface** — white in light, near-black in dark.
Never write `color: #ffffff` next to `background: var(--accent)`.

### Charts

Eight categorical colours, `--chart-1` … `--chart-8`, from IBM Carbon's hues:

```
#0f62fe  #007d79  #d02670  #198038  #ff832b  #1192e8  #a2191f  #6f6f6f
```

Ordered so the first three are distinguishable under the common forms of colour blindness, and
**purple/indigo are deliberately omitted** — partly the ban list, partly because they read as "brand
colour" rather than "series 4".

Read from CSS by `charts/theme.js` at chart-creation time, so a theme switch re-reads them. Never
hard-code a series colour in a renderer.

### Focus

- **Light:** elevation marks the focused window (`--shadow-window-focused`).
- **Dark:** shadows barely read on `#161616`, so the **border** steps up to `--border-strong` instead.

`--focus-ring` is its own token, and keyboard focus is always visible. Never remove an outline without
replacing it with something equally locatable.

---

## 3. Type

| Purpose | Face |
|---|---|
| Interface text | **IBM Plex Sans** (`--font-ui`) |
| Every number, table cell, worksheet cell, and the whole Session Window | **IBM Plex Mono** (`--font-mono`) with `tabular-nums` |

**Numbers are always monospaced, and this is not stylistic.** A column of proportional figures cannot be
compared by eye: the digits do not line up, so `1.001` and `1.010` look the same length. Mono plus
`tabular-nums` makes a column of numbers scannable, which is the entire job of a statistics table.

Reports use a third face — **Source Serif** — for titles and cover blocks only, because a printed document
wants a serif at display size where a screen does not. See §7.

---

## 4. Shape and depth

- **Radius: 4px** (`--radius`), everywhere. One value. Not 6 on cards and 4 on buttons.
- **Borders: 1px.** A thing is delimited by a line, not by a shadow.
- **Shadows communicate elevation and nothing else.** Three defined: `--shadow-window`,
  `--shadow-window-focused`, `--shadow-panel`. Do not invent a fourth to make something "pop".

---

## 5. Components

### Buttons

Say exactly what they do. **"Run regression", never "Submit".** The label is the specification: if a
button needs a tooltip to explain what it does, the label is wrong.

One primary action per dialog, filled with `--accent`. Everything else is outlined.

> **Trap:** `.win-body button` styles *every* button in a window as a `.btn`. A list built from plain
> buttons comes out as a wall of outlined pills. Use two classes (e.g. `.calc-list .calc-list-item`) to
> beat that selector — see `CLAUDE.md` trap 15.

### Dialogs

**Power without clutter.** A field marked `advanced: true` goes into a collapsed `<details>` "Options"
section. That is how a fifteen-setting dialog opens looking like a four-setting one.

Every procedure dialog is generated by `procedureDialog.js` from a declarative registry, so they cannot
drift apart. Layout of a result is always: narrative → tiles → titled tables → graphs → run details.

### Results

Every result renders through one path (`resultView.js`), and every block goes through `block()`, which is
what gives it a chevron menu, keyboard focus and Ctrl+C. A block that bypasses it looks fine and is
silently unexportable.

### Icons

221 inline SVGs in `frontend/icons/registry.js`, keyed by **concept** — one entry serves every item that
means the same thing.

- 16px slot on **every** menu item, empty for a category. The empty slot is what keeps labels in one
  column.
- Stroke with `currentColor` and nothing else. Light/dark, accent-filled hover rows and disabled muting
  then all come for free.
- A missing key renders an **empty slot with no error**. Check additions in **Window → Icon Gallery**.

### Menu help

A card appears only after the pointer **rests** on an item for 600ms, so scanning a menu shows nothing.
Once one has shown, it swaps instantly. It is `pointer-events: none` so it can never be hovered or
clicked. One sentence of *what*, one of *when*; where siblings are confusable, the difference **is** the
description (1-Sample Z vs t, Rank vs Sort).

---

## 6. Motion

**The budget is 120–220ms, and one signature.**

- `--fast: 120ms` for hovers and small state changes.
- The **~500ms numeric count-up** on result tiles is the one expressive motion in the app. It draws the
  eye to the number that matters.
- Everything else is functional: a window opening, a panel expanding.
- All of it is suppressed under `prefers-reduced-motion`.

**Chart draw animation is off and must stay off.** Not a taste decision — Chart.js only interpolates
numbers and colours, and a per-type `animations` object *replaces* the defaults rather than merging, so
non-numeric properties throw from the animation tick and wedge the animator permanently. The visible
symptom is a blank canvas and blank exported PNGs. See `CLAUDE.md` trap 2 before touching
`theme.animation()`.

The progress bar on an update download is exempt: it measures real progress, and a bar that jumps in
steps is harder to read than one that moves.

---

## 7. The report

Exported documents are a **separate design surface** with a different job: a report is read on paper,
by someone who was not in the room.

- **Source Serif** for the cover block and card titles; **IBM Plex Mono** for numerals; IBM Plex Sans for
  body.
- The **G-mark and a t-distribution rule on every page**, with "page X of Y" over an inverted curve.
- One **bordered card per result**, with a coloured **verdict badge**.
- `@media print` re-declares the light tokens: paper is white whatever the screen was.
- Charts are **re-rendered** for export at 2× in the light palette — never screenshotted — so a report
  exported from dark mode still has light figures with print-sized type.

Two rules that are easy to break:

**A verdict badge is computed from numbers, never parsed from prose.** `verdict.py` reads `p_value`,
`r_squared`, `accuracy`, or explicit fields. Conclusions get reworded, and "not statistically significant"
contains the word "significant" — a regex over prose would flip a badge from red to green on a copy edit.

**Polarity is about attention, not good news.** A significant *normality* test is red, because the
assumption failed.

---

## 8. The brand

`frontend/brand/mark.svg` is **one continuous stroke**: a geometric G whose crossbar is a t-distribution,
the right tail running out to meet the bowl. The letter and the curve are the same line.

**It never names a colour.** The asset strokes with `currentColor` only, which is what lets one file serve
the menu bar (inheriting `--ink`), the About window and the loading state (an ancestor sets
`color: var(--accent)`), in both themes, with no JavaScript on a theme switch. Adding a stroke colour to
the asset is what would force a second file.

`logo.svg` adds the wordmark as **live `<text>`**, so it must be **inlined**, never used as `<img src>` —
an `<img>` renders in an isolated context where `currentColor` falls back to black and IBM Plex Sans is
unavailable.

Favicons and the Windows icons are **generated from the mark's geometry**
(`brand/make_favicons.py`, `desktop/scripts/make_app_icons.py`). Edit the path, re-run them.

---

## 9. Two themes, in practice

- The theme is applied by an inline `<script>` in `<head>` **before** the stylesheets, so opening in dark
  never flashes white. It duplicates two literal colours — the only such duplication in the app, because
  there is no CSS to read yet — and `themeMode.apply()` clears them immediately.
- **A Chart.js chart cannot be re-themed with `.update()`.** Axis, grid and tooltip colours are copied
  into the chart's own options at build time, so a theme switch **rebuilds** every open chart
  (`reThemeOpenWindows()`).
- **`Plotly.relayout` replaces any nested object you hand it.** Passing a whole `scene` back wipes
  `scene.camera` and snaps every 3D plot to its default view. `plotly.js` flattens the layout into dotted
  attribute paths so the camera is never mentioned.
- **A destructured theme token snapshots the old theme forever.** `charts/theme.js` exports colours as
  `let` and reassigns on switch; ES live bindings only survive namespace access. Always `theme.ACCENT`,
  never `const { ACCENT } = theme`.
- **`:root[data-theme='light']` cannot be read from any element except `<html>`.** Both token sets are on
  `:root`, so `getComputedStyle` on a `<div data-theme='light'>` returns the *dark* values it inherited.

---

## 10. Checklist for a visual change

1. Does every colour come from a token, and does that token exist in **both** themes?
2. Have you looked at it in light **and** dark?
3. Does it survive `prefers-reduced-motion`?
4. Is keyboard focus still visible?
5. If it added a menu item: does it have an `icon`, a `description` and a `needs`? Does the icon render
   in **Window → Icon Gallery** in both themes?
6. If it added a result block: does it go through `block()`, and does it export?
7. If it touched charts: does an exported PNG still render? (Trap 2 makes this fail silently.)
8. Does it introduce anything on the ban list?
