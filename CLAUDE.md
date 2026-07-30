# Gosset (repo: personal-analytics-mcp)

The product is called **Gosset**, after W. S. Gosset — "Student" — who published the t-distribution
in 1908. The repo directory, the Python packages (`analytics_mcp`), the endpoints and the module
names still carry the old `personal-analytics-mcp` name ON PURPOSE: renaming them would risk breaking
installs and MCP client configs for no user-visible gain. Rename user-facing STRINGS only.
Brand assets live in `frontend/brand/` — see the brand rule below.

A **Minitab-equivalent desktop analytics app**, built one menu area per scoped session. Same
analysis code serves two interfaces: a REST API + browser UI, and an MCP server.

Read this first, then the linked memory notes for whatever area you're touching (paths relative to
`~/.claude/projects/C--Users-xafiz-OneDrive-Documents-personal-analytics-mcp/memory/`).

**Project files are `.gsp`** ("Gosset project"), which is what the Windows installer registers. The
older `.baproj` is still ACCEPTED on open so nobody's saved work becomes unopenable — the format never
changed, only the extension. Everything below that says `.baproj` means `.gsp` for anything new.
A `.gsp`'s `worksheets[].rows` are **row objects keyed by column name**, not arrays; a hand-authored
fixture with arrays 422s at `POST /datasets/values`, and until 2026-07-30 it did so INVISIBLY (see the
trap list).

## Run it

```
LaunchBackend.bat                                  # venv + uvicorn on :8000 + opens the browser
uvicorn backend.api:app --reload --port 8000       # manual equivalent
python mcp_server.py                               # MCP server (stdio), separate process/state
cd desktop && npm start                            # the Electron shell (falls back to .venv python)
cd desktop && npm run build                        # PyInstaller sidecar + NSIS installer
```

The desktop shell (`desktop/`) **wraps** this and never replaces it: same frontend, same REST API, a
bundled Python sidecar on a free loopback port. → `project_desktop_shell_installer.md`

Frontend is plain ES modules + CSS, **no build step**, served by FastAPI itself from `frontend/`
(`app.mount("/", ...)` at the bottom of `api.py`, mounted last so it never shadows API routes).
Open `http://localhost:8000`. Reports land in `output/`, served at `/output`.

There is **no automated test suite**. Verification is three layers, in this order:
scipy/statsmodels cross-check in Python → the live REST API → the real dialogs driven in Chrome.
The browser layer has repeatedly caught bugs the other two cannot.

## Layout

```
backend/api.py            ~850 lines, every REST route. Thin: parse → core → pydantic out.
backend/core/
  datasets.py             in-memory DatasetStore, dtype re-inference, paste/rename
  basic_stats.py          all 18 Basic Statistics procedures, one compute() dispatch
  regression_models.py    all 13 Regression procedures, one compute() dispatch
  anova.py                all 20 ANOVA procedures (one-way → GLM → mixed → MANOVA → ANOM)
  calc.py                 all 28 Calc procedures (Calculator → random data → resampling → matrices)
  expressions.py          the Calculator's ast-whitelist engine + its 49-function library
  distributions.py        the 26-distribution catalogue in Minitab's parameterisation
  data_ops.py             all 25 Data menu operations, one compute() dispatch
  graphs.py               Graph menu data (client renders it)
  procedures.py           ProcedureError + shared option parsing / JSON sanitising
  charts.py               matplotlib PNGs (house style rcParams)
  reports.py              Word / Excel / Markdown / PowerPoint, and the PDF's ONLY translator
  stats.py tests.py regression.py forecasting.py segmentation.py predictive.py   (v1 analyses)
backend/report_engine/    the branded PDF. Reusable and statistics-free — see the rule below.
  theme.py                fonts, palette, metrics, and t_curve_points(): the signature curve.
                          CURVE_SPAN is the dial that matters — the rule is ~55:1, so a bell spread
                          across all of it reads as a sagging line, not a distribution. Tails flat.
  components.py           the flowables: ResultCard, VerdictBadge, StatTable, ChartFigure, Caption,
                          NoteBlock, plus curve_png/mark_png for the formats that need pixels
  builder.py              page templates, the every-page furniture, page X of Y, landscape switching
  verdict.py              a badge's three fields, derived from NUMBERS — never from prose
  fonts/                  the five bundled OFL faces + their licences (fetch_fonts.py re-downloads)
analytics_mcp/            MCP surface: app.py, tools.py (10 tools), models.py (shared pydantic)
frontend/
  app.js                  shell, windows, session log, worksheet registry, project save/open
  themeMode.js            light/dark: resolve, apply to <html>, the menu-bar switch, notify
  windowManager.js        MDI: drag/resize/minimise/taskbar
  worksheet.js            the grid: selection, clipboard, delete, per-sheet undo/redo, storeColumns
  worksheetTabs.js        the tab strip (pure view; app.js owns the registry)
  constants.js            the K1/K2… store and its window
  conditionalFormat.js    the worksheet's cell-tint rules: kinds, evaluation, Manage Rules
  menu.js                 dropdown/flyout engine (hover intent, keyboard, edge flipping, icon slot)
  icons/registry.js       219 inline SVGs: one per leaf menu item, plus the block menu's own set
  icons/gallery.js        Window > Icon Gallery (or #icons): the set in a grid + the description review
  menuHelp.js             the hover/focus help card: rest-intent timing, placement, pointer-events:none
  blockMenu.js            the chevron action menu on every output block (one shared, moved on hover)
  blockCapture.js         any block -> PNG: canvas for charts, SVG foreignObject for tables/text
  reportPane.js           Window > Report: the staged blocks, drag-reorder, notes, curated export
  brand/mark.svg          the G-mark: one path, a t-curve as the G's crossbar. currentColor only.
  brand/logo.svg          mark + "Gosset" wordmark; live <text>, so it must be INLINED not <img>
  brand/brand.js          fetches and inlines those two; holds the version and the About strings
  brand/make_favicons.py  regenerates favicon-16/32/48.png + favicon.ico FROM mark.svg's geometry
  procedureDialog.js      shared dialog builder + standard result layout
  dialogFields.js         composite dialog fields: the Data menu's (conditions, sort keys, mapping
                          tables, worksheet pickers) and the ANOVA menu's (term picker, subset,
                          model-factor/covariate/holds)
  *Config.js              declarative registries (fields, showIf, request building)
  matrices.js             the M1/M2… store and its window (constants.js's twin)
  basicStats.js regression.js anova.js calc.js dataMenu.js graphs.js   behaviour layers
  charts/                 theme.js, renderers.js, modelRenderers.js, graphConfig.js, plotly.js
  resultView.js           tiles/tables renderer shared by app.js and the procedure dialogs
```

