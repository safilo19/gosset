---
name: project-conventions
description: Conventions for adding to this Minitab-equivalent analytics app — menu items and their required registry icon, procedures, dialogs, theming. Use when adding or editing any menu item, Stat/Calc/Data/Graph procedure, or frontend icon.
---

# Project conventions

`CLAUDE.md` at the repo root is the architecture; this is the checklist for the things that are easy
to leave half-done. Read the area's memory note as well (paths in `CLAUDE.md`).

## Adding menu items

**One rule, three fields: every new leaf menu item ships with `icon`, `description`, and `needs`
where it has real input requirements.** All three live on the same config entry, so one entry fully
describes a menu item — the icon in the 16px slot, the description and Needs line in the hover help
card (`menuHelp.js`). An item missing any of them is unfinished: the icon column reads as broken and
the card either says nothing or says half of it.

### 1. The icon

Add it to `frontend/icons/registry.js`, in the group for its menu, following the style rules in the
comment block at the top of that file. Read them before drawing. The short version: 16×16 viewBox,
stroke-based, stroke-width 1.5, `stroke="currentColor"` and never a colour literal, a miniature of
the concept rather than an abstract glyph, and built from the family base its siblings use (`CURVE`,
`FIT`, `CAL`, `SHEET`, `BRACKETS`, `HIST`, `AXES`, `SIGMOID`, `SPREAD`) so the family still reads as
a family. Two tools that differ only in sample count differ only by a `1`/`2` badge.

Where two menu items are genuinely the same concept in different submenus (GLM > Predict and
Mixed > Predict; a distribution under Random Data and under Probability Distributions), **share one
icon**. Distinctness only has to hold within a single flyout, which is the only place an eye
compares them.

### 2. The description

One sentence of WHAT it does, plus one of WHEN to reach for it if that is not obvious from the
label. Style:

- Plain language, and **no second person** — "Tints the cells above a given number", not "the number
  you give". Name the input instead of addressing the reader.
- Concrete, never promotional. "Tests whether the means of two independent groups differ", not
  "a powerful tool for comparing groups". No *powerful*, *simply*, *intuitive*, *seamless*.
- **Where siblings are easy to confuse, stating the DIFFERENCE is the description's main job.** That
  is the whole reason the field exists. 1-Sample Z vs 1-Sample t is about whether sigma is known;
  Rank vs Sort is labelling values vs moving rows; Balanced ANOVA vs GLM is whether the cell counts
  are equal; Tukey vs Fisher vs Dunnett vs Games-Howell is the comparison family and the variance
  assumption. Read the neighbour's description before writing a new one.
- Name the method only where it helps choose between similar tools ("Uses Welch's approximation by
  default; a pooled option is in Options"). Not as decoration.

### 3. The `needs` line

The data requirements, shown muted under the description — the most useful line on the card for
someone learning the tool. Be specific about counts and types: *"One numeric column and one grouping
column with 2 levels."* Omit it only when the item genuinely has no data prerequisite (New
Worksheet, Set Base, Cascade windows). An item that is greyed out until something else has been done
needs no `needs`: `menuHelp.js` promotes the item's `title` into that slot, which is why the disabled
GLM items explain themselves without any extra text.

### Where the fields go

A hand-written menu entry carries all three inline. A generated one (the distribution submenus,
File > Recent) has its generator set them. A **procedure registry** — `dataMenuConfig.js`,
`calcConfig.js`, `anovaConfig.js`, `basicStatsConfig.js`, `charts/graphConfig.js`,
`conditionalFormat.js`'s `RULE_KINDS` — declares them on the PROCEDURE and its menu builder forwards
them, because the procedure owns its own identity. If you add a new group helper to one of those
files, forward `description` and `needs` alongside `icon` or the card silently goes blank.

The static File / Edit / Window menus in `index.html` use `data-icon` / `data-help` / `data-needs`
attributes instead, hydrated by `menus.hydrateIcons()`.

