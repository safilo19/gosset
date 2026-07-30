// The menu icon registry: one inline SVG per leaf menu item, keyed by a concept name that a menu
// config entry names in its `icon:` field. menu.js renders getIcon(entry.icon) into a fixed 16px
// slot at the left of every item.
//
// ===========================================================================================
// STYLE RULES — every addition must follow these. They are what makes a 240-item menu scannable.
// ===========================================================================================
//
// 1.  GEOMETRY. 16×16 viewBox, stroke-based line work, stroke-width 1.5, round caps and joins.
//     Keep every mark inside 1.5–14.5 so nothing clips against the slot. Use the `svg()` helper —
//     it carries all of that, so an icon body is only its paths.
//
// 2.  COLOR. stroke="currentColor" ONLY, which the helper sets on the root. Never write a hex, an
//     rgb(), a var(--token) or a named colour anywhere in this file. Inheriting the menu item's own
//     colour is what makes every icon correct in light theme, in dark theme, on the accent-filled
//     hover row, and muted along with the text of a disabled item — with no per-icon CSS and no
//     JavaScript on a theme switch.
//
// 3.  FILLS. Stroked by default. Two exceptions, both `fill="currentColor"` so rule 2 still holds:
//       - tiny accents — a data point, one filled bar, a letter badge. Use `dot()` and `badge()`
//         rather than writing them by hand.
//       - a shaded region, where the shading IS the concept (a heatmap cell, an area graph's fill,
//         a distribution's shaded tail). Always with a `fill-opacity` well under 0.4, never a
//         second colour, and never more than two shaded regions in one icon.
//     Anything else stays stroked. A filled silhouette reads as a different icon family.
//
// 4.  EVERY ICON IS A MINIATURE OF ITS CONCEPT, NOT AN ABSTRACT GLYPH. A boxplot icon is a tiny
//     boxplot. A heatmap icon is a shaded grid. Sort is stacked bars of decreasing width with an
//     arrow. A calculator is a keypad. A matrix is a bracketed grid. Bootstrap is a histogram with
//     a loop arrow. If you cannot draw the thing, draw what it does to the data — never reach for
//     a generic gear or star.
//
// 5.  RELATED TOOLS SHARE VISUAL DNA. Build the family's base shape once as a constant, then vary
//     it with a small badge. The bases below are the vocabulary:
//       CURVE      every distribution and every test on a mean (badge: 1, 2, Z, N, t, F, χ², …)
//       FIT        every regression (points with a fitted line through them)
//       CAL        every date/time tool
//       SHEET      every whole-worksheet operation
//       BRACKETS   every matrix operation
//       HIST       every resampling / frequency tool
//       AXES       every plot that is drawn against axes
//     Family resemblance is the point: 1-Sample t and 2-Sample t must look like siblings, and
//     differ only by the badge.
//
// 6.  THE 1 / 2 BADGE CONVENTION. Where two tools differ only in sample count (1-Sample t vs
//     2-Sample t, 1 Proportion vs 2 Proportions, 1-Sample Poisson Rate vs 2-Sample), the icons are
//     identical apart from a numeral badge. Do not invent a second scheme for a new pair.
//
// 7.  NO emoji, no raster images, no icon-font dependency, no external file — inline SVG strings in
//     this module only.
//
// 8.  PARENTS AND CATEGORIES GET NO ICON. A submenu host ("Merge Worksheets ▸", "Basic Statistics")
//     renders an empty slot, so its label still aligns with its siblings'. Only leaves are keyed.
//
// Check any addition in the Icon Gallery (Window > Icon Gallery, or #icons) in BOTH themes before
// calling it done — a wrong stroke weight or a stray fill is obvious there and invisible in a menu.

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