`analytics_mcp/models.py` holds the pydantic output models that **both** interfaces import.
The MCP server and the REST API each have their own DatasetStore — they do not share state.

## Architecture rules

**One endpoint per menu area, not per procedure.** `POST /datasets/{id}/basic-stats`,
`/regression-model`, `/anova`, `/calc` and `/data-op` each take a `procedure`/`operation` string
and dispatch through a handler dict. 18, 13, 20, 28 or 25 pydantic request models would be pure
boilerplate.

**The Calculator never evaluates a string.** `expressions.py` parses with `ast.parse` and walks the
tree with one visit method per allowed node type; anything without a method — an attribute access,
a subscript, a lambda, a comprehension — falls into the generic reject. Whitelist by construction,
not a blacklist of things to strip. Minitab's spellings (`AND`, `=` for equality, `<>`) are
rewritten into Python's before parsing, together with an offset map, so the caret the dialog shows
still points at the character the user actually typed.

**Three stores live in the browser, not the server.** Constants (K1…), matrices (M1…) and the Set
Base seed are client-side, which is what lets them be saved in a `.baproj`. A Calc result names
what it wants stored — `store_columns`, `store_constant`, `store_matrix` — and `calc.js` routes it;
a written column goes through the ordinary `set_columns` data operation so it lands on the undo
stack like any other edit. A matrix operation posts its operands with the request, because the
server keeps no matrix store between calls.

**A fitted model is client state, not server state.** Stat > ANOVA's GLM and Mixed dialogs return a
`model_spec`; `anova.js` keeps it and every downstream dialog (Comparisons, Predict, Factorial
Plots, Contour, Surface, Response Optimizer) posts it back so the backend refits. Refitting costs
milliseconds, the API stays stateless, a result window outlives any cache — and the fitted model
travels in a saved `.baproj`. The items downstream of a fit are `aria-disabled` with a tooltip
until there is one (`anova.refreshMenuState()`, called from app.js's).

**A worksheet is a dataset; a project holds several.** `state.datasets` in app.js is the registry,
`state.dataset` the active one, and `worksheetTabs.js` is only its view. Everything else resolves
`activeDataset()` at the moment it acts. The Data menu's cross-worksheet operations (merge, stack
worksheets, conversion tables) are handed the OTHER frames by `api.py`; `data_ops.py` itself never
sees the store. Undo history is per worksheet — one shared stack would apply sheet A's snapshot to
sheet B the moment someone switched tabs.

**Every procedure returns the same shape:** `tables: [{title, rows}]`, `highlights`,
`graphs: [{renderer, title, data}]`, `conclusion`/`summary`, plus loose scalars. One frontend
renderer covers all of them, and a reopened `.baproj` (no live render function) still shows
findings because the payload carries `tables` + `highlights`.

**The report engine knows no statistics.** `backend/report_engine/` is handed titles, rows, a PNG path
and a caption; it has no idea what a p-value is. Everything that knows the SHAPE of a result — which key
holds the table, which fields are narrative — stays in `reports.py::_engine_sections()`, the one
translator. That is what makes the engine testable on its own and reusable, and it is why a new
procedure needs no engine change at all.

Its corollary: **a verdict badge is computed from numbers, never parsed from prose.** `verdict.py` reads
`p_value` / `r_squared` / `accuracy` / `segments`, or the explicit `verdict_label` / `verdict_polarity` /
`key_stat` a procedure supplies. Conclusions get reworded, and "not statistically significant" contains
the word "significant" — a regex over them would flip a badge from red to green on a copy edit. Polarity
is about ATTENTION, not good news: a significant *normality* test is red, because the assumption failed.

**Config / behaviour split.** A declarative registry (`basicStatsConfig.js`, `regressionConfig.js`,
`charts/graphConfig.js`) describes fields and request building; the sibling module does forms,
dispatch and rendering. Both dialog areas are thin because `procedureDialog.js` owns the form
builder (field types: column, columns, value, levels, select, radio, checkbox, number, text,
checkbox-grid) and the result layout (narrative → tiles → titled tables → graphs → run details →
capture).