**Parents and categories get none of the three.** A submenu host ("Merge Worksheets ▸", "Basic
Statistics", "General Linear Model") renders the slot empty on purpose — the `▸` is what says it
opens something, and an icon there competes with its children's. `menu.js` never reads `icon` on an
entry that has `items`, and `menuHelp.js` refuses to show a card for a submenu parent, because the
flyout wants exactly the space the card would take.

### Checking it

Open **Window > Icon Gallery** (or the `#icons` hash) in **both themes**. It flags hardcoded
colours, wrong viewBox and wrong stroke-width automatically, and shows the whole set in a grid so a
style outlier is obvious. Turn on **Show descriptions** and it becomes the content-review page: every
icon with the label, description and Needs line of each menu item that uses it, which is the only
practical way to read the set for tone in one pass. Then hover the real item in the real menu.

## Adding an analysis output block

**Every output block MUST be built through `block()` in `resultView.js`.** That wrapper is the only
thing that gives a block its chevron action menu — Send to Word / PowerPoint / Report, Copy, Copy as
Picture, Print, Delete — plus keyboard focus, Enter-to-open and Ctrl+C. A new output that appends a
bare `<div>` to the container gets none of it, silently, and looks finished until someone reaches for
the menu.

Use the existing builders where they fit — `buildTableBlock()`, `buildStatGrid()`, `buildTextBlock()`
and `drawGraph()` already wrap themselves. Only call `block()` directly for a genuinely new shape:

```js
container.appendChild(block({ kind: 'table', name: 'Variance components', rows }, myMarkup));
```

- **`kind`** is `'text' | 'tiles' | 'table' | 'chart'`. It decides which Copy path runs, so it has to
  be honest: a `chart` block is expected to contain a `<canvas>` or an `<img>`.
- **`name`** is what the menu, the Report pane and the exported section heading call it. Name it what
  the output is ("ANOVA table"), not what it is made of ("table 2").
- **`rows`** — an array of plain objects — is what Copy turns into tab-separated text and what Send to
  Word / PowerPoint export as a real table. **A table block without `rows` copies nothing and exports
  as an empty section.** If your output is a table, pass its rows even if the markup is bespoke.
- **`text`** does the same job for a prose block.

Two paths every block has to support, and what makes them work:

- **Copy** — tables copy as TSV from `rows` (matching the worksheet's clipboard conventions), prose
  copies `text`, charts copy their PNG. If neither `rows` nor `text` is set, Copy falls back to the
  block's `innerText`, which is a last resort, not a design.
- **Copy as Picture** — charts use their canvas; everything else is rasterised from DOM by
  `blockCapture.js` via an SVG `<foreignObject>`. That path re-reads every visible CSS property off
  the live node with `getComputedStyle` and inlines it, because the SVG renders in its own document
  with no access to the page's stylesheet, tokens or webfonts. **So: if a block's appearance depends
  on anything outside the properties listed in `COPIED`, add the property there or the capture will
  not match the screen.**

A chart block must be **attached to the container before the chart mounts** — a Chart.js chart built
in a detached element paints nothing. `drawGraph()`, the v1 `mountChart()` path and `graphs.js` all
append the wrapper first for exactly this reason; keep that order.

And the mirror of it: **anything that detaches a block containing a chart must stop the chart first**,
or Chart.js throws `this._fn is not a function` from its animation tick every frame, against a canvas
that has left the document. `removeBlock()` in app.js does this via `stopChartsIn()`. Use `stop()`, not
`destroy()`, so the canvas keeps its last frame and Undo can re-insert the same node.

## Adding a procedure

One entry in the config registry + one handler in the backend `_HANDLERS`. Nothing else — see
`CLAUDE.md`'s architecture rules for why, and the area's memory note for that menu's specifics. The
config entry needs `icon:` (above), and a field that would clutter the dialog needs
`advanced: true` so it lands in the collapsed Options section.

## How a result reaches the branded PDF

`backend/report_engine/` owns the look of every PDF: `theme.py` (fonts, palette, metrics, the t-curve),
`components.py` (the flowables), `builder.py` (page templates and the furniture). It knows nothing about
statistics — `backend/core/reports.py::_engine_sections()` is the only translator, and everything that
knows the SHAPE of a result stays on that side.

**A new procedure needs nothing to appear correctly.** It gets a card, its `tables: [{title, rows}]`
become group-labelled StatTables, and its `conclusion` / `interpretation` / `summary` becomes the
caption. Two things are worth knowing:

- **The verdict badge is derived from numbers, never from prose.** `report_engine/verdict.py` reads
  `p_value`, then `r_squared`, then `accuracy`, then `segments`. If a procedure's headline is none of
  those, or the derived wording is wrong for it, put `verdict_label` / `verdict_polarity` /
  `key_stat` straight in the result — explicit fields always win. **Never** make the badge depend on
  matching words in a conclusion: those get reworded, and "not statistically significant" contains
  "significant".
- **Polarity means attention, not good news.** `positive` (green) = this test found something;
  `negative` (red) = an assumption or a model is in trouble; `neutral` = nothing to flag. A significant
  NORMALITY test is red. If a new procedure is an assumption check, add its id to `_INVERTED` in
  `verdict.py` — ids and menu labels are both normalised, so either spelling matches.

Numbers in a table are formatted by `components.format_cells()`, which gives a column **consistent**
decimals whenever any value in it is fractional. Word goes through the same function. Don't format
numbers into strings before handing them over, or both lose the alignment.

**A chart is captured for print, not photographed off the screen.** `printCapture()` in app.js
re-renders the whole result offscreen inside `theme.withPrintRendering()` — light palette, 2x — so a
report exported from dark mode still has light figures. That helper is `async` and holds the palette
until the capture settles, deliberately: charts draw a frame or two after they are constructed, and a
plugin that fills the plot area reads the palette *then*. If you add a renderer, it only has to report
its PNG through `onCapture` as every other renderer does.

## Before saying it works

There is no automated test suite. Verify in this order — the browser layer has repeatedly caught
bugs the other two cannot:

1. scipy/statsmodels cross-check in Python
2. the live REST API
3. the real dialogs driven in Chrome, in **both** themes

After editing frontend code, hard-reload (**ctrl+shift+r**): Chrome caches the ES modules across a
normal reload, `location.reload(true)` included.

## The name and the brand

The product is **Gosset**. The repo directory, the Python packages, the endpoints and the module names
still say `personal-analytics-mcp` / `analytics_mcp` deliberately — rename user-facing **strings**
only, never identifiers or paths. The old name in a code comment is fine.

Brand assets are in `frontend/brand/`, and there are two rules that are easy to break:

- **`mark.svg` and `logo.svg` stroke with `currentColor` and name no colour of their own.** One file
  serves the menu bar, the About window and the accent treatment; the accent version is an ancestor
  setting `color: var(--accent)`, not a second asset. Adding a stroke colour to the SVG breaks both
  themes at once.
- **`logo.svg` must be INLINED, never `<img src>`.** Its wordmark is live `<text>` in IBM Plex Sans,
  and an `<img>` gets neither the page's webfont nor a `currentColor` to resolve against — it would
  silently render in a system sans, in black. `brand/brand.js` does the inlining; use it.

The favicons are DERIVED: `python frontend/brand/make_favicons.py` regenerates the PNGs and the `.ico`
from the mark's own geometry. If you change the mark, re-run it, and check the 16px result — the small
sizes are drawn with a heavier stroke because a 2-unit stroke is only 1px at 16 and greys out.

Version and About strings live in `brand/brand.js`.

## Theming

Both `:root[data-theme='light']` and `[data-theme='dark']` must define every token, and a raw hex
anywhere else in `style.css` is a bug. See the visual-direction section of `CLAUDE.md` for the
locked tokens and the ban list (no purple/indigo, gradients, glassmorphism, glow, emoji as icons,
marketing copy). Icons need no theme handling at all — `currentColor` is the whole mechanism.
