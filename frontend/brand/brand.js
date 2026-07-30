// The Gosset brand assets, as the app consumes them.
//
// mark.svg and logo.svg are the source of truth on disk and are fetched, not duplicated here — one
// place to edit the geometry. They are INLINED into the DOM rather than used as <img src>, for two
// reasons that both matter:
//
//   - `stroke="currentColor"` only resolves against the surrounding document. An <img> renders in its
//     own isolated context, where currentColor falls back to black — so the mark would be invisible
//     on a dark menu bar and unthemeable everywhere.
//   - logo.svg's wordmark is live <text> in IBM Plex Sans. An <img> gets no access to the page's
//     webfont and would silently render the name in a system sans instead.

// version.js is GENERATED from desktop/package.json (the one source of truth) — never edit the
// number here or in that file; change package.json and run `npm run stamp` in desktop/.
import { VERSION } from './version.js';

const NAME = 'Gosset';

/** Named for William Sealy Gosset, who published the t-distribution as "Student" in 1908. */
const NAMESAKE = 'Named for W. S. Gosset — “Student”, 1908';
/** Where About's "Release notes" link and the updater's manual-download fallback point. */
const REPO_URL = 'https://github.com/safilo19/personal-analytics-mcp';
const CREDITS = 'FastAPI · pandas · SciPy · statsmodels · scikit-learn · Chart.js · Plotly · matplotlib';

const cache = new Map();

/** The raw SVG text of one brand asset, fetched once. */
async function asset(name) {
  if (!cache.has(name)) {
    cache.set(
      name,
      fetch(`/brand/${name}.svg`)
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${name}.svg: ${r.status}`))))
        .catch(() => ''), // a missing asset must not take the app down with it
    );
  }
  return cache.get(name);
}

export const version = VERSION;
export const name = NAME;
export const namesake = NAMESAKE;
export const credits = CREDITS;
export const repoUrl = REPO_URL;

/** Inline the full lockup (mark + wordmark) into an element. */
export async function mountLogo(host) {
  if (!host) return;
  const svg = await asset('logo');
  if (!svg) {
    host.textContent = NAME; // the name still has to appear if the asset did not load
    return;
  }
  host.innerHTML = svg;
}

/** Inline the mark alone into an element, at a given pixel size. */
export async function mountMark(host, size = 32) {
  if (!host) return;
  const svg = await asset('mark');
  if (!svg) return;
  host.innerHTML = svg;
  const el = host.querySelector('svg');
  if (el) {
    el.setAttribute('width', String(size));
    el.setAttribute('height', String(size));
  }
}

/** The mark's SVG text, for callers that want to place it themselves (the Icon Gallery). */
export function markSource() {
  return asset('mark');
}
