// Persisted user preferences (File > Options) and the File > Recent list, both in localStorage.
// Kept in its own module so windowManager can ask about motion without importing the app.

const SETTINGS_KEY = 'pa.settings.v1';
const RECENT_KEY = 'pa.recent.v1';
const RECENT_LIMIT = 8;

export const DEFAULTS = {
  decimals: 3, // decimal places shown for fractional numbers in results
  alpha: 0.05, // default significance level, prefilled into test forms
  animations: true, // master switch; prefers-reduced-motion overrides it either way
  theme: 'system', // 'light' | 'dark' | 'system' — first visit follows prefers-color-scheme
  menuHelp: true, // the hover help card on menu items (menuHelp.js) — on by default
  // Tooltips, hover highlight, zoom/pan and clickable legends on every chart. An app preference,
  // not project data: it lives here rather than in a .baproj so it follows the person, not the
  // file. Read through charts/theme.js::interactive() — never by a renderer directly.
  interactiveCharts: true,
};

export const THEME_MODES = ['light', 'dark', 'system'];

const listeners = new Set();

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : fallback;
  } catch {
    return fallback; // private mode / disabled storage / corrupt value — fall back to defaults
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage unavailable: settings still apply for this session, they just won't persist
  }
}

function clampSettings(raw) {
  const s = { ...DEFAULTS, ...raw };
  const decimals = Number(s.decimals);
  const alpha = Number(s.alpha);
  return {
    decimals: Number.isFinite(decimals) ? Math.min(8, Math.max(0, Math.round(decimals))) : DEFAULTS.decimals,
    alpha: Number.isFinite(alpha) && alpha > 0 && alpha < 1 ? alpha : DEFAULTS.alpha,
    animations: s.animations !== false,
    menuHelp: s.menuHelp !== false,
    interactiveCharts: s.interactiveCharts !== false,
    // The inline boot script in index.html reads this same key and applies the same fallback, so
    // a corrupt or missing value lands on 'system' before first paint and here identically.
    theme: THEME_MODES.includes(s.theme) ? s.theme : DEFAULTS.theme,
  };
}

let current = clampSettings(readJSON(SETTINGS_KEY, DEFAULTS));

export function get() {
  return { ...current };
}

export function update(patch) {
  current = clampSettings({ ...current, ...patch });
  writeJSON(SETTINGS_KEY, current);
  for (const fn of listeners) fn(get());
  return get();
}

export function onChange(fn) {
  listeners.add(fn);
}

export const prefersReducedMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

// The single question every animation asks. The OS/browser preference wins over the app setting:
// if the user asked for reduced motion at that level, no in-app checkbox should override it.
export function motionDisabled() {
  return prefersReducedMotion || !current.animations;
}

// ---------------------------------------------------------------------------
// File > Recent
// ---------------------------------------------------------------------------

// Entries: {kind: 'file' | 'gsheet' | 'project', name, url?}. Local files store only their name —
// a browser cannot reopen a path without the user picking the file again (see the menu tooltip).
export function recent() {
  const list = readJSON(RECENT_KEY, []);
  return Array.isArray(list) ? list.filter((e) => e && e.kind && e.name).slice(0, RECENT_LIMIT) : [];
}

export function addRecent(entry) {
  const list = recent().filter((e) => !(e.kind === entry.kind && (e.url || e.name) === (entry.url || entry.name)));
  list.unshift(entry);
  writeJSON(RECENT_KEY, list.slice(0, RECENT_LIMIT));
}

export function clearRecent() {
  writeJSON(RECENT_KEY, []);
}