**So: adding a procedure = one entry in the config registry + one handler in the backend
`_HANDLERS`. Nothing else.** (A Data operation is the same: one entry in `dataMenuConfig.js` + one
handler in `data_ops.py`. Its `DataOpResult.mode` — `none` / `in_place` / `other_in_place` / `new`
/ `many` — is the whole contract for what the frontend does next.)

**One config entry fully describes a menu item: `icon`, `description`, `needs`.** Every leaf carries
all three (239 leaves, 239 described); no parent carries any.

- **`icon`** — `frontend/icons/registry.js` holds 207 inline SVGs keyed by CONCEPT, so one entry
  serves every item that means the same thing (GLM > Predict and Mixed > Predict share `predict`; all
  26 distributions share theirs between Random Data and Probability Distributions). `menu.js` renders
  a fixed 16px slot on EVERY item, empty for a category — the empty slot is what keeps all the labels
  in one column. Icons stroke with `currentColor` and nothing else, so light/dark, the accent-filled
  hover row and a disabled item's muting all come for free.
- **`description` / `needs`** — the hover help card (`frontend/menuHelp.js`). One sentence of what,
  one of when; where siblings are confusable the description's job IS the difference (1-Sample Z vs
  t, Rank vs Sort, Balanced vs GLM). `needs` is the muted data-requirements line. No second person,
  no promotional words. A disabled item needs no `needs`: `menuHelp.js` promotes its `title` there,
  so the greyed GLM items explain themselves.

A hand-written entry names all three inline; a procedure registry declares them on the PROCEDURE and
its menu builder forwards them (**add a group helper and you must forward all three, or the card goes
silently blank**); the static File / Edit / Window markup uses `data-icon` / `data-help` /
`data-needs`, hydrated by `menus.hydrateIcons()`.

The card's behaviour is the part that must not annoy: it appears only after the pointer RESTS on an
item for 600ms, so scanning a menu shows nothing; once one card has shown it swaps instantly between
items; it is `pointer-events: none` so it cannot be hovered, clicked or focused; and it is placed
outside its panel with candidates rejected if they would cover ANY open panel. Submenu parents get no
card — the flyout wants that space. File > Options has "Show menu help on hover" (default on).

Check additions in **Window > Icon Gallery** (or `#icons`) in both themes; its "Show descriptions"
toggle turns it into the content-review page.
→ `project_menu_icon_registry.md`, `project_menu_help_card.md`, `reference_icon_registry_traps.md`

**The brand is one path, and it is never recoloured in the asset.** `frontend/brand/mark.svg` is a
single continuous stroke: a geometric G whose crossbar is a t-distribution, with the right tail
running out to meet the bowl. It strokes with `currentColor` and nothing else, so the same file serves
the menu bar (inherits `--ink`), the About window and the loading state (an ancestor sets `color:
var(--accent)`), in both themes. Never add a stroke colour to the asset — that is what would force a
second file. `logo.svg` adds the wordmark as **live `<text>`**, so it must be **inlined** into the
document (`brand.js` does this) and never used as `<img src>`: an `<img>` renders in an isolated
context where `currentColor` falls back to black and the page's IBM Plex Sans is unavailable. The
favicons are generated FROM the mark by `brand/make_favicons.py` — edit the geometry, re-run it.

**Every output block goes through `block()` in `resultView.js`.** That wrapper is what gives a block
its chevron menu (Send to Word / PowerPoint / Report, Copy, Copy as Picture, Print, Delete), keyboard
focus and Ctrl+C. The payload a block declares — `kind`, `name`, `rows` or `text` — is what Copy and
the exporters read; a table block with no `rows` copies nothing and exports as an empty section. The
block's export metadata lives in a WeakMap, not in data-* attributes, so rows keep their numeric types
and a closed window's blocks are collectable. → `project_block_menu_report_pane.md`

**The Report pane is a curated report, not a session log.** `reportPane.js` holds an ordered list of
staged blocks plus free-text notes; it is app state, not DOM state, so closing the window loses
nothing and the list is what goes into the `.baproj` (**v3**). File > Export Report offers both
scopes: "Everything from this session" (analyses in run order) and "Report pane contents" (blocks in
the curated order). A staged chart keeps its full PNG because that PNG *is* its export image;
everything else keeps only a thumbnail, since it exports from its rows.

**A single block exports as the ONE thing it is.** Block and Report-pane sections set
`allow_generated_chart: false`, or `section_chart()`'s last-resort branch renders a chart out of a
table block's own rows and the document gets both. A Report-pane note has an empty title, and all
three document renderers skip the heading for an untitled section.

**A field marked `advanced: true`** goes into a collapsed `<details>` "Options" section. That's how
a fifteen-setting dialog opens looking like a four-setting one — the user asked for "power without
clutter" explicitly.

**A figure is RENDERED for export, never photographed off the screen.** `theme.renderForExport(draw,
{width, height, scale, scope})` is the only path an export may take to a chart PNG — the report engine
(`app.js::printCapture`), the block menu's Send to Word/PowerPoint, Copy as Picture and Report-pane
staging all go through it. It renders the figure again into an attached offscreen `.print-figure` host
at a fixed 800×500 CSS px, devicePixelRatio 2 (= 1600×1000 real px), in the light palette with
print-tuned type (12.5pt ticks, 13.5pt axis titles, 0.6px gridlines — a figure is scaled DOWN into a
~460pt frame, so screen sizes land at ~6.5pt there). The old contract — "the chart travels as the
picture the user is looking at" — meant the same chart exported at a different aspect from a different
window size, with tick labels sized for a 300px panel.

