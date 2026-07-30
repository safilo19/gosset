// Light/dark mode: resolving the preference, applying it to <html>, the menu-bar toggle, and
// telling the rest of the app when it changed.
//
// The preference lives in the ordinary settings object (File > Options > Theme), so it persists
// with everything else. What makes theming different from the other settings is that it has to be
// applied BEFORE first paint — otherwise opening the app in dark mode flashes white — so the
// inline boot script in index.html sets data-theme from that same localStorage key. This module
// takes over from it once the modules load.

import * as settings from './settings.js';

const darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

const listeners = new Set();
const toggles = new Set();

let applied = null; // the resolved theme currently on <html>: 'light' | 'dark'

export function systemPrefersDark() {
  return !!(darkQuery && darkQuery.matches);
}

// The stored mode ('light' | 'dark' | 'system') collapsed to what actually gets painted.
export function resolved() {
  const mode = settings.get().theme;
  if (mode === 'light' || mode === 'dark') return mode;
  return systemPrefersDark() ? 'dark' : 'light';
}

export function isDark() {
  return resolved() === 'dark';
}

// Subscribers re-style anything CSS variables cannot reach on their own — Chart.js defaults and
// the charts already on screen. Fired only when the painted theme really changed.
export function onChange(fn) {
  listeners.add(fn);
}

function syncToggles(theme) {
  for (const el of toggles) {
    el.setAttribute('aria-checked', theme === 'dark' ? 'true' : 'false');
    el.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
  }
}

// A ~180ms cross-fade of the whole UI, then the class comes straight back off: leaving a global
// transition installed makes every ordinary hover feel laggy. Reduced motion skips it entirely,
// which is the instant swap the design asks for.
let transitionTimer = null;

function withTransition(fn) {
  if (settings.motionDisabled()) {
    fn();
    return;
  }
  const root = document.documentElement;
  root.classList.add('theme-transition');
  fn();
  clearTimeout(transitionTimer);
  transitionTimer = setTimeout(() => root.classList.remove('theme-transition'), 200);
}

// `animate` is false for the very first application (nothing to cross-fade from) and true for a
// later switch.
export function apply({ animate = true } = {}) {
  const theme = resolved();
  const root = document.documentElement;

  if (theme === applied) {
    syncToggles(theme);
    return theme;
  }

  const swap = () => {
    root.setAttribute('data-theme', theme);
    // The boot script painted an inline background to cover the pre-CSS gap. The stylesheet is
    // parsed by now, so hand control back to it rather than keeping a second source of truth.
    root.style.backgroundColor = '';
    root.style.colorScheme = '';
  };

  if (applied === null || !animate) swap();
  else withTransition(swap);

  applied = theme;
  syncToggles(theme);
  for (const fn of listeners) fn(theme);
  return theme;
}

// ---------------------------------------------------------------------------
// the toggle control
// ---------------------------------------------------------------------------

// Stroke-style inline SVG — no icon font, no emoji. 24-unit viewBox scaled by CSS to 12px.
const SUN = `<svg class="theme-toggle-icon theme-toggle-icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" aria-hidden="true">
  <circle cx="12" cy="12" r="4.25" />
  <path d="M12 1.8v2.2M12 20v2.2M1.8 12h2.2M20 12h2.2M4.8 4.8l1.6 1.6M17.6 17.6l1.6 1.6M19.2 4.8l-1.6 1.6M6.4 17.6l-1.6 1.6" />
</svg>`;

const MOON = `<svg class="theme-toggle-icon theme-toggle-icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M20.2 14.8A8.6 8.6 0 0 1 9.2 3.8a7.6 7.6 0 1 0 11 11z" />
</svg>`;

// Turns an existing <button> into the switch. A real button already toggles on both Space and
// Enter and takes :focus-visible from the global rule, so no key handling is needed here.
export function mountToggle(button) {
  if (!button) return;
  button.classList.add('theme-toggle');
  button.type = 'button';
  button.setAttribute('role', 'switch');
  button.setAttribute('aria-label', 'Dark mode');
  button.innerHTML = `<span class="theme-toggle-track">${SUN}${MOON}<span class="theme-toggle-thumb"></span></span>`;
  toggles.add(button);
  syncToggles(resolved());

  button.addEventListener('click', () => {
    // Writing an explicit light/dark leaves "System" behind on purpose — the user just made a
    // choice, and it should stick when the OS flips later. System stays reachable in Options.
    settings.update({ theme: isDark() ? 'light' : 'dark' });
  });
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------

// Any settings write re-resolves; apply() no-ops unless the painted theme actually changed, so an
// unrelated change (decimals, alpha) costs nothing here.
settings.onChange(() => apply());

// Follow the OS while the mode is 'system'. resolved() already ignores the query for an explicit
// choice, so this listener stays installed and simply no-ops then.
if (darkQuery && darkQuery.addEventListener) darkQuery.addEventListener('change', () => apply());

apply({ animate: false });
