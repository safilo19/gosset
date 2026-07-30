// The desktop shell, as the app sees it — and a no-op everywhere else.
//
// The Electron preload exposes `window.gosset`. Every caller in the app goes through THIS module
// rather than touching that object, for one reason: the browser dev mode
// (`uvicorn backend.api:app` + localhost) has to keep working unchanged, and the way that stays true
// is that `available()` is false there and every function below has a defined browser behaviour.
//
// So the rule for anything added here: it either degrades to something sensible in a browser, or it
// does not belong in the app at all.

/** True only inside the Electron shell. */
export function available() {
  return Boolean(globalThis.window && window.gosset && window.gosset.isDesktop);
}

const bridge = () => (available() ? window.gosset : null);

/**
 * The native open dialog, or null when there isn't one.
 *
 * Returns `{path, name, text, base64}`: `text` for a project file, `base64` for a data file. A null
 * return means either "no desktop shell" or "the user cancelled" — both cases mean the caller should
 * do nothing, so they deliberately look the same.
 */
export async function openFileDialog() {
  const g = bridge();
  if (!g) return null;
  return g.openFileDialog();
}

/**
 * Write a project through the native save dialog. Returns `{path, name}`, or null if cancelled or if
 * there is no shell — the caller falls back to a blob download when `available()` is false.
 */
export async function saveProjectDialog(defaultName, text) {
  const g = bridge();
  if (!g) return null;
  return g.saveProjectDialog(defaultName, text);
}

/** Put the open project's name in the window title bar. Harmless no-op in a browser, where the
 *  document title already carries it. */
export function setTitle(projectName) {
  const g = bridge();
  if (g) g.setTitle(projectName || '');
}

/** Reveal an exported report in Explorer. */
export function showItemInFolder(path) {
  const g = bridge();
  if (g) g.showItemInFolder(path);
}

/**
 * Register the handler for a .gsp opened from outside the app — double-clicked in Explorer, whether
 * that launched Gosset or arrived at an already-open window.
 *
 * Calling this is ALSO what tells the main process the renderer can receive one; a project delivered
 * before this point is parked rather than dropped. So it must be called during app startup, after the
 * handler it is given is genuinely able to run.
 */
export function onOpenProject(handler) {
  const g = bridge();
  if (g) g.onOpenProject(handler);
}

/**
 * The auto-update channel, or null.
 *
 * Null in a browser, and that is the feature detect the whole update UI hangs off: File > Options hides
 * its update section, and `updates.js` wires up no listeners at all. A browser tab has no installer to
 * replace, so offering to update it would be a button that cannot work.
 */
export function updater() {
  const g = bridge();
  return g && g.updater ? g.updater : null;
}

/**
 * Google sign-in, or null.
 *
 * Null in a browser, which is the feature detect the account UI hangs off — the sign-in flow needs a
 * system browser and an OS keychain, neither of which a page can reach. Gosset is usable signed out by
 * design, so its absence removes a button and nothing else.
 */
export function auth() {
  const g = bridge();
  return g && g.auth ? g.auth : null;
}