- **Composites compose from the LAYOUT.** `compositeFigure` reads each canvas's offset inside the host
  and draws it at its own size and position, so `.marginal-layout` and the matrix `.model-grid` come
  out with the geometry their CSS already describes — plus the DOM-only labels (a matrix plot's
  diagonal, panel titles) drawn on. Its predecessor took an array of canvases and a column count and
  stretched every one into the FIRST panel's box: a marginal plot's 74px histogram strip became the
  cell size for its scatter, and a matrix plot's diagonals (which hold no canvas) shifted every panel
  after them one square early. `renderers.captureGrid(container, onCapture)` uses the same composition
  for the on-screen record's capture.
- **`applyPrintGeometry` runs TWICE, and that is not redundant.** A composite grid's `1fr` rows only
  have a height once their panels have been sized, and a chart's deferred resize can land after the
  first pass — when it did, the figure composed at the collapsed height and a marginal plot exported as
  a letterbox strip, intermittently. The pass is idempotent; the second one closes the race.
- **Plotly figures go through `Plotly.toImage`.** A WebGL canvas cannot be read by `drawImage`, so
  contour/3D/surface used to reach documents as a rasterised screenshot of their surrounding markup.
- **A marginal histogram is padded to the scatter's PLOT AREA** (`alignMarginal`), not its canvas, or
  the bars sit ~40px off the slice of x they describe. It writes only leaf numbers into
  `options.layout.padding`: `chart.options` is a resolver proxy, and assigning a branch read off it
  back into itself recurses until the stack runs out.
- **`fitCategoryLabels` keeps a categorical axis legible** — thin the ticks, then truncate with an
  ellipsis, then rotate 45°, each only if the axis is still too tight. Called from `mountChart` for
  every chart and again at print geometry, so 120 date labels read as 8 spaced ones on screen and on
  paper.

**A grouping column is validated in the CORE.** `procedures.check_group_column` refuses a column with
more than 30 distinct values or with a single row in every group, and warns from 15 up; `graphs.py`
(via `_group_values` and `compute`) and `anova.py` (via `_group_summaries` and `compute`) both call it,
so the MCP tools, the REST API and the dialogs cannot disagree. The refusal carries `swap` — the two
field names to exchange — which the API passes through as a 400 body field, `apiClient` attaches to the
Error, and both form builders turn into a one-click "Swap X and Y" button. That is what an interval
plot asked to group by a 96-value measurement now says, instead of drawing 96 one-observation
"groups". Soft warnings ride in the result payload as `warnings: [...]` and render above the findings
(`procedureDialog.buildWarnings`).

**A report is a document, not a data dump.** `reports.TABLE_ROW_LIMIT` (25) / `TABLE_ROWS_SHOWN` (20):
past the limit a table exports as its first 20 rows plus a mono note naming how many were left out, in
the PDF, Word, Markdown and PowerPoint. **Excel is deliberately exempt** — a spreadsheet is where
someone goes FOR the rows. The block menu's "Send to Report (full table)" sets
`ReportSection.full_tables` to opt one section out, and it survives a `.baproj` round-trip.
Captions come from ONE place: `_split_narrative` compares fragments through `_caption_key`, which
flattens whitespace, separator punctuation and case — so `conclusion` "Interval Plot of y by g." and
`summary` "Interval Plot of y.", or a title restated with a different dash, collapse to one sentence
instead of printing as "X. X."

**Chart interactivity is one switch, read in one place.** File > Options > Charts > "Interactive
charts" (default on, persisted with the other Options — an app preference, so it is NOT in a
`.baproj`). `charts/theme.js::interactive()` is the only reader: `baseOptions()` and `mountChart()`
apply it, so no renderer ever asks and no chart can disagree. Plain mode's off switch is
`events: []` — Chart.js then attaches NO listeners, and tooltips, hover highlight and legend clicks
all stop from that one line. Three consequences that are easy to undo by accident:

- **A capture is always plain**, because `interactive()` is false while `printing`. That is what makes
  an export identical in both modes; never make a capture honour the setting.
- **Plotly plain mode is layout attributes** (`hovermode` / `dragmode` / `scene.dragmode` false),
  never `config.staticPlot`. Config cannot be relayouted and staticPlot skips `initInteractions`
  permanently, so a plot born static could never come back without a re-plot — which would throw away
  the camera angle the user rotated to. The modebar (config, likewise) is hidden by
  `:root.charts-plain` in CSS instead, as is any caption clause that promises an interaction
  (`.chart-note-interactive`: "drag to rotate").
- **Switching applies to open windows immediately** through `reThemeOpenWindows()` — the same
  rebuild-every-chart path a theme switch uses, for the same reason (a chart bakes its interaction
  options in at construction). It does NOT re-enable draw animation; trap 2 still holds.