/** Wraps an icon body in the one root element every icon shares. */
const svg = (body) =>
  `<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

/** A data point / accent dot. One of the two permitted fills (rule 3). */
const dot = (x, y, r = 0.95) => `<circle cx="${x}" cy="${y}" r="${r}" fill="currentColor" stroke="none"/>`;

/** A letter or numeral badge, top-right by default. The other permitted fill (rule 3). */
const badge = (text, x = 12.6, y = 5.4, size = 7) =>
  `<text x="${x}" y="${y}" font-family="'IBM Plex Sans', system-ui, sans-serif" font-size="${size}" font-weight="600" text-anchor="middle" fill="currentColor" stroke="none">${text}</text>`;

/** A vertical bar rising from the baseline — the unit of every bar/histogram icon. */
const bar = (x, top, bottom = 13.25) => `M${x} ${bottom}V${top}`;

// ---------------------------------------------------------------------------
// family bases (rule 5)
// ---------------------------------------------------------------------------

/** L-shaped plot axes. */
const AXES = '<path d="M2.5 1.9v11.6h11.75"/>';
/** The baseline alone, for icons that need no y axis. */
const FLOOR = '<path d="M1.75 13.25h12.5"/>';
/** The bell curve on its baseline: every distribution, every test on a mean. */
const CURVE = '<path d="M1.6 12.4c3.1 0 2.5-8.4 6.4-8.4s3.3 8.4 6.4 8.4"/><path d="M1.6 12.4h12.8"/>';
/** An S-curve through its own inflection: everything logistic (fit, CDF, ordinal/binary response). */
const SIGMOID = '<path d="M3.9 12.4c2.6 0 3-4.15 4.4-4.15s1.8-4.15 4.4-4.15"/>';
/** Points with a fitted line through them: every regression. */
const FIT = `${AXES}<path d="M4.4 11.9 13 4.9"/>${dot(5.2, 10.4)}${dot(8, 8.9)}${dot(10.8, 6.2)}`;
/** A calendar: every date/time tool. */
const CAL = '<rect x="2" y="3.4" width="12" height="10.6" rx="1"/><path d="M2 6.9h12"/><path d="M5.25 1.9v3M10.75 1.9v3"/>';
/** A worksheet: every operation on a whole worksheet. */
const SHEET = '<rect x="1.9" y="2.6" width="12.2" height="10.8" rx="1"/><path d="M1.9 6.1h12.2M6.3 2.6v10.8"/>';
/** A narrower worksheet, leaving the right third free for a mark. */
const SHEET_N = '<rect x="1.9" y="2.6" width="8.4" height="10.8" rx="1"/><path d="M1.9 6.1h8.4M5.4 2.6v10.8"/>';
/** Matrix brackets: every matrix operation. */
const BRACKETS = '<path d="M5 2.1H2.6v11.8H5M11 2.1h2.4v11.8H11"/>';
/** The 2×2 of cells inside the brackets. */
const CELLS = `${dot(6.4, 5.9)}${dot(9.6, 5.9)}${dot(6.4, 10.1)}${dot(9.6, 10.1)}`;
/** A small histogram: every resampling and frequency tool. */
const HIST = `${FLOOR}<path d="${bar(3.6, 9.6)}${bar(6.4, 6.1)}${bar(9.2, 4.4)}${bar(12, 8.4)}"/>`;
/** The width of a distribution, measured below its baseline: the variance tests. Deliberately
 *  OUTSIDE the curve — drawn inside it reads as a crossbar and the icon collapses onto t1/t2. */
const SPREAD = '<path d="M3.6 14.2h8.8M3.6 13.2v2M12.4 13.2v2"/>';
/** The resample loop: draw again from the same data. Kept inside the box — an arc that leaves the
 *  viewBox renders as a clipped fragment, which is what the first version did. */
const RESAMPLE_LOOP = '<path d="M13.4 4.4a3 3 0 1 1-3-3"/><path d="M10.1 3.1 11.4 1.4l1.7 1.1"/>';
/** A page with a folded corner. */
const PAGE = '<path d="M3.4 13.9V2.1h4.9L12.1 5.9v8z"/><path d="M8.3 2.1v3.8h3.8"/>';

// ===========================================================================================
// FILE
// ===========================================================================================

const FILE_ICONS = {
  // A worksheet plus a plus: a new grid.
  'new-worksheet': svg('<rect x="1.9" y="2.6" width="9" height="10.8" rx="1"/><path d="M1.9 6.1h9M5.5 2.6v10.8"/><path d="M13.4 8.9v4.4M11.2 11.1h4.4"/>'),
  // Two sheets plus a plus: a project holds several worksheets.
  'new-project': svg('<path d="M4.4 4.6V2.2h7.7v7.4"/><rect x="1.9" y="4.6" width="7.6" height="8.8" rx="1"/><path d="M13.4 9.4v4.2M11.3 11.5h4.2"/>'),
  open: svg('<path d="M1.9 12.9V4.2a.8.8 0 0 1 .8-.8h3.5l1.5 2h5.6a.8.8 0 0 1 .8.8v6.7a.8.8 0 0 1-.8.8H2.7a.8.8 0 0 1-.8-.8z"/>'),
  // A recently opened file: a page with the clock hand that "recent" means.
  'recent-file': svg(`${PAGE}<path d="M6.1 8.4v2.4l1.9 1.2"/>`),
  // The classic save shape: a shutter over a label.
  'save-project': svg('<path d="M2.4 3.1a1 1 0 0 1 1-1h7.9l2.3 2.3v8.5a1 1 0 0 1-1 1H3.4a1 1 0 0 1-1-1z"/><path d="M5.2 2.1v3.7h5.4V2.1M5.2 13.9v-3.6h5.4v3.6"/>'),
  // The same shutter, smaller, with the arrow of "somewhere else".
  'save-project-as': svg('<path d="M1.8 2.9a.8.8 0 0 1 .8-.8h6.5l1.9 1.9v6.4a.8.8 0 0 1-.8.8H2.6a.8.8 0 0 1-.8-.8z"/><path d="M4.2 2.1v3h4.1v-3"/><path d="M9.4 13.2h5M12.7 11.5l1.7 1.7-1.7 1.7"/>'),
  // A page leaving the app: the report that goes out to someone else.
  'export-report': svg('<path d="M2.6 13.9V2.1h4.7l3 3v1.9"/><path d="M7.3 2.1v3h3"/><path d="M2.6 13.9h5.1"/><path d="M11.6 14V8.2M9.4 10.4l2.2-2.2 2.2 2.2"/>'),
  print: svg('<path d="M4.4 6.1V2.1h7.2v4"/><path d="M4.4 12.4H2.9a1 1 0 0 1-1-1V7.1a1 1 0 0 1 1-1h10.2a1 1 0 0 1 1 1v4.3a1 1 0 0 1-1 1h-1.5"/><path d="M4.4 9.9h7.2v4H4.4z"/>'),
  // A page with lines of prose on it.
  'project-description': svg(`${PAGE}<path d="M5.6 8.4h4.4M5.6 10.9h3"/>`),
  // Sliders: the app's settings.
  options: svg('<path d="M2.4 4.6h11.2M2.4 11.4h11.2"/><circle cx="6.1" cy="4.6" r="1.9"/><circle cx="10.4" cy="11.4" r="1.9"/>'),
  exit: svg('<path d="M9.9 2.4H3.6a.8.8 0 0 0-.8.8v9.6a.8.8 0 0 0 .8.8h6.3"/><path d="M7.6 8h6.6M11.9 5.7 14.2 8l-2.3 2.3"/>'),
};

// ===========================================================================================
// EDIT
// ===========================================================================================

const EDIT_ICONS = {
  undo: svg('<path d="M2.4 5.4h7.1a3.9 3.9 0 0 1 0 7.8H5.1"/><path d="M5.1 2.4 2.1 5.4l3 3"/>'),
  redo: svg('<path d="M13.6 5.4H6.5a3.9 3.9 0 0 0 0 7.8h4.4"/><path d="M10.9 2.4l3 3-3 3"/>'),
  // An eraser taken across a cell: clear the contents, keep the cell.
  clear: svg('<path d="M2.1 13.4h5.4"/><path d="M9.9 11.4 5.4 6.9l3.6-3.6a1 1 0 0 1 1.4 0l3.1 3.1a1 1 0 0 1 0 1.4z"/><path d="M5.4 6.9 2.6 9.7a1 1 0 0 0 0 1.4l2.3 2.3h2.6l2.4-2"/>'),
  // A row lifted out of the grid: delete removes the cells themselves.
  delete: svg('<path d="M2.4 4.4h11.2"/><path d="M6.1 4.4V2.6h3.8v1.8"/><path d="M3.9 4.4l.8 8.6a1 1 0 0 0 1 .9h4.6a1 1 0 0 0 1-.9l.8-8.6"/>'),
  copy: svg('<rect x="5.6" y="5.6" width="8.4" height="8.4" rx="1"/><path d="M11.4 5.6V3a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v7.4a1 1 0 0 0 1 1h2.6"/>'),
  cut: svg('<path d="M4.4 4.1 11.9 13M11.6 4.1 4.1 13"/><circle cx="3.4" cy="12.6" r="1.8"/><circle cx="12.6" cy="12.6" r="1.8"/>'),
  paste: svg('<path d="M6.1 2.9H4.4a1 1 0 0 0-1 1v9.1a1 1 0 0 0 1 1h7.2a1 1 0 0 0 1-1V3.9a1 1 0 0 0-1-1H9.9"/><rect x="6.1" y="1.9" width="3.8" height="2.4" rx=".7"/><path d="M5.9 8.1h4.2M5.9 10.9h2.8"/>'),
  // The whole grid inside a selection frame.
  'select-all': svg('<rect x="2.1" y="2.1" width="11.8" height="11.8" rx="1"/><path d="M2.1 6.6h11.8M2.1 10.1h11.8M6.4 2.1v11.8M10.1 2.1v11.8"/>'),
  // A dialog panel with the pencil of "open it again as it was".
  'edit-last-dialog': svg('<rect x="1.9" y="2.6" width="12.2" height="10.8" rx="1"/><path d="M1.9 5.6h12.2"/><path d="M4.4 8.4h3.4M4.4 11.1h2.2"/><path d="M13.4 7.9 9.9 11.4l-1.6.4.4-1.6 3.5-3.5a.8.8 0 0 1 1.2 1.2z"/>'),
};

// ===========================================================================================
// DATA — 25 operations, conditional formatting, and the utility items
// ===========================================================================================

const DATA_ICONS = {
  // ----- take part of a worksheet out -----
  // Rows picked out of the grid into a smaller grid.
  subset: svg(`${SHEET_N}<path d="M9.4 8.1h4.7M11.8 5.9v4.4"/><path d="M2.4 8.6h2.4"/>`),
  // One worksheet becoming two.
  'split-worksheet': svg('<rect x="1.9" y="2.4" width="5.4" height="11.2" rx="1"/><path d="M8.9 4.6h5.2M8.9 8h5.2M8.9 11.4h5.2"/><path d="M12.4 2.9l1.7 1.7-1.7 1.7M12.4 9.7l1.7 1.7-1.7 1.7"/>'),

  // ----- bring worksheets together -----
  // Two frames meeting on a shared key column.
  'merge-match': svg('<path d="M2.1 3.4h4.4v9.2H2.1zM9.5 3.4h4.4v9.2H9.5"/><path d="M6.5 8h3"/><path d="M4.3 3.4v9.2M11.7 3.4v9.2"/>'),
  // Two frames set flush against each other.
  'merge-side-by-side': svg('<path d="M2.1 3.4h5.4v9.2H2.1zM8.5 3.4h5.4v9.2H8.5z"/><path d="M2.1 6.4h5.4M8.5 6.4h5.4"/>'),
  // One frame landing under another.
  'stack-worksheets': svg('<path d="M2.6 2.1h10.8v4.4H2.6zM2.6 9.5h10.8v4.4H2.6z"/><path d="M8 7.1v1.8"/><path d="M6.9 7.8 8 8.9l1.1-1.1"/>'),

  // ----- reorder / thin out -----
  // Bars of decreasing width with the arrow of the sort direction.
  sort: svg('<path d="M2.1 3.9h8.2M2.1 8h5.6M2.1 12.1h3"/><path d="M13.1 3.4v9.2M11.2 10.7l1.9 1.9 1.9-1.9"/>'),
  // The same bars, numbered rather than reordered.
  rank: svg(`<path d="M5.4 3.9h8.7M5.4 8h6.1M5.4 12.1h4.1"/>${badge('1', 2.6, 5.4, 6)}${badge('2', 2.6, 9.5, 6)}${badge('3', 2.6, 13.6, 6)}`),
  // A row struck out of the grid.
  'delete-rows': svg('<rect x="1.9" y="2.6" width="12.2" height="10.8" rx="1"/><path d="M1.9 6.1h12.2M1.9 9.9h12.2"/><path d="M3.9 6.9l8.2 2.2M12.1 6.9 3.9 9.1"/>'),
  // A column lifted clean out of the grid.
  'erase-variables': svg('<path d="M1.9 2.6h12.2v10.8H1.9z"/><path d="M5.9 2.6v10.8M10.1 2.6v10.8"/><path d="M6.6 6.4l2.8 3.2M9.4 6.4l-2.8 3.2"/>'),

  // ----- copy (columns, worksheets, constants, matrices) -----
  'copy-columns': svg('<path d="M2.1 2.6h3.8v10.8H2.1z"/><path d="M10.1 2.6h3.8v10.8h-3.8z"/><path d="M6.6 8h2.8M8.1 6.6 9.5 8 8.1 9.4"/>'),
  'copy-worksheet': svg('<rect x="5.6" y="5.4" width="8.4" height="8.6" rx="1"/><path d="M5.6 8.4H14M8.9 5.4V14"/><path d="M11.4 5.4V2.9a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v7.5a1 1 0 0 0 1 1h2.6"/>'),
  // A worksheet column emptying into the K store.
  'column-to-constants': svg(`<path d="M2.1 2.6h3.8v10.8H2.1z"/><path d="M7.1 8h2.6M8.4 6.6 9.7 8 8.4 9.4"/>${badge('K', 12.6, 9.4, 8)}`),
  'constants-to-column': svg(`${badge('K', 3.4, 9.4, 8)}<path d="M6.3 8h2.6M7.6 6.6 8.9 8l-1.3 1.4"/><path d="M10.1 2.6h3.8v10.8h-3.8z"/>`),
  'constants-to-constants': svg(`${badge('K', 3.9, 9.9, 8)}<path d="M7.1 8h2.1M8.1 6.6 9.4 8 8.1 9.4"/>${badge('K', 12.4, 9.9, 8)}`),
  'matrices-to-matrices': svg(`${badge('M', 3.9, 9.9, 8)}<path d="M7.4 8h1.6M7.9 6.6 9.2 8 7.9 9.4"/>${badge('M', 12.4, 9.9, 8)}`),
  // A matrix opening out into columns, and the reverse.
  'matrix-to-columns': svg('<path d="M4.1 3.4H2.4v9.2h1.7M6.9 3.4h1.7v9.2H6.9"/><path d="M9.9 8h1.9M10.9 6.6 12.2 8l-1.3 1.4"/><path d="M13.1 3.4v9.2"/>'),
  'columns-to-matrix': svg('<path d="M2.9 3.4v9.2M5.1 3.4v9.2"/><path d="M6.9 8h1.9M7.9 6.6 9.2 8l-1.3 1.4"/><path d="M11.9 3.4h-1.7v9.2h1.7M14.1 3.4h-1.5"/><path d="M13.6 3.4h.5v9.2h-.5"/>'),

  // ----- reshape -----
  // Several columns poured into one tall column.
  'stack-columns': svg('<path d="M2.1 2.6h2.6v5.4H2.1zM5.9 2.6h2.6v5.4H5.9z"/><path d="M5.4 9.9v3.5M4.3 12.3l1.1 1.1 1.1-1.1"/><path d="M10.9 2.6h3v10.8h-3z"/>'),
  // Blocks of columns, each block stacking as a unit.
  'stack-blocks': svg('<path d="M2.1 2.4h2.4v4.1H2.1zM5.6 2.4H8v4.1H5.6z"/><path d="M2.1 9.5h2.4v4.1H2.1zM5.6 9.5H8v4.1H5.6z"/><path d="M10.4 3.9h3.5v8.2h-3.5z"/><path d="M8.9 4.6h1.1M8.9 11.4h1.1"/>'),
  // Rows becoming a single column.
  'stack-rows': svg('<path d="M2.1 3.4h5.4M2.1 6.1h5.4M2.1 8.9h5.4M2.1 11.6h5.4"/><path d="M8.6 8h1.9M9.6 6.6 10.9 8 9.6 9.4"/><path d="M12.1 2.9h2.1v10.2h-2.1z"/>'),
  // One column opening into several.
  'unstack-columns': svg('<path d="M2.1 2.6h3v10.8h-3z"/><path d="M6.1 8h2M7.1 6.6 8.4 8 7.1 9.4"/><path d="M9.4 2.6H12v5.4H9.4zM9.4 8.6H12V14H9.4z"/><path d="M12.9 2.6h1.2v5.4h-1.2zM12.9 8.6h1.2V14h-1.2z"/>'),
  // Rows and columns trading places.
  transpose: svg('<path d="M2.4 2.4h11.2v11.2H2.4z"/><path d="M2.4 6.1h11.2M6.1 2.4v11.2"/><path d="M9.6 4.1h2.6v2.6"/><path d="M12.2 4.1 4.1 12.2"/><path d="M6.6 12.2H4.1V9.6"/>'),

  // ----- recode / retype -----
  // Values on the left becoming other values on the right.
  'recode-numeric': svg(`${badge('12', 4.1, 6.6, 6.5)}${badge('34', 11.9, 12.9, 6.5)}<path d="M9.4 5.1h3.6M11.6 3.6l1.4 1.5-1.4 1.5"/><path d="M6.6 10.9H3.1M5.4 9.4 3.9 10.9l1.5 1.5"/>`),
  'recode-text': svg(`${badge('ab', 4.1, 6.6, 6.5)}${badge('cd', 11.9, 12.9, 6.5)}<path d="M9.4 5.1h3.6M11.6 3.6l1.4 1.5-1.4 1.5"/><path d="M6.6 10.9H3.1M5.4 9.4 3.9 10.9l1.5 1.5"/>`),
  'recode-datetime': svg('<rect x="1.9" y="3.9" width="8.2" height="8.2" rx="1"/><path d="M1.9 6.6h8.2M4.4 2.6v2.4M7.6 2.6v2.4"/><path d="M11.4 8.9h2.9M12.9 7.4l1.4 1.5-1.4 1.5"/>'),
  // A lookup table doing the recoding.
  'recode-conversion-table': svg('<rect x="2.1" y="2.9" width="11.8" height="10.2" rx="1"/><path d="M8 2.9v10.2M2.1 6.4h11.8M2.1 9.6h11.8"/><path d="M5.4 4.9h.1M10.6 4.9h.1M5.4 8h.1M10.6 8h.1"/>'),
  // A column's dtype swapping: numerals for letters.
  'change-type': svg(`<path d="M2.4 2.6h11.2v10.8H2.4z"/><path d="M8 2.6v10.8"/>${badge('1', 5.2, 10.4, 7.5)}${badge('A', 10.9, 10.4, 7.5)}`),

  // ----- date/time (the CAL family) -----
  'date-extract-numeric': svg(`${CAL}${badge('1', 8, 12.4, 7.5)}<path d="M10.4 10.1h1.9"/>`),
  'date-extract-text': svg(`${CAL}${badge('A', 8, 12.4, 7.5)}<path d="M10.4 10.1h1.9"/>`),
  // A calendar with the clock hand snapping to the hour.
  'date-round': svg('<rect x="1.9" y="3.4" width="9.2" height="8.2" rx="1"/><path d="M1.9 6.4h9.2M4.4 2.1v2.6M8.6 2.1v2.6"/><circle cx="11.6" cy="11.6" r="2.9"/><path d="M11.6 10.1v1.5l1.2.8"/>'),
  // Two text cells joining into one.
  concatenate: svg(`${badge('ab', 4.1, 6.6, 6.5)}${badge('cd', 4.1, 13.1, 6.5)}<path d="M7.9 4.6h1.6l1.4 3.4 1.4 3.4h1.6"/><path d="M7.9 11.4h1.6"/>`),

  // ----- conditional formatting: a cell being tinted by a rule -----
  'cf-greater': svg(`<rect x="1.9" y="4.9" width="6.2" height="6.2" rx="1"/>${dot(5, 8, 1.3)}<path d="M10.4 5.9l3 2.1-3 2.1"/>`),
  'cf-less': svg(`<rect x="7.9" y="4.9" width="6.2" height="6.2" rx="1"/>${dot(11, 8, 1.3)}<path d="M5.6 5.9l-3 2.1 3 2.1"/>`),
  'cf-equal': svg(`<rect x="1.9" y="4.9" width="6.2" height="6.2" rx="1"/>${dot(5, 8, 1.3)}<path d="M10.1 6.9h3.8M10.1 9.6h3.8"/>`),
  'cf-between': svg(`<path d="M2.4 4.4v7.2M13.6 4.4v7.2"/><rect x="5.9" y="5.4" width="4.2" height="5.2" rx="1"/>${dot(8, 8, 1.2)}`),
  // A cell holding the string being looked for.
  'cf-contains': svg(`<rect x="1.9" y="4.4" width="12.2" height="7.2" rx="1"/>${badge('ab', 6.4, 10.4, 6.5)}<path d="M9.9 6.9h2.6M9.9 9.4h1.6"/>`),
  // The top of a ranked column highlighted.
  'cf-top-n': svg(`<path d="M2.4 2.9h8.2"/><path d="M2.4 6.1h6.2M2.4 9.4h4.6M2.4 12.6h3.2"/><path d="M13.1 6.9V2.4M11.4 4.1l1.7-1.7 1.7 1.7"/>`),
  'cf-bottom-n': svg(`<path d="M2.4 2.9h3.2M2.4 6.1h4.6M2.4 9.4h6.2"/><path d="M2.4 12.6h8.2"/><path d="M13.1 8.1v4.5M11.4 10.9l1.7 1.7 1.7-1.7"/>`),
  // A run chart with its 3σ limits and the point outside them.
  'cf-sigma3': svg(`<path d="M1.9 3.4h12.2M1.9 12.6h12.2"/><path d="M1.9 8h12.2" stroke-dasharray="2 2"/>${dot(4.1, 9.4)}${dot(6.9, 6.6)}${dot(9.6, 9.1)}${dot(12.1, 2.4, 1.3)}`),
  // A boxplot with the outlier point it flags.
  'cf-iqr-outlier': svg(`<path d="M4.4 8H2.4M11.6 8h1.4"/><rect x="4.4" y="5.4" width="7.2" height="5.2" rx=".8"/><path d="M8 5.4v5.2"/>${dot(13.6, 8, 1.3)}`),
  // A Pareto: the vital few bars, one of them filled.
  'cf-pareto': svg(`${FLOOR}<path d="M3.4 13.25V4.1"/><path d="M6.1 13.25V6.4"/><path d="M8.8 13.25V9.4M11.5 13.25v-2.2"/><path d="M2.4 3.4l4.2 3.6 5.9 3.1"/>`),
  // The rule list.
  'cf-manage': svg('<path d="M2.4 4.4h6.2M2.4 8h6.2M2.4 11.6h6.2"/><rect x="10.4" y="2.9" width="3.2" height="3.2" rx=".8"/><rect x="10.4" y="9.9" width="3.2" height="3.2" rx=".8"/><path d="M10.6 7.4l1.4 1.4"/>'),
  'cf-clear-column': svg('<path d="M2.9 2.6h4.2v10.8H2.9z"/><path d="M9.4 5.4l4.2 5.2M13.6 5.4l-4.2 5.2"/>'),
  'cf-clear-all': svg('<path d="M1.9 2.6h12.2v10.8H1.9z"/><path d="M6.1 2.6v10.8M10.1 2.6v10.8M1.9 8h12.2"/><path d="M3.4 3.9l9.2 8.2M12.6 3.9 3.4 12.1"/>'),

  // ----- inspect / utility -----
  // The worksheet printed into the Session Window.
  'display-data': svg('<path d="M1.9 2.6h6.2v10.8H1.9z"/><path d="M1.9 6.1h6.2"/><path d="M10.1 4.4h3.8M10.1 7.1h3.8M10.1 9.9h3.8M10.1 12.6h2.4"/>'),
  'worksheet-info': svg(`<rect x="1.9" y="2.6" width="12.2" height="10.8" rx="1"/><path d="M1.9 6.1h12.2"/>${dot(4.6, 8.9, 1)}<path d="M4.6 11.9v-1.4"/><path d="M7.4 9.4h5.4M7.4 11.9h3.6"/>`),
  constants: svg(`${badge('K', 5.4, 11.4, 11)}<path d="M9.9 4.4h3.9M9.9 8h3.9M9.9 11.6h2.4"/>`),
  // A file arriving in the worksheet.
  'import-file': svg('<path d="M9.9 2.6h4.2v10.8H9.9"/><path d="M9.9 6.1h4.2"/><path d="M2.4 8h5.4M5.9 5.9 8 8l-2.1 2.1"/>'),
  // The worksheet's shape at a glance.
  'dataset-summary': svg(`${FLOOR}<path d="M3.4 13.25V6.4M6.1 13.25V3.4M8.8 13.25V8.4M11.5 13.25V5.4"/>`),
  'reload-worksheet': svg('<path d="M13.4 8a5.4 5.4 0 1 1-1.6-3.8"/><path d="M13.6 2.4v2.9h-2.9"/><path d="M5.9 8h4.2M8 5.9v4.2" stroke-width="1.2"/>'),
};

// ===========================================================================================
// CALC
// ===========================================================================================

/** The 26 distributions. Every one is the CURVE base plus its own badge or silhouette — the
 *  Random Data and Probability Distributions submenus share them, since each submenu's own items
 *  are all distinct from each other and the context is the flyout you are standing in. */
const DISTRIBUTION_ICONS = {
  'dist-normal': svg(`${CURVE}${badge('N')}`),
  // Two overlapping bells: a joint distribution.
  'dist-multivariate-normal': svg('<path d="M1.6 12.4c2.4 0 2-6.6 5-6.6s2.6 6.6 5 6.6"/><path d="M4.4 12.4c2.4 0 2-6.6 5-6.6s2.6 6.6 5 6.6"/><path d="M1.6 12.4h12.8"/>'),
  // Right-skewed, with the χ² badge.
  'dist-chi-square': svg(`<path d="M1.9 12.4c1.9 0 1.4-7.4 4.1-7.4 2.9 0 2.9 7.4 8.4 7.4"/><path d="M1.9 12.4h12.5"/>${badge('χ', 12.4, 5.9)}`),
  'dist-f': svg(`<path d="M1.9 12.4c1.9 0 1.4-7.4 4.1-7.4 2.9 0 2.9 7.4 8.4 7.4"/><path d="M1.9 12.4h12.5"/>${badge('F', 12.4, 5.9)}`),
  'dist-t': svg(`${CURVE}${badge('t')}`),
  // A rectangle: the flat density.
  'dist-uniform': svg(`${FLOOR}<path d="M3.4 12.4V5.4h7.2v7"/>${badge('U', 12.9, 4.9, 6.5)}`),
  // Two bars: success and failure.
  'dist-bernoulli': svg(`${FLOOR}<path d="${bar(5.4, 7.9)}${bar(10.6, 4.4)}"/>${badge('2', 12.9, 12.4, 6.5)}`),
  // A binomial's symmetric bar profile.
  'dist-binomial': svg(`${FLOOR}<path d="${bar(3.1, 10.4)}${bar(5.4, 6.4)}${bar(7.7, 4.4)}${bar(10, 6.4)}${bar(12.3, 10.4)}"/>`),
  // Bars falling away geometrically.
  'dist-geometric': svg(`${FLOOR}<path d="${bar(3.1, 3.4)}${bar(5.4, 6.4)}${bar(7.7, 8.9)}${bar(10, 10.6)}${bar(12.3, 11.9)}"/>`),
  // The same decay, delayed — the negative binomial's hump.
  'dist-negative-binomial': svg(`${FLOOR}<path d="${bar(3.1, 9.9)}${bar(5.4, 4.9)}${bar(7.7, 6.4)}${bar(10, 8.9)}${bar(12.3, 11.1)}"/>`),
  // Drawing without replacement: bars over an urn's two kinds of ball.
  'dist-hypergeometric': svg(`${FLOOR}<path d="${bar(4.1, 8.9)}${bar(6.6, 4.9)}${bar(9.1, 7.4)}"/>${dot(12.6, 4.4, 1.2)}<circle cx="12.6" cy="8.1" r="1.4"/>`),
  // An arbitrary bar profile: whatever values and probabilities you name.
  'dist-discrete': svg(`${FLOOR}<path d="${bar(3.1, 7.4)}${bar(5.4, 4.4)}${bar(7.7, 9.9)}${bar(10, 5.9)}${bar(12.3, 8.6)}"/>`),
  // Equal bars over the integers.
  'dist-integer': svg(`${FLOOR}<path d="${bar(3.4, 6.4)}${bar(6.1, 6.4)}${bar(8.8, 6.4)}${bar(11.5, 6.4)}"/>${badge('n', 13.4, 4.9, 6)}`),
  // Counts: a right-skewed bar profile.
  'dist-poisson': svg(`${FLOOR}<path d="${bar(3.1, 8.4)}${bar(5.4, 4.4)}${bar(7.7, 5.9)}${bar(10, 8.9)}${bar(12.3, 11.4)}"/>${badge('λ', 13.4, 3.4, 6)}`),
  // Bounded on [0,1], leaning left.
  'dist-beta': svg(`<path d="M2.4 12.4c0-5.4 1.4-7.4 3.9-7.4 3.4 0 4.4 7.4 7.4 7.4"/><path d="M1.9 12.4h12.5"/>${badge('β', 12.9, 5.4)}`),
  // Heavier tails than the normal, same peak.
  'dist-cauchy': svg(`<path d="M1.6 12.4c3.9 0 2.4-8.4 6.4-8.4s2.5 8.4 6.4 8.4"/><path d="M1.6 12.4h12.8"/>${badge('C', 12.6, 5.4, 6.5)}`),
  // Pure decay from the axis.
  'dist-exponential': svg(`<path d="M2.4 3.4c0 6 2.4 9 11.5 9"/><path d="M1.9 12.4h12.5"/>${badge('e', 12.6, 5.4, 6.5)}`),
  'dist-gamma': svg(`<path d="M1.9 12.4c1.9 0 1.4-7.4 4.1-7.4 2.9 0 2.9 7.4 8.4 7.4"/><path d="M1.9 12.4h12.5"/>${badge('Γ', 12.4, 5.4)}`),
  // A sharp two-sided peak with CONCAVE sides — the double exponential's decay. Drawn concave on
  // purpose: with straight sides this is Triangular, and the two are neighbours in the menu.
  'dist-laplace': svg(`<path d="M1.9 12.4c3.4 0 5.1-8.5 6.1-8.5s2.7 8.5 6.1 8.5"/><path d="M1.9 12.4h12.5"/>`),
  // Skewed with the long tail to the right (largest extreme value).
  'dist-largest-extreme-value': svg(`<path d="M1.9 12.4c2.4 0 1.6-7.4 4.4-7.4 2.6 0 2.4 7.4 8.1 7.4"/><path d="M1.9 12.4h12.5"/><path d="M12.4 3.4h2M13.4 2.4v2"/>`),
  // The S of a logistic CDF — the one curve in the family drawn cumulative, which is what makes it
  // tell itself apart from the normal and the Cauchy at 16px.
  'dist-logistic': svg(`${AXES}${SIGMOID}`),
  'dist-loglogistic': svg(`<path d="M2.4 12.4c0-5.9 1.6-8 4.1-8 3.4 0 4.6 8 7.6 8"/><path d="M1.9 12.4h12.5"/>${badge('ll', 12.4, 5.4, 6)}`),
  // A right-skewed density starting at zero.
  'dist-lognormal': svg(`<path d="M2.1 12.4c0-5.4 1.4-7.4 3.6-7.4 3.4 0 4.1 7.4 8.4 7.4"/><path d="M1.9 12.4h12.5"/>${badge('ln', 12.4, 5.4, 6)}`),
  // The mirror of the largest-extreme-value skew.
  'dist-smallest-extreme-value': svg(`<path d="M14.1 12.4c-2.4 0-1.6-7.4-4.4-7.4-2.6 0-2.4 7.4-8.1 7.4"/><path d="M1.9 12.4h12.5"/><path d="M1.9 3.4h2"/>`),
  // Straight sides AND the three ticks its parameters sit on (min, mode, max) — the ticks are what
  // keep it out of Laplace's territory, since a bare triangle is what Laplace nearly draws too.
  'dist-triangular': svg(`<path d="M2.6 12.4 8 4.1l5.4 8.3"/><path d="M1.9 12.4h12.5"/><path d="M2.6 13.1v1.4M8 13.1v1.4M13.4 13.1v1.4" stroke-width="1.2"/>`),
  'dist-weibull': svg(`<path d="M2.1 12.4c0-4.9 1.9-6.9 4.4-6.9 3.4 0 4.1 6.9 7.6 6.9"/><path d="M1.9 12.4h12.5"/>${badge('W', 12.6, 5.4, 6.5)}`),
};

const CALC_ICONS = {
  // A keypad: the Calculator.
  calculator: svg(`<rect x="2.9" y="1.9" width="10.2" height="12.2" rx="1"/><path d="M4.9 4.4h6.2"/>${dot(5.4, 8, 0.8)}${dot(8, 8, 0.8)}${dot(10.6, 8, 0.8)}${dot(5.4, 11.1, 0.8)}${dot(8, 11.1, 0.8)}${dot(10.6, 11.1, 0.8)}`),
  // A column reduced to one number.
  'column-statistics': svg('<path d="M2.9 2.6h3.8v10.8H2.9z"/><path d="M8.1 8h2.4M9.4 6.6 10.7 8 9.4 9.4"/><path d="M12.1 6.9h2v2.2h-2z"/>'),
  // A row reduced to one number.
  'row-statistics': svg('<path d="M2.6 2.9v3.8h10.8V2.9z"/><path d="M8 8.1v2.4M6.6 9.4 8 10.7l1.4-1.3"/><path d="M6.9 12.1h2.2v2h-2.2z"/>'),
  // A spread being pulled onto one scale.
  standardize: svg(`${CURVE}<path d="M8 13.9V11"/><path d="M4.4 13.4h7.2" stroke-dasharray="1.6 1.6"/>`),

  // ----- make patterned data -----
  'patterned-numbers': svg(`${badge('1', 5.4, 6.4, 6.5)}${badge('2', 5.4, 10.4, 6.5)}${badge('3', 5.4, 14, 6.5)}<path d="M11.4 3.9v8.2M9.9 10.4l1.5 1.7 1.5-1.7"/>`),
  'patterned-arbitrary': svg(`${badge('7', 5.4, 6.4, 6.5)}${badge('2', 5.4, 10.4, 6.5)}${badge('9', 5.4, 14, 6.5)}<path d="M9.4 4.4h4.2M9.4 8h4.2M9.4 11.6h4.2"/>`),
  'patterned-text': svg(`${badge('A', 5.4, 6.4, 6.5)}${badge('B', 5.4, 10.4, 6.5)}${badge('C', 5.4, 14, 6.5)}<path d="M9.4 4.4h4.2M9.4 8h4.2M9.4 11.6h4.2"/>`),
  'patterned-datetime': svg(`${CAL}<path d="M4.6 9.4h2.2M9.2 9.4h2.2M4.6 11.9h2.2M9.2 11.9h2.2"/>`),
  'patterned-datetime-arbitrary': svg(`<rect x="1.9" y="3.4" width="9.2" height="8.2" rx="1"/><path d="M1.9 6.4h9.2M4.4 2.1v2.6M8.6 2.1v2.6"/>${dot(4.4, 8.9, 0.8)}${dot(8.4, 8.9, 0.8)}${dot(6.4, 10.4, 0.8)}<path d="M13.1 6.4v5.2M11.9 9.9l1.2 1.4 1.2-1.4"/>`),
  // A grid of x/y pairs.
  'mesh-data': svg(`<path d="M2.4 5.4h11.2M2.4 8h11.2M2.4 10.6h11.2M5.4 2.4v11.2M8 2.4v11.2M10.6 2.4v11.2"/>${dot(5.4, 5.4, 1)}${dot(10.6, 10.6, 1)}`),
  // A category column becoming 0/1 columns.
  'indicator-variables': svg(`${badge('A', 3.4, 6.4, 7)}${badge('B', 3.4, 13, 7)}<path d="M6.4 8h2.4M7.6 6.6 8.9 8 7.6 9.4"/>${badge('1', 12.4, 6.4, 7)}${badge('0', 12.4, 13, 7)}`),
  // The seed the generator starts from.
  'set-base': svg(`<rect x="2.4" y="2.4" width="11.2" height="11.2" rx="2"/>${dot(5.6, 5.6, 1.1)}${dot(10.4, 5.6, 1.1)}${dot(8, 8, 1.1)}${dot(5.6, 10.4, 1.1)}${dot(10.4, 10.4, 1.1)}`),

  // ----- random data -----
  // Rows drawn out of a column at random.
  'sample-columns': svg(`<path d="M2.4 2.6h4.2v10.8H2.4z"/><path d="M2.4 6.1h4.2M2.4 9.9h4.2"/><path d="M8.1 5.4h2.4M9.4 4 10.7 5.4 9.4 6.9"/><path d="M8.1 11.1h2.4M9.4 9.6l1.3 1.5-1.3 1.4"/><path d="M12.1 3.9h2v3h-2zM12.1 9.6h2v3h-2z"/>`),
  ...DISTRIBUTION_ICONS,

  // ----- resampling: the HIST family with a loop arrow -----
  'bootstrap-1sample': svg(`${HIST}${RESAMPLE_LOOP}${badge('1', 3.4, 4.9, 6.5)}`),
  'bootstrap-2sample': svg(`${HIST}${RESAMPLE_LOOP}${badge('2', 3.4, 4.9, 6.5)}`),
  // A histogram with the shuffled-label arrows.
  'randomization-1mean': svg(`${HIST}<path d="M8.4 2.4h4.4M11.4 1.1l1.4 1.3-1.4 1.4"/>${badge('1', 3.6, 3.9, 6.5)}`),
  'randomization-1proportion': svg(`${HIST}<path d="M8.4 2.4h4.4M11.4 1.1l1.4 1.3-1.4 1.4"/>${badge('%', 4.4, 3.9, 6.5)}`),
  'randomization-2means': svg(`${HIST}<path d="M8.4 2.4h4.4M11.4 1.1l1.4 1.3-1.4 1.4"/>${badge('2', 3.6, 3.9, 6.5)}`),

  // ----- matrices: the BRACKETS family -----
  // Columns arriving IN, and a matrix going OUT. The arrowheads point opposite ways: without them
  // these two were the same icon with a tick moved by a pixel.
  'matrix-import': svg(`${BRACKETS}${dot(6.4, 6.4)}${dot(9.6, 6.4)}<path d="M8 14.1V9.9M6.6 11.2 8 9.9l1.4 1.3"/>`),
  'matrix-export': svg(`${BRACKETS}${dot(6.4, 9.6)}${dot(9.6, 9.6)}<path d="M8 6.1v4.2M6.6 7.4 8 6.1l1.4 1.3"/>`),
  'matrix-transpose': svg(`${BRACKETS}${dot(6.4, 5.9)}${dot(9.6, 10.1)}<path d="M9.9 6.4 6.1 9.9"/><path d="M8.4 5.9h1.9v1.9M7.6 10.1H5.7V8.2"/>`),
  // A⁻¹.
  'matrix-invert': svg(`${BRACKETS}${dot(6.4, 6.9)}${dot(9.6, 6.9)}${dot(6.4, 10.6)}${dot(9.6, 10.6)}${badge('-1', 12.4, 4.4, 5.5)}`),
  'matrix-diagonal': svg(`${BRACKETS}${dot(6.4, 5.9)}${dot(9.6, 10.1)}`),
  'matrix-define': svg(`<path d="M4.4 3.4H2.4v9.2h2M8.1 3.4h1.9v9.2H8.1"/>${dot(6.2, 6.4, 0.85)}${dot(6.2, 9.6, 0.85)}<path d="M11.9 6.9h2.6M11.9 9.4h2.6"/>`),
  // A matrix reduced to its eigenvalue/vector pair.
  'matrix-eigen': svg(`<path d="M4.6 3.4H2.6v9.2h2M8.4 3.4h1.9v9.2H8.4"/>${dot(6.4, 6.4)}${dot(6.4, 9.6)}<path d="M11.9 8h2.4M13.1 6.6 14.4 8l-1.3 1.4"/>${badge('λ', 13.1, 5.1, 6)}`),
  'matrix-arithmetic': svg(`<path d="M4.4 3.9H2.6v8.2h1.8M8.1 3.9h1.8v8.2H8.1"/>${dot(6.2, 6.4, 0.85)}${dot(6.2, 9.6, 0.85)}<path d="M11.6 8h2.9M13.1 6.6v2.9"/>`),
  // The M-store window.
  'matrices-window': svg(`<rect x="1.9" y="2.6" width="12.2" height="10.8" rx="1"/><path d="M1.9 5.6h12.2"/>${badge('M', 5.4, 11.6, 7.5)}<path d="M8.9 8.9h3.6M8.9 11.4h2.4"/>`),
};

// ===========================================================================================
// STAT > BASIC STATISTICS — the CURVE family with 1 / 2 badges (rules 5 and 6)
// ===========================================================================================

const BASIC_STATS_ICONS = {
  // The descriptive table printed out.
  'display-descriptives': svg('<path d="M2.4 3.4h11.2M2.4 6.6h11.2M2.4 9.9h11.2M2.4 13.1h7.4"/><path d="M6.1 3.4v9.7"/>'),
  // The same statistics written back into columns.
  'store-descriptives': svg('<path d="M2.4 3.4h11.2M2.4 6.6h6.2M2.4 9.9h6.2"/><path d="M10.4 8.6h3.2v5.2h-3.2z"/><path d="M8.9 11.1h1.5"/>'),
  // Minitab's one-pager: a curve over a boxplot.
  'graphical-summary': svg(`<path d="M1.9 7.9c3 0 2.4-6 6.1-6s3.1 6 6.1 6"/><path d="M4.6 11.6H2.4M11.4 11.6h2.2"/><rect x="4.6" y="9.9" width="6.8" height="3.4" rx=".7"/><path d="M8 9.9v3.4"/>`),
  z1: svg(`${CURVE}${badge('Z')}`),
  t1: svg(`${CURVE}${badge('1')}`),
  t2: svg(`${CURVE}${badge('2')}`),
  // The same bell, with the paired-observation arrows.
  'paired-t': svg(`${CURVE}<path d="M10.9 3.4h3.4M12.9 2.1l1.4 1.3-1.4 1.4"/><path d="M14.3 6.4h-3.4M12.4 5.1 11 6.4l1.4 1.4"/>`),
  // A proportion: the filled share of a whole.
  prop1: svg(`<circle cx="7.4" cy="8" r="5.6"/><path d="M7.4 2.4v5.6l4.9 2.8"/>${badge('1', 14, 4.6, 6.5)}`),
  prop2: svg(`<circle cx="5.4" cy="8" r="3.9"/><path d="M5.4 4.1V8l3.4 1.9"/><circle cx="11.9" cy="8" r="3.9"/><path d="M11.9 4.1V8l-3.4 1.9"/>`),
  // A rate: counts over an interval.
  'poisson-rate-1': svg(`${FLOOR}<path d="${bar(3.4, 9.4)}${bar(6.1, 5.4)}${bar(8.8, 7.4)}"/>${badge('1', 12.9, 6.4)}`),
  'poisson-rate-2': svg(`${FLOOR}<path d="${bar(3.4, 9.4)}${bar(6.1, 5.4)}${bar(8.8, 7.4)}"/>${badge('2', 12.9, 6.4)}`),
  // Variance: the spread itself, marked out under the curve.
  var1: svg(`${CURVE}${SPREAD}${badge('1', 12.9, 5.4)}`),
  // Two spreads compared.
  var2: svg(`${CURVE}${SPREAD}${badge('2', 12.9, 5.4)}`),
  // Points hugging a line: correlation.
  correlation: svg(`${AXES}${dot(5, 11.1)}${dot(6.9, 9.4)}${dot(8.6, 8.1)}${dot(10.6, 6.4)}<path d="M4.4 11.9 12.4 5.4" stroke-dasharray="2 1.8"/>${badge('r', 13.4, 4.4, 6.5)}`),
  // The signed cross-product: two axes about their means.
  covariance: svg(`${AXES}<path d="M2.5 8h11.75M8.4 1.9v11.6" stroke-dasharray="2 1.8"/>${dot(5.4, 10.6)}${dot(11.1, 5.4)}${dot(10.4, 6.9)}${dot(6.1, 9.4)}`),
  // A probability plot: points on the reference line.
  'normality-test': svg(`${AXES}<path d="M4.1 12.1 13.1 4.1"/>${dot(5.4, 10.6, 0.85)}${dot(7.4, 9.1, 0.85)}${dot(9.4, 7.1, 0.85)}${dot(11.4, 5.6, 0.85)}`),
  // The one point that sits away from the rest.
  'outlier-test': svg(`${FLOOR}${dot(3.9, 10.4)}${dot(5.9, 9.6)}${dot(7.6, 10.6)}${dot(9.4, 9.9)}${dot(12.6, 3.9, 1.4)}<path d="M12.6 6.4v3.4" stroke-dasharray="1.6 1.6"/>`),
  // Observed bars against the fitted curve.
  'poisson-gof': svg(`${FLOOR}<path d="${bar(3.6, 9.6)}${bar(6.4, 5.9)}${bar(9.2, 7.9)}${bar(12, 11.1)}"/><path d="M2.4 11.4c1.4 0 1.9-6.4 4.4-6.4s3.4 8.4 7.1 8.4"/>`),
};

// ===========================================================================================
// STAT > REGRESSION — the FIT family (rule 5)
// ===========================================================================================

const REGRESSION_ICONS = {
  // The plain fitted line with its interval band.
  'fitted-line': svg(`${FIT}<path d="M4.4 13.4 13 6.4M4.4 10.4 13 3.4" stroke-dasharray="2 1.8" stroke-width="1.1"/>`),
  'fit-regression': svg(FIT),
  // Several candidate fits, one chosen.
  'best-subsets': svg(`${AXES}<path d="M4.4 12.4 13 8.9M4.4 12.9 13 6.4" stroke-dasharray="2 1.8" stroke-width="1.1"/><path d="M4.4 11.9 13 3.9"/>${dot(9.4, 7.4)}`),
  // Terms entering the model one at a time.
  stepwise: svg('<path d="M1.9 13.4h3.4v-3.4h3.4V6.6h3.4V3.1h3.4"/>'),
  // A curved fit through the points.
  'nonlinear-regression': svg(`${AXES}<path d="M4.1 12.4c2.4 0 3.4-1.4 4.6-3.9 1.2-2.5 2.4-3.9 4.6-3.9"/>${dot(5.4, 11.6)}${dot(8, 9.6)}${dot(11.4, 5.4)}`),
  // A fit with the specification limit it is tested against.
  'stability-study': svg(`${AXES}<path d="M4.1 4.4 13.1 10.9"/><path d="M2.5 12.6h11.75" stroke-dasharray="2 1.8"/>${dot(5.4, 5.4, 0.85)}${dot(8.4, 7.4, 0.85)}${dot(11.4, 9.4, 0.85)}`),
  // Errors measured perpendicular to the line, not vertically.
  'orthogonal-regression': svg(`${AXES}<path d="M4.4 12.1 13.1 4.4"/>${dot(6.4, 8.9, 0.85)}${dot(10.4, 8.4, 0.85)}<path d="M6.4 8.9 8.4 11.1M10.4 8.4l1.9 2.1" stroke-width="1.1"/>`),
  // Components extracted from the predictors, then fitted.
  'partial-least-squares': svg(`${AXES}<path d="M4.4 11.9 13 5.4"/><path d="M4.9 4.1h3.4M4.9 6.6h5.4" stroke-width="1.2"/>${dot(7.4, 9.1, 0.85)}${dot(10.6, 7.1, 0.85)}`),

  // ----- the logistic branch: the same points, an S-curve instead of a line -----
  // The logistic S-curve replaces the straight line, over the 0/1 response it is fitted to.
  'binary-fitted-line': svg(`${AXES}${SIGMOID}${dot(5.2, 12.4, 0.85)}${dot(6.6, 12.4, 0.85)}${dot(10.4, 4.1, 0.85)}${dot(11.9, 4.1, 0.85)}`),
  'binary-logistic': svg(`${AXES}${SIGMOID}${badge('2', 13.4, 4.4, 6.5)}`),
  // Ordered categories: rungs of increasing height.
  'ordinal-logistic': svg(`${AXES}<path d="M4.4 12.4h2.4V9.4h2.4V6.4h2.4V3.6h1.6"/>`),
  // Unordered categories: separate marks.
  'nominal-logistic': svg(`${AXES}<path d="M4.4 11.4h2.2M7.9 5.9h2.2M11.4 8.6h2.2"/>${dot(5.5, 8.9, 0.85)}${dot(9, 11.9, 0.85)}${dot(12.5, 4.4, 0.85)}`),
  // Counts fitted by a rising curve.
  'poisson-regression': svg(`${AXES}<path d="M4.1 12.6c4.9 0 5.4-3.4 9-8.6"/>${dot(5.9, 12.1, 0.85)}${dot(9.4, 9.6, 0.85)}${dot(12.1, 5.4, 0.85)}`),
};

// ===========================================================================================
// STAT > ANOVA — group means, and the model-driven items downstream of a fit
// ===========================================================================================

const ANOVA_ICONS = {
  // Three group means with their intervals: the one-way picture.
  'one-way': svg(`${FLOOR}<path d="M4.4 4.9v6.2M8 3.4v6.2M11.6 6.4v6.2"/><path d="M3.4 4.9h2M7 3.4h2M10.6 6.4h2M3.4 11.1h2M7 9.6h2M10.6 12.6h2"/>`),
  // Two spreads set against each other.
  'equal-variances': svg(`${FLOOR}<path d="M4.4 3.9v8.2M11.6 6.4v5.7"/><path d="M2.9 3.9h3M2.9 12.1h3M10.1 6.4h3M10.1 12.1h3"/>`),
  // A balanced design: every cell of the grid equally filled.
  'balanced-anova': svg(`<path d="M2.4 2.9h11.2v10.2H2.4z"/><path d="M2.4 6.4h11.2M2.4 9.6h11.2M6.1 2.9v10.2M9.9 2.9v10.2"/>${dot(4.2, 8, 0.8)}${dot(8, 8, 0.8)}${dot(11.8, 8, 0.8)}`),
  // Factors nested inside factors.
  'nested-anova': svg('<path d="M2.4 2.6v10.4h3.4"/><path d="M5.9 5.4v4.6h3.4"/><path d="M9.4 7.4v3.4h3.4"/><path d="M2.4 2.6h3.4M5.9 5.4h3.4M9.4 7.4h3.4"/>'),
  // Several responses tested together.
  manova: svg(`${AXES}<path d="M4.4 11.9 13 6.4M4.4 12.9 13 9.4M4.4 10.9 13 3.4"/>${badge('Y', 13.6, 2.9, 6)}`),

  // ----- the two fits -----
  // The general linear model: continuous and categorical terms in one design.
  'glm-fit': svg(`${AXES}<path d="M4.4 11.9 13 4.4"/>${dot(5.9, 10.6, 0.85)}${dot(9.4, 7.9, 0.85)}${dot(11.9, 5.4, 0.85)}<path d="M4.9 4.4h2.4" stroke-width="1.2"/>`),
  // The same fit with a random effect: a bracketed group of lines.
  'mixed-fit': svg(`${AXES}<path d="M4.4 12.1 13 5.4"/><path d="M4.4 13.4 13 6.9M4.4 10.6 13 4.1" stroke-dasharray="2 1.8" stroke-width="1.1"/>${dot(8.4, 8.6, 0.85)}`),

  // ----- items that work off a fitted model. Shared by the GLM and Mixed submenus: the same
  //       concept in each, and the flyout you are in says which model it uses. -----
  // Means compared pairwise, with the grouping bracket.
  comparisons: svg(`${FLOOR}<path d="M4.4 5.4v6.4M8 3.9v6.4M11.6 7.4v4.4"/><path d="M4.4 3.4h3.6M4.4 2.4v2M8 2.4v2"/>`),
  // A new x giving a fitted y with its interval.
  predict: svg(`${AXES}<path d="M4.1 12.1 11.1 5.4" stroke-dasharray="2 1.8"/><path d="M11.9 4.4v5.2M10.9 4.4h2M10.9 9.6h2"/>${dot(11.9, 6.9, 1.2)}`),
  // Main effects and an interaction, side by side.
  'factorial-plots': svg('<path d="M2.4 2.6v4.6h4.6M9.4 2.6v4.6h4.6"/><path d="M3.4 5.9l2.6-2.4M10.4 5.9l1.4-2.4 1.4 1.4"/><path d="M2.4 8.9v4.6h4.6M9.4 8.9v4.6h4.6"/><path d="M3.4 12.4l2.6-2.6M10.4 12.4l3-2.6M10.4 10.1l3 2.3"/>'),
  // Nested closed contours.
  'contour-plot': svg('<rect x="2.1" y="2.6" width="11.8" height="10.8" rx="1"/><path d="M4.4 11.4c0-3.4 1.6-5.4 3.6-5.4s3.6 2 3.6 5.4"/><path d="M6.1 11.4c0-2 .9-3.1 1.9-3.1s1.9 1.1 1.9 3.1"/>'),
  // A ruled surface in perspective.
  'surface-plot': svg('<path d="M1.9 10.9 8 13.4l6.1-2.5"/><path d="M1.9 10.9 5.4 4.9 8 8.4l3.1-4.4 3 6.9"/><path d="M8 8.4v5M5.4 4.9l2.6 3.5 3.1-4"/>'),
  // The optimiser's target: the peak of the response.
  'response-optimizer': svg(`${AXES}<path d="M4.1 12.4c2.4 0 2.9-7.4 5.4-7.4 1.9 0 2.6 3.4 3.6 5.9"/><path d="M9.5 4.9V1.9M8 3.4h3"/>`),
  // Two contour sets laid over each other with the feasible window between them.
  'overlaid-contour': svg('<rect x="2.1" y="2.6" width="11.8" height="10.8" rx="1"/><path d="M4.1 11.9c0-3.6 1.4-5.6 3.4-5.6s3.4 2 3.4 5.6"/><path d="M6.6 3.9c2.4 0 4.1 1.9 4.1 4.6" stroke-dasharray="2 1.8"/>'),

  // ----- the standalone plots -----
  'interval-plot': svg(`${FLOOR}<path d="M4.4 4.6v6.4M8 6.4v5.2M11.6 3.6v6.9"/><path d="M3.4 4.6h2M3.4 11h2M7 6.4h2M7 11.6h2M10.6 3.6h2M10.6 10.5h2"/>${dot(4.4, 7.8, 0.85)}${dot(8, 9, 0.85)}${dot(11.6, 7.1, 0.85)}`),
  'main-effects-plot': svg(`${AXES}<path d="M4.4 11.4 8 6.4l4.9 2.4"/><path d="M2.5 9h11.75" stroke-dasharray="2 1.8" stroke-width="1.1"/>${dot(4.4, 11.4, 0.85)}${dot(8, 6.4, 0.85)}${dot(12.9, 8.8, 0.85)}`),
  'interaction-plot': svg(`${AXES}<path d="M4.4 11.4 12.9 5.4"/><path d="M4.4 5.9 12.9 11.9"/>${dot(4.4, 11.4, 0.85)}${dot(12.9, 5.4, 0.85)}${dot(4.4, 5.9, 0.85)}${dot(12.9, 11.9, 0.85)}`),
  // Analysis of means: group means against decision limits.
  anom: svg(`<path d="M1.9 4.4h12.2M1.9 12.1h12.2" stroke-dasharray="2 1.8"/><path d="M1.9 8.4h12.2"/>${dot(4.4, 6.4)}${dot(8, 9.9)}${dot(11.6, 3.4, 1.3)}`),
};

// ===========================================================================================
// STAT > the remaining categories
// ===========================================================================================

const STAT_REST_ICONS = {
  // A contingency table with the χ² badge.
  'chi-square-association': svg(`<path d="M2.4 2.9h9.2v10.2H2.4z"/><path d="M2.4 6.4h9.2M2.4 9.6h9.2M7 2.9v10.2"/>${badge('χ', 13.4, 5.9, 7)}`),
  // History, then the dashed projection with its fan.
  forecast: svg(`${AXES}<path d="M4.1 11.4 6.4 8.9l2.4 2"/><path d="M8.8 10.9 13.4 5.4" stroke-dasharray="2 1.8"/><path d="M13.4 8.4 13.4 5.4h-3" stroke-width="1.1"/>`),
  // Points falling into groups.
  segmentation: svg(`${dot(4.4, 4.9)}${dot(6.4, 3.9)}${dot(5.4, 6.6)}<circle cx="5.4" cy="5.1" r="3.1" stroke-dasharray="2 1.8" stroke-width="1.1"/>${dot(10.6, 10.4)}${dot(12.4, 11.6)}${dot(11.1, 12.6)}<circle cx="11.4" cy="11.4" r="3.1" stroke-dasharray="2 1.8" stroke-width="1.1"/>`),
  // A branching tree.
  'decision-tree': svg('<path d="M8 2.4v3M8 5.4 4.4 8.9M8 5.4l3.6 3.5M4.4 8.9v2.4M11.6 8.9v2.4"/><path d="M3.1 11.4h2.6v2.4H3.1zM10.3 11.4h2.6v2.4h-2.6z"/>'),
  // Several trees.
  'random-forest': svg('<path d="M4.1 13.6V9.4M4.1 9.4 2.1 7.1M4.1 9.4l2-2.3M8 13.6V7.4M8 7.4 5.9 4.9M8 7.4l2.1-2.5M11.9 13.6V9.4M11.9 9.4 9.9 7.1M11.9 9.4l2-2.3"/>'),
  // Stacked additive stages.
  'gradient-boosting': svg(`${FLOOR}<path d="M3.4 13.25v-2.4M6.1 13.25V8.4M8.8 13.25V5.4M11.5 13.25V2.9"/><path d="M2.4 11.9c3.4 0 5.9-4.4 11.2-8.4" stroke-dasharray="2 1.8" stroke-width="1.1"/>`),
  // Models ranked against each other, the winner marked.
  automl: svg(`<path d="M2.4 4.4h7.4M2.4 8h5.4M2.4 11.6h3.9"/><path d="M11.6 3.4 12.9 6l2.6.4-1.9 1.8.5 2.6-2.5-1.3-2.5 1.3.5-2.6-1.9-1.8 2.6-.4z"/>`),
};

// ===========================================================================================
// GRAPH — every icon is a miniature of that chart type
// ===========================================================================================

const GRAPH_ICONS = {
  // The builder itself: an empty pair of axes with the panel you compose the chart in.
  'graph-builder': svg('<path d="M2.4 2.4v11.2h11.2"/><path d="M9.4 4.1h4.6M9.4 6.6h4.6M9.4 9.1h2.9"/><path d="M4.4 12.1V9.4M6.4 12.1V6.4"/>'),
  scatter: svg(`${AXES}${dot(5.4, 10.4)}${dot(7.4, 6.9)}${dot(9.4, 9.4)}${dot(11.4, 4.9)}${dot(12.9, 8.1)}`),
  // The same scatter, sized by a third variable.
  bubble: svg(`${AXES}<circle cx="5.9" cy="10.4" r="1.4"/><circle cx="9.4" cy="6.9" r="2.2"/><circle cx="12.6" cy="10.9" r="1"/>`),
  'line-plot': svg(`${AXES}<path d="M4.1 11.4 6.9 7.4l2.4 2.6 3.9-6.1"/>`),
  'bar-chart': svg(`${FLOOR}<path d="${bar(3.9, 8.4)}${bar(7, 4.4)}${bar(10.1, 6.4)}${bar(13.2, 9.9)}"/>`),
  'pie-chart': svg('<circle cx="8" cy="8" r="5.9"/><path d="M8 2.1V8l5 3.1"/>'),
  'area-graph': svg(`${AXES}<path d="M4.1 11.9 6.9 8.4l2.4 2.4 3.9-5.4v6.5z" fill="currentColor" fill-opacity=".18"/><path d="M4.1 11.9 6.9 8.4l2.4 2.4 3.9-5.4"/>`),
  // A line over a time axis with its tick marks.
  'time-series': svg(`${AXES}<path d="M4.1 10.4 6.4 6.9l2.4 3.1 4.4-6.6"/><path d="M5.4 13.5v1.1M8.4 13.5v1.1M11.4 13.5v1.1" stroke-width="1.2"/>`),
  histogram: svg(`${FLOOR}<path d="${bar(3.4, 10.4)}${bar(5.6, 6.9)}${bar(7.8, 3.9)}${bar(10, 5.9)}${bar(12.2, 9.4)}"/>`),
  // Whiskers, box, median line — and the outlier dot.
  boxplot: svg(`<path d="M4.6 8H2.4M11.4 8h2.2"/><rect x="4.6" y="4.9" width="6.8" height="6.2" rx=".8"/><path d="M8 4.9v6.2"/>`),
  // A shaded grid.
  heatmap: svg(`<rect x="2.4" y="2.4" width="11.2" height="11.2" rx="1"/><path d="M8 2.4v11.2M2.4 8h11.2"/><path d="M2.4 2.4h5.6V8H2.4z" fill="currentColor" fill-opacity=".35" stroke="none"/><path d="M8 8h5.6v5.6H8z" fill="currentColor" fill-opacity=".16" stroke="none"/>`),
  // The lower triangle of a correlation matrix.
  correlogram: svg(`<rect x="2.4" y="2.4" width="11.2" height="11.2" rx="1"/><path d="M2.4 6.1h11.2M2.4 9.9h11.2M6.1 2.4v11.2M9.9 2.4v11.2"/>${dot(4.2, 8, 1.1)}${dot(4.2, 11.8, 1.1)}${dot(8, 11.8, 1.1)}`),
  // A scatter reduced to shaded cells.
  'binned-scatter': svg(`${AXES}<path d="M5.4 13.5V4.9M8.4 13.5V4.9M11.4 13.5V4.9M2.5 7.9h11.75M2.5 10.9h11.75" stroke-width="1"/><path d="M5.4 7.9H8.4v3H5.4z" fill="currentColor" fill-opacity=".35" stroke="none"/><path d="M8.4 4.9h3v3h-3z" fill="currentColor" fill-opacity=".16" stroke="none"/>`),
  // Stacked dots over the value axis.
  dotplot: svg(`${FLOOR}${dot(4.1, 11.4, 1)}${dot(6.6, 11.4, 1)}${dot(6.6, 9, 1)}${dot(9.1, 11.4, 1)}${dot(9.1, 9, 1)}${dot(9.1, 6.6, 1)}${dot(11.6, 11.4, 1)}`),
  // Every observation shown, one column per group.
  'individual-value': svg(`${FLOOR}${dot(4.4, 10.4, 0.9)}${dot(4.4, 7.4, 0.9)}${dot(4.4, 5.4, 0.9)}${dot(8, 11.1, 0.9)}${dot(8, 8.6, 0.9)}${dot(11.6, 9.4, 0.9)}${dot(11.6, 6.4, 0.9)}${dot(11.6, 4.4, 0.9)}`),
  // A step function climbing to 1.
  ecdf: svg(`${AXES}<path d="M4.1 12.4h2.4V9.4h2.4V6.4h2.4V3.6h2.1"/>`),
  'probability-plot': svg(`${AXES}<path d="M4.1 12.1 13.1 4.1" stroke-dasharray="2 1.8"/>${dot(5.4, 11.1)}${dot(7.4, 9.4)}${dot(9.4, 6.9)}${dot(11.4, 5.4)}`),
  // A density curve with its shaded tail.
  'distribution-plot': svg(`${CURVE}<path d="M10.9 12.4c1.6 0 2.2-2.4 3.5-2.4v2.4z" fill="currentColor" fill-opacity=".28" stroke="none"/><path d="M10.9 12.4V9.9"/>`),
  // Stems on the left, leaves on the right.
  'stem-leaf': svg(`<path d="M5.4 2.9v10.2"/>${badge('1', 3.4, 6.4, 6.5)}${badge('2', 3.4, 10.4, 6.5)}${badge('3', 3.4, 14, 6.5)}<path d="M6.9 4.4h5.4M6.9 8h6.9M6.9 11.6h3.9"/>`),
  // A grid of little scatterplots.
  'matrix-plot': svg(`<rect x="2.4" y="2.4" width="11.2" height="11.2" rx="1"/><path d="M8 2.4v11.2M2.4 8h11.2"/>${dot(4.4, 6.4, 0.8)}${dot(6.1, 4.6, 0.8)}${dot(10.1, 6.4, 0.8)}${dot(11.9, 4.6, 0.8)}${dot(4.4, 12.1, 0.8)}${dot(6.1, 10.1, 0.8)}${dot(10.4, 11.4, 0.8)}`),
  // A scatter with a histogram along each margin.
  'marginal-plot': svg(`<path d="M2.4 4.9v8.7h8.7"/><path d="M4.4 3.4v1.5M6.9 1.9v3M9.4 2.9v2"/><path d="M12.6 11.6h1.5M12.6 8.9h3M12.6 6.4h1.9"/>${dot(5.1, 10.9, 0.9)}${dot(7.4, 8.4, 0.9)}${dot(9.6, 9.9, 0.9)}`),
  // One polyline per row across several parallel axes.
  'parallel-coords': svg('<path d="M3.4 2.6v10.8M8 2.6v10.8M12.6 2.6v10.8"/><path d="M3.4 10.4 8 5.4l4.6 3.4"/><path d="M3.4 6.4 8 9.9l4.6-4.4" stroke-dasharray="2 1.8" stroke-width="1.1"/>'),
  scatter3d: svg(`<path d="M2.4 4.4v7.2l6.1 2.4 5.1-2.4V4.4L8.5 1.9z"/>${dot(6.4, 6.9)}${dot(9.9, 9.4)}${dot(8.4, 4.9, 0.9)}`),
};

// ===========================================================================================
// WINDOW
// ===========================================================================================

const WINDOW_ICONS = {
  // A conversation.
  assistant: svg('<path d="M2.4 3.4h11.2v7.2H7.4l-3.4 2.9v-2.9H2.4z"/><path d="M5.4 6.9h5.4"/>'),
  cascade: svg('<path d="M2.4 5.4h7.6v7.6H2.4z"/><path d="M4.9 5.4V2.9h7.6v7.6H10"/>'),
  'close-all-windows': svg('<path d="M2.4 5.4h7.6v7.6H2.4z"/><path d="M4.9 5.4V2.9h7.6v7.6H10"/><path d="M4.4 7.4l3.4 3.4M7.8 7.4l-3.4 3.4"/>'),
  // The Session Window: a pinned log at the bottom of the screen.
  'session-window': svg('<rect x="1.9" y="2.4" width="12.2" height="11.2" rx="1"/><path d="M1.9 8.9h12.2"/><path d="M4.1 10.9h4.4M4.1 12.4h6.4"/>'),
  // Help > About: the conventional info circle.
  about: svg(`<circle cx="8" cy="8" r="6.1"/><path d="M8 7.4v4.1"/>${dot(8, 4.9, 1)}`),
  // The gallery of icons itself.
  'icon-gallery': svg(`<rect x="2.1" y="2.1" width="4.9" height="4.9" rx="1"/><rect x="9" y="2.1" width="4.9" height="4.9" rx="1"/><rect x="2.1" y="9" width="4.9" height="4.9" rx="1"/><rect x="9" y="9" width="4.9" height="4.9" rx="1"/>${dot(4.55, 4.55, 1)}${dot(11.45, 11.45, 1)}`),
};

// ===========================================================================================
// OUTPUT BLOCK MENU — the chevron menu on each block of a result window
// ===========================================================================================

const BLOCK_ICONS = {
  // The chevron on the block itself. Not a menu item, but it belongs to the same set.
  'block-chevron': svg('<path d="M4.4 6.4 8 10l3.6-3.6"/>'),
  // A page with the W of Word.
  'send-word': svg(`${PAGE}${badge('W', 7.6, 12.4, 7)}`),
  // A slide: a 16:9 frame on a stand.
  'send-powerpoint': svg('<rect x="1.9" y="2.9" width="12.2" height="8.2" rx="1"/><path d="M8 11.1v2.4M5.4 13.9h5.2"/><path d="M4.9 8.6l2.4-2.9 1.9 1.9 1.9-2.4"/>'),
  // A block dropping into a stack: the Report pane.
  'send-report': svg('<path d="M2.4 6.4h11.2v7.2H2.4z"/><path d="M2.4 9.4h11.2"/><path d="M8 1.9v3.4M6.4 3.9 8 5.4l1.6-1.5"/>'),
  // The clipboard pair, matching Edit > Copy so the two read as the same action.
  'copy-block': svg('<rect x="5.6" y="5.6" width="8.4" height="8.4" rx="1"/><path d="M11.4 5.6V3a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v7.4a1 1 0 0 0 1 1h2.6"/>'),
  // The same clipboard with a picture in it.
  'copy-picture': svg(`<rect x="5.6" y="5.6" width="8.4" height="8.4" rx="1"/><path d="M11.4 5.6V3a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v7.4a1 1 0 0 0 1 1h2.6"/><path d="M6.9 12.4l2.1-2.4 1.4 1.4 1.4-1.9"/>${dot(12.4, 7.9, 0.9)}`),
  // One sheet of paper leaving the printer, rather than File > Print's whole document.
  'print-block': svg('<path d="M4.9 5.9V2.4h6.2v3.5"/><path d="M4.9 11.9H3.4a1 1 0 0 1-1-1V7.4a1 1 0 0 1 1-1h9.2a1 1 0 0 1 1 1v3.5a1 1 0 0 1-1 1h-1.5"/><path d="M4.9 9.9h6.2v3.9H4.9z"/>'),
  // A block being lifted out of a stack.
  'delete-block': svg('<path d="M2.4 4.4h11.2"/><path d="M6.1 4.4V2.6h3.8v1.8"/><path d="M3.9 4.4l.8 8.6a1 1 0 0 0 1 .9h4.6a1 1 0 0 0 1-.9l.8-8.6"/><path d="M6.6 7.1v3.9M9.4 7.1v3.9" stroke-width="1.2"/>'),
  // Window > Report: the staged list.
  report: svg('<rect x="2.4" y="1.9" width="11.2" height="12.2" rx="1"/><path d="M4.9 5.4h6.2M4.9 8h6.2M4.9 10.6h3.9"/><path d="M2.4 3.9h11.2" stroke-width="1.2"/>'),
  // The Report pane's "Add text" button.
  'add-text': svg(`<path d="M2.9 4.4h7.2M6.5 4.4v8.2"/><path d="M12.4 8.4v5.2M9.8 11h5.2" stroke-width="1.3"/>`),
  // A drag handle for reordering staged blocks.
  'drag-handle': svg(`${dot(6.1, 4.4, 1)}${dot(9.9, 4.4, 1)}${dot(6.1, 8, 1)}${dot(9.9, 8, 1)}${dot(6.1, 11.6, 1)}${dot(9.9, 11.6, 1)}`),
};

// ===========================================================================================
// the registry
// ===========================================================================================

export const ICONS = {
  ...FILE_ICONS,
  ...EDIT_ICONS,
  ...DATA_ICONS,
  ...CALC_ICONS,
  ...BASIC_STATS_ICONS,
  ...REGRESSION_ICONS,
  ...ANOVA_ICONS,
  ...STAT_REST_ICONS,
  ...GRAPH_ICONS,
  ...WINDOW_ICONS,
  ...BLOCK_ICONS,
};

/** The order the groups are declared in, for the Icon Gallery. */
export const ICON_GROUPS = [
  { label: 'File', icons: FILE_ICONS },
  { label: 'Edit', icons: EDIT_ICONS },
  { label: 'Data', icons: DATA_ICONS },
  { label: 'Calc', icons: CALC_ICONS },
  { label: 'Stat — Basic Statistics', icons: BASIC_STATS_ICONS },
  { label: 'Stat — Regression', icons: REGRESSION_ICONS },
  { label: 'Stat — ANOVA', icons: ANOVA_ICONS },
  { label: 'Stat — Tables / Time Series / Multivariate / Predictive', icons: STAT_REST_ICONS },
  { label: 'Graph', icons: GRAPH_ICONS },
  { label: 'Window', icons: WINDOW_ICONS },
  { label: 'Output block menu', icons: BLOCK_ICONS },
];

/**
 * The SVG markup for a named icon, or '' when the name is missing or unknown — the caller still
 * renders its 16px slot, so an unassigned item's label stays in the same column as every other.
 */
export function getIcon(name) {
  if (!name) return '';
  return ICONS[name] || '';
}

/** Whether a name is in the registry. Used by the gallery's coverage check. */
export function hasIcon(name) {
  return !!name && Object.prototype.hasOwnProperty.call(ICONS, name);
}

/** Every registered name, in declaration order. */
export function iconNames() {
  return Object.keys(ICONS);
}