**Minitab parity is the spec.** Menu items map 1:1 with Minitab's, in Minitab's order and with its
dividers. OK closes the dialog and opens a result window. Where an algorithm is proprietary, an
honest substitution is used **and labelled in the UI** (Shapiro-Wilk for Ryan-Joiner; A-D p-values
from D'Agostino & Stephens; Bonett's p by bisecting its own CI; Dixon's Q against tables, n ≤ 30).

## What's shipped

- **Worksheet** — a blank `C1..C20` × 50 dataset is created server-side at load and is the
  permanent default view; never gated behind an upload screen. Cell edits widen the column dtype
  rather than rejecting. Two-row Minitab header (positional `C{n}` label + editable real name),
  arrow-key navigation, sticky headers, range selection, clipboard, undo/redo.
- **MDI window system** — worksheet is the base document layer; every form and result is a
  draggable/resizable/minimisable window with a taskbar. The page itself never scrolls.
- **Session Window** — pinned, collapsible, logs every run (menu- and chat-triggered), never
  cleared. Entries are clickable and refocus/reopen their result window.
- **Worksheet tabs** — one per open worksheet, along the bottom of the grid. Click to switch
  (which sets the app-wide active dataset, so the Assistant and every Stat/Graph dialog follow),
  double-click or F2 to rename, × to close (confirmed when it holds data; the last one cannot be
  closed), + for a blank one. Every Data operation that makes a worksheet opens its tab and
  switches to it.
- **Menu bar** — File / Edit / Data / Stat / Graph / Window, with real accelerators.
  Data mirrors Minitab's own order: Subset / Split / Merge ▸ / Stack Worksheets; Sort / Rank /
  Delete Rows / Erase Variables; Copy ▸; Stack ▸ / Unstack / Transpose; Recode ▸ / Change Data
  Type / Date-Time ▸ / Concatenate; Conditional Formatting ▸; Display Data / Worksheet
  Information / Constants. **25 operations**, all through `POST /datasets/{id}/data-op`.
  Stat: **Basic Statistics (all 18)**, **Regression (all 13 + the Predict panel)**,
  **ANOVA (all 20)** — One-Way (both layouts, Welch, Tukey/Fisher/Dunnett/Games-Howell with
  grouping letters), Test for Equal Variances, Balanced and Fully Nested ANOVA, General MANOVA,
  a **General Linear Model** submenu (fit → comparisons / predict / factorial plots / contour /
  surface / response optimizer) and a **Mixed Effects Model** submenu, the standalone
  interval/main-effects/interaction plots, and Analysis of Means. Then Tables (chi-square),
  Time Series (Forecast), Multivariate (Segmentation), plus the v1 predictive tools.
- **Calc menu** (between Data and Stat) — the **Calculator** (a bespoke window: column list,
  function browser over 49 functions in 6 categories, live server-side validation with a caret
  under the offending character), Column/Row Statistics, Standardize (5 methods), Make Patterned
  Data ▸ (numbers / arbitrary / text / date-time, both of Minitab's repeat controls), Make Mesh
  Data, Make Indicator Variables, **Set Base**, **Random Data ▸** and **Probability
  Distributions ▸** (26 distributions, one generated dialog each, all from one catalogue the
  backend serves so the two menus can never disagree), **Resampling ▸** (5 bootstrap and
  randomization tests, each with its distribution histogram and the observed value marked) and
  **Matrices ▸**. 78 dialogs.
- **Constants and matrices** — K1/K2… and M1/M2… stores per project, each with its own window,
  moved to and from worksheet columns by Data > Copy (the three matrix items there hand off to the
  Calc implementations — one operation, two menu entries). Client-side: see the architecture rule.
- **Conditional formatting** — per-column rules (greater/less/equal/between/contains, highest and
  lowest N, outside 3σ, IQR outliers, a simplified Pareto "vital few") that tint cells. Recomputed
  from the live grid on every render, so "highest 5" follows an edit. Managed and cleared from
  Data > Conditional Formatting.
- **Export** — PDF / Word / Excel / Markdown / PowerPoint. Every on-screen chart registers a PNG capture that
  `POST /reports` accepts as `chart_image_base64`, so any new chart type is exportable with zero
  server-side work; `charts.py::render_analysis_chart()` also covers results server-side.
  The **PDF is a branded document** from `backend/report_engine/`: the Gosset mark and the
  t-distribution rule on every page, a Source Serif cover block, one bordered card per result with a
  coloured verdict badge, small-caps group labels, mono numerals, captions under the figures, and
  "page X of Y" over an inverted curve. Wide tables shrink a step then take a landscape page; a card
  taller than a page splits with its border continuing. The Word export mirrors that hierarchy within
  python-docx's limits (the curve rules travel as images pre-rendered from the same function), and
  Markdown and Excel carry the verdict line as text. Charts are re-rendered for print — light palette
  at 2x — so a report exported from dark mode still has light figures.
  `.baproj` project save/open — **version 2** saves EVERY worksheet plus which was active, the
  constants, the matrices, the Set Base seed, the fitted ANOVA models and the conditional-formatting rules; a v1 file (one worksheet) still opens. Rules name
  their worksheet by INDEX in the file, never by dataset_id: the ids are minted fresh by the server
  on every open. Print.

Sample data: `sample_factorial.csv` (balanced 3×4×2 with two covariates, two responses and a real
machine×shift interaction — 4 per cell, for ANOVA/GLM/MANOVA/mixed), `sample_nested.csv`
(4 lots × 3 batches × 5 samples, for Fully Nested ANOVA), `sample_grid.csv` (two-level factors,
Poisson counts, a paired column),
`sample_small_batch.csv` (20 rows, planted outlier — for Dixon), `sample_stability.csv` (ICH Q1E),
plus the v1 `sample_data.csv` / `sample_customers.csv` / `sample_timeseries.csv`.

## Visual direction — locked, with a ban list

Enterprise "precision instrument" register, in **light and dark**. Both token sets live at the top
of `frontend/style.css` (`:root[data-theme='light']` / `[data-theme='dark']`) and **both themes
define every token — a raw hex anywhere else in that file is a bug**, because it will be wrong in
one of the two. Light: `--workspace #EDEFF2`, `--surface #FFFFFF`, `--accent #0F62FE`. Dark:
`--workspace #161616`, `--surface #262626`, `--accent #78A9FF` (`#0F62FE` fails contrast on dark).
IBM Plex Sans for interface text; IBM Plex Mono + `tabular-nums` for every number, table cell,
worksheet cell and the whole Session Window. 4px radius.

Theming rules that are easy to get wrong:

- `--on-accent` is the ink for text **on** a filled accent surface: white in light, near-black in
  dark. Never write `color: #ffffff` next to `background: var(--accent)`.
- Focus: in light, elevation marks the focused window; in dark, shadows barely read on `#161616`,
  so the **border** steps up instead (`--border-strong`). `--focus-ring` is its own token.
- Table/worksheet gridlines use `--gridline`, deliberately softer than the `--border` frame around
  them; at full strength a dense grid reads as a cage.
- The theme is applied by an inline `<script>` in `<head>` **before** the stylesheets, so opening
  in dark never flashes white. It duplicates two literal colors — the only such duplication in the
  app, because there is no CSS to read yet — and `themeMode.apply()` clears them immediately.
- `@media print` re-declares the light tokens: paper is white whatever the screen is.
- Chart tokens (`--chart-1..8`, one set per theme) are read from CSS by `charts/theme.js` at
  chart-creation time; `theme.refresh()` re-reads them on a switch.
- Conditional-formatting tints (`--cf-amber`…`--cf-grey`) are applied as `td[data-cf="…"]`, not as
  an inline colour, so a cell re-tints itself on a theme switch with no JavaScript. Those rules are
  declared **before** the selection rules in the stylesheet: same specificity, later wins, and a
  selected cell must always read as selected however it is highlighted.

**Banned — treat any of these as a regression, not a style choice:** dark purple/indigo themes,
gradients (background or text), glassmorphism/backdrop-blur, glow shadows, decorative background
animation, emoji as icons, marketing copy. Button labels say exactly what they do ("Run
regression", never "Submit"). Motion: the ~500ms numeric count-up is the one signature; everything
else is 120–220ms and functional; all suppressed under `prefers-reduced-motion`.
Server-rendered matplotlib uses the same tokens via `_HOUSE_STYLE`. Categorical colours are IBM
Carbon hues with purple/indigo deliberately omitted. → `feedback_ui_design_constraints.md`

## Traps that cost real debugging time

None of these produce an error message. Full detail in the reference memory notes.

1. **`<input type=number step=0.01>` silently blocks submit** when the value isn't `min + n×step`
   (0.5 with `min: 0.000001` is invalid). No event, no console message — reads as a dead button.
   Every fractional field uses `step: 'any'`; forms carry `novalidate`; the backend is the only
   range authority. Diagnose with `form.querySelector(':invalid')`.
   → `reference_form_step_blocks_submit.md`
2. **Chart DRAW animation is off, and must stay off.** Chart.js only interpolates numbers and
   colours, and a per-type `animations` object REPLACES the defaults instead of merging — so for every
   bar chart `backgroundColor`/`borderColor`/`pointStyle` get no interpolator, the animation throws
   from its tick, and it then NEVER completes: the chart sits in Chart.js's animator forever and its
   canvas is left cleared. What you see is a stale composited frame; `getImageData` returns nothing,
   which is why captured chart PNGs came out blank. `theme.animation()` returns `{duration: 0}`; the
   app's signature motion is the numeric count-up, not chart draw-in. Anything that detaches a canvas
   must `stopChartsIn()` first, and `chart.stop()` can throw for the same reason, so it is wrapped.

   **Its sting was in `Chart.defaults.animation`, and never assign over that object.**
   `Animations.configure()` copies each property's options with
   `for (const option of Object.keys(Chart.defaults.animation))` — that object's KEYS are the list of
   per-animation option names Chart.js carries across, which is why it ships with `type`, `fn`, `from`,
   `to`, `easing`, `delay` and `loop` all present-but-undefined. Assigning `{duration: 0}` over it left
   the list as `['duration']`, so `colors`' `type: 'color'` and `snap`'s `fn` were stripped from every
   animation — which is why those two configs looked correct and did nothing. Consequence, live until
   2026-07-29: hovering any bar or point animated `backgroundColor` from `rgba(…)` to `#059BFF7F` with
   no interpolator, threw from the tick, and wedged `Chart.animator` for the whole page on one dead
   rAF — so **hover tooltips activated and froze at opacity 0.03, invisible**, and a legend
   show/hide could not repaint. `applyStructuralDefaults()` now MERGES: `{...Chart.defaults.animation,
   ...animation()}`, and zeroes `transitions.active` so hover feedback is instant rather than a 400ms
   colour fade. The tooltip's own 200ms opacity fade (0 under reduced motion) is declared in
   `tooltipStyle()` and is the only chart animation the app keeps.
   → `reference_chartjs_pitfalls.md`
3. **A Chart.js chart built in a detached element paints nothing.** `mountChart` waits for
   `canvas.isConnected` then does `resize()` + `update('none')` + `draw()` — all three matter.
   Also: Chart.js only interpolates numbers and colours (`stepped: 'after'`, `borderDash` etc.
   throw from inside the animation tick); a linear axis faked as categorical needs pinned ticks;
   plugin-drawn marks are invisible to axis auto-scaling. The guards in `charts/theme.js` look
   redundant and are not — don't simplify them away. → `reference_chartjs_pitfalls.md`
4. **A duplicate key in the `apiClient` object literal silently wins.** ~25 keys and no warning —
   `grep -n "name:" frontend/apiClient.js` before adding a method. (`regressionModel` is named
   that because `regression` was taken.)
5. **Never make cleanup depend solely on an event that may fire.** `windowManager.close()` relied
   on an animation `onfinish`; a backgrounded tab throttles Web Animations and windows never
   closed. Now: immediate path + a 400ms `setTimeout` backstop.
6. **Chrome caches the ES modules across a normal reload** — even `location.reload(true)`. After
   editing frontend code, send **ctrl+shift+r**, or prove the server has the new file with
   `fetch('/module.js?bust=' + Date.now())`. → `reference_frontend_collision_traps.md`
7. **A destructured theme token snapshots the old theme forever.** `charts/theme.js` exports its
   colors as `let` and reassigns them on a theme switch; ES live bindings only survive namespace
   access. `const { ACCENT } = theme` at import time keeps painting light-theme blue in dark mode —
   always `theme.ACCENT`.
8. **`Plotly.relayout` REPLACES any nested object you hand it.** Passing a whole `scene` back wiped
   `scene.camera` and snapped every 3D plot to its default view on a theme switch. `plotly.js`
   flattens the layout into dotted attribute paths so the camera is never mentioned.
9. **A Chart.js chart cannot be re-themed with `.update()`** — axis, grid and tooltip colors are
   copied into the chart's own options object at build time. Re-themeing means rebuilding, which is
   why `reThemeOpenWindows()` re-renders each result window from its stored record.
10. **A `disabled` button never shows its `title`.** Chrome suppresses pointer events on disabled
   form controls entirely, so a menu item greyed out *because it needs explaining* explains
   nothing. The Data menu's unsupported matrix items use `aria-disabled` + `.menu-item-disabled`
   instead, and the click dispatch skips them AND calls `stopPropagation()` — otherwise the
   document-level menu closer would see the click that the disabled attribute used to swallow.
11. **A widget that redraws itself on every change eats the control you are holding.** The Data
    menu's repeating-row fields rebuild rows to grow a second value box ('between') or a new
    block — but doing that on *every* tick destroys the checkbox or select just clicked and drops
    the next one. They now rebuild only when the row's SHAPE changes and patch text/values in
    place otherwise. Symptom: a second click in the same widget silently does nothing.
12. **A covariate in an interaction makes the other term's "main effect" a test at covariate = 0.**
    With `temp_c` in 60–90 and `machine*temp_c` in the model, machine's Type III F was 0.74
    (p = 0.48) — it is genuinely testing machine at 0 °C. Nothing is wrong and nothing warns you.
    Every ANOVA model therefore centres its covariates, via patsy's stateful `center()` inside the
    formula rather than in the frame: design_info then re-applies the identical shift to every
    prediction grid, so no downstream surface, EMM or optimiser can drift out of step with the fit.
13. **statsmodels quietly drops a random factor when `groups` and `vc_formula` are combined.**
    `MixedLM.from_formula(..., groups=lot, vc_formula={batch: ...})` sets `k_re = 0`, so `lot`
    contributes nothing at all and only `batch` appears in the variance components. With more than
    one random factor, put ALL of them in `vc_formula` inside a single dummy group. Related:
    `exog_re_names` is None on some versions, which silently swallowed the random slopes.
14. **`psturng` floors its p-values at 0.001.** Every strongly significant Tukey comparison came
    back as the same "0.001", losing the ordering between them. scipy ≥ 1.11 has the exact
    `studentized_range` — use `.sf`/`.ppf` and keep psturng only as a fallback.
15. **`.win-body button` styles EVERY button in a window as a `.btn`.** A 200-item picker built
    from plain buttons came out as a wall of outlined pills with the labels squeezed out of their
    14px boxes. Two classes (`.calc-list .calc-list-item`) beat that one-class-one-type selector;
    flex children in a fixed-height list also need `flex: 0 0 auto` or they shrink until the text
    clips. Check any new list-of-buttons against it.
16. **Deserialisation that "cleans" a record silently drops the field the next step needs.**
    `conditionalFormat.setRules()` rebuilt each rule from a fixed key list and lost the
    `worksheetIndex` that `remapWorksheets()` was about to read — so every rule restored from a
    project pointed at no worksheet and quietly never fired. Nothing errored; the tints were just
    absent. Round-trip a project and *count what comes back*, don't just check it parses.
17. **`os.kill(pid, 0)` does not probe liveness on Windows — it TERMINATES the process.** CPython maps
   every signal except `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` onto `TerminateProcess`, so the POSIX idiom
   for "is my parent still alive?" shot the Electron shell dead about two seconds after launch. The
   shell logged a clean startup, spawned the sidecar, and vanished — no exception, no lifecycle event,
   exit code 0. Use `OpenProcess` + `WaitForSingleObject` (`sidecar.py::_watch_parent`).
   → `project_desktop_shell_installer.md`
18. **A failed project restore printed nothing at all.** `restoreProject` calls `wm.closeAll()` and
   clears `state.datasets` before anything can fail, so when it threw, the import panel's error line
   was written into an element that had already been destroyed. No message, no data, a half-cleared
   session — identical to the click doing nothing. Errors now go through `ws.showError`, which draws on
   the worksheet and outlives `closeAll`. **Anything that clears state before it can fail needs an
   error surface that survives the clearing.**
19. **The desktop app's PORT is part of its identity, because localStorage is partitioned by ORIGIN.**
   The window loads `http://127.0.0.1:<port>`, and every File > Options preference, the theme, the
   recent-files list and the "last version run" marker live in localStorage. While the port was
   OS-assigned per launch, each launch got a fresh storage bucket: the desktop app silently reset every
   preference on every restart, and the "What's new" window could never appear because the version
   marker it compares against was always absent. Three origins were sitting in one install's Local
   Storage, one per launch. `sidecar.js` now fixes the port (48219, deterministic walk, OS-assigned
   only as a logged last resort). **Anything that changes the origin throws away all client-side
   state** — the same trap waits for a custom protocol or a hostname change.
   → `project_desktop_shell_installer.md`
20. **A PDF content stream is ASCII85 *then* Flate, and reportlab writes floats with no leading zero.**
    Grepping the raw file for an operator finds nothing; `zlib.decompress` alone also fails, because the
    filter chain is `/ASCII85Decode /FlateDecode`. Use pypdf's `page.get_contents().get_data()`, which
    applies the whole chain. And the success green is emitted as `.141176 .631373 .282353 rg`, not
    `0.141176 …` — a colour regex expecting the leading zero matches nothing. Both of these made a
    verdict badge that was rendering perfectly look like it was missing, for an embarrassingly long time.
    When a probe and a screenshot disagree, **trust the screenshot** and fix the probe.
21. **No bundled font has U+25CF (`●`).** The badge dot is a drawn circle (`components._Dot`), not a
    glyph. Every one of the five faces has `•` and `·` but not `●`, so it rendered as nothing at all —
    silently, because a missing glyph is not an error. Word's own fonts *do* have it, which is why the
    docx badge uses the real character. Check coverage with fontTools before using an exotic character.
22. **`:root[data-theme='light']` cannot be read from any element except `<html>`.** Both token sets are
    declared on `:root`, so `getComputedStyle` on a `<div data-theme='light'>` returns the *dark* values
    it inherited — a plausible-looking probe that quietly measures the wrong theme. `charts/theme.js`
    reads the light values out of the stylesheet RULE (`lightRuleLookup()`) instead, which is how a
    print capture gets light colours without flipping the whole app to light for a frame.
23. **Restoring the theme after `new Chart(...)` returns is too early.** `mountChart` deliberately draws
    on a later frame (it waits for the canvas to be connected), and a plugin that fills the plot area
    reads `theme.SURFACE` at DRAW time. A print capture that restored the palette synchronously produced
    charts with light axes on a dark background. `withPrintRendering` is `async` and awaits the whole
    capture for that reason — an easy "simplification" to make and a hard one to see.
24. **A one-cell reportlab Table cannot split, whatever you set on it.** Splitting happens between
    ROWS, so a card built as a single cell raises `LayoutError: too large on page` the moment its
    content exceeds one page. `components.result_card` therefore uses one row per content flowable,
    with `splitByRow=1, splitInRow=1` and the 14pt padding applied to the first and last rows only.
25. **reportlab declares Helvetica and Times-Roman on pages that draw neither.** Three separate causes,
    each invisible: `CellStyle.fontname` defaults to Helvetica, so **every** Table needs an explicit
    `("FONT", …)` command even when all its cells are Paragraphs; `graphics.shapes.STATE_DEFAULTS`
    seeds Times-Roman into any page that renders a Drawing (the logo), fixed once in `ensure_fonts()`;
    and the canvas preamble sets a font, which is `doc.initialFontName`'s job — passing
    `initialFontName` as a canvas kwarg does nothing, because BaseDocTemplate passes it explicitly.
    Audit with `/BaseFont` over the decoded file, not by eye.

## Working notes

- The spec at `../personal-analytics-mcp-spec.md` is a v1 doc and stops at section 9. If the user
  references a later section or "Phase 5" in it, ask whether a newer spec exists — don't assume.
- Predictors reach patsy under generated safe ids (`x0`, `f1`) because columns are called things
  like `yield (kg)` or `C1`; `_pretty_term` maps labels back for display. The
  continuous/categorical split is sent explicitly as `options.n_continuous` — never guessed.
- The Predict panel refits server-side per prediction from a returned `predict_spec`. Stateless on
  purpose: a result window outlives any server-side cache.
- The old generic `describe`/`correlation`/`hypothesis-test` forms remain in `analysisConfig.js`
  only because the chat parser still emits those actions.
