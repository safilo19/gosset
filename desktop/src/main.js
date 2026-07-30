'use strict';

/**
 * The Gosset desktop shell.
 *
 * It wraps the existing web app rather than replacing any of it: the frontend is the same unbuilt ES
 * modules the browser dev mode serves, still fetched over HTTP from the same FastAPI process, still
 * talking to the same REST API. The shell adds four things a browser tab cannot give it — a real
 * window, a bundled Python backend the user never has to start, native file dialogs, and a .gsp file
 * association.
 *
 * Startup order matters and is not negotiable:
 *
 *   1. single-instance lock      — a second launch must hand its argv to the first and exit
 *   2. sidecar (port, spawn, /health)
 *   3. window                    — created only once the backend answers, so the first paint is the
 *                                  app rather than a connection error
 *
 * Because the window is created late, the .gsp path a cold double-click arrives with has to be parked
 * (`pendingOpenPath`) and replayed once the renderer says it is ready. The renderer, not the main
 * process, decides when that is: app.js has to have registered its handler first or the message
 * lands in a page that cannot act on it.
 */

const { app, BrowserWindow, dialog, ipcMain, Menu, screen, shell } = require('electron');
const { existsSync, readFileSync, writeFileSync } = require('node:fs');
const { basename, dirname, join, resolve } = require('node:path');

const { Auth } = require('./auth');
const { log } = require('./log');
const { Sidecar } = require('./sidecar');
const { Updater } = require('./updater');
const { WindowState, MIN_WIDTH, MIN_HEIGHT } = require('./windowState');

const PROJECT_EXT = 'gsp';
const REPO_ROOT = resolve(__dirname, '..', '..');
const IS_DEV = process.argv.includes('--dev') || !app.isPackaged;
/** Where "Release notes" and the manual-download fallback point. */
const REPO_URL = 'https://github.com/safilo19/personal-analytics-mcp';

/** @type {BrowserWindow | null} */
let mainWindow = null;
/** @type {Sidecar | null} */
let sidecar = null;
/** @type {Updater | null} */
let updater = null;
/** @type {Auth | null} */
let auth = null;

/**
 * The renderer's "Check for updates automatically" preference, mirrored here.
 *
 * It LIVES in the renderer (localStorage, alongside the other File > Options settings, so it follows
 * the person and travels with nothing else). The main process needs it to decide whether to run the
 * background check, so the renderer pushes it over on startup and on every change. Defaulting to true
 * matters: the very first check happens 3s after the window appears, which can be before the renderer
 * has told us anything.
 */
let autoUpdateEnabled = true;

/** A .gsp waiting for the renderer to be able to receive it. */
let pendingOpenPath = null;
let rendererReady = false;

// ---------------------------------------------------------------------------
// the .gsp path, from however the OS chose to deliver it
// ---------------------------------------------------------------------------

/**
 * Pull a project path out of a process argv.
 *
 * Explorer appends the document path as a bare argument, so this cannot simply take the last item:
 * in development argv also carries `--dev`, and a packaged app can be launched with Chromium's own
 * switches. Requiring the extension AND that the file exists is what keeps `--dev` and
 * `--inspect=5858` from being mistaken for a project.
 */
function projectPathFromArgv(argv) {
  const candidates = argv
    .slice(1)
    .filter((arg) => !arg.startsWith('-'))
    .filter((arg) => arg.toLowerCase().endsWith(`.${PROJECT_EXT}`));
  for (const candidate of candidates) {
    const full = resolve(candidate);
    if (existsSync(full)) return full;
  }
  return null;
}

/** Read a .gsp and hand it to the renderer, or park it until the renderer can take it. */
function openProjectPath(path) {
  if (!path) return;
  log.info(`open project: ${path}`);
  if (!rendererReady || !mainWindow || mainWindow.isDestroyed()) {
    pendingOpenPath = path;
    return;
  }
  let text;
  try {
    text = readFileSync(path, 'utf8');
  } catch (err) {
    dialog.showMessageBox(mainWindow, {
      type: 'error',
      title: 'Could not open project',
      message: `Gosset could not read ${basename(path)}.`,
      detail: err.message,
    });
    return;
  }
  mainWindow.webContents.send('gosset:open-project', { path, name: basename(path), text });
}

// ---------------------------------------------------------------------------
// single instance
// ---------------------------------------------------------------------------

// Must run before anything expensive: the second process's only job is to hand over its argv and go.
// Without this, double-clicking a .gsp while Gosset is open starts a WHOLE second app — a second
// Electron, a second Python sidecar on a second port, with its own separate worksheets.
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', (_event, argv) => {
    log.info(`second instance: ${argv.join(' ')}`);
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
    openProjectPath(projectPathFromArgv(argv));
  });

  main();
}

// ---------------------------------------------------------------------------
// window
// ---------------------------------------------------------------------------

function appIcon() {
  const icon = join(__dirname, '..', 'build', 'icon.ico');
  return existsSync(icon) ? icon : undefined;
}

function createWindow(state, url) {
  const win = new BrowserWindow({
    ...state.bounds(screen),
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    title: 'Gosset',
    icon: appIcon(),
    // The app paints its own background before the stylesheet loads; matching the workspace token
    // means no white flash on the way in, which matters most in dark mode.
    backgroundColor: '#161616',
    // Nothing is shown until the first paint. Combined with creating the window only after /health,
    // the user sees the finished worksheet rather than a blank frame that fills in.
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      // The renderer is a web app talking to localhost over HTTP; it has no business with Node.
      // The preload bridge is the only channel, and it exposes named operations, never fs.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
    },
  });

  // The app's own menu bar is HTML (File/Edit/Data/Stat/Graph/Window, with its own accelerators), so
  // a native menu would be a duplicate set of File and Edit menus above it. Removing it also stops
  // Alt from stealing focus into a menu the app does not use.
  Menu.setApplicationMenu(null);
  win.setMenuBarVisibility(false);

  state.track(win);
  if (state.state.maximized) win.maximize();

  win.once('ready-to-show', () => win.show());

  // A .gsp double-click that reloads or crashes the page must not replay a stale project into it.
  win.webContents.on('did-start-navigation', (_e, _url, _frame, isMainFrame) => {
    if (isMainFrame) rendererReady = false;
  });

  // Any http(s) link in the app (the credits, a Google Sheets URL) belongs in the user's browser.
  // Without this a target=_blank opens a chromeless Electron window with no address bar.
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/i.test(target)) shell.openExternal(target);
    return { action: 'deny' };
  });

  win.on('closed', () => {
    mainWindow = null;
  });

  win.loadURL(url);
  return win;
}

/** Show a failure the user can act on, then exit. There is no window to put an error inside. */
function fatal(title, detail) {
  log.error(`${title}: ${detail}`);
  dialog.showErrorBox(
    title,
    `${detail}\n\n${log.path ? `Details were written to:\n${log.path}` : ''}`,
  );
  app.exit(1);
}

// ---------------------------------------------------------------------------
// IPC: the preload bridge's implementations
// ---------------------------------------------------------------------------

function registerIpc() {
  // The renderer announces that its open-project handler is attached. Everything before this point
  // would be delivered into a page that cannot act on it.
  ipcMain.on('gosset:renderer-ready', () => {
    rendererReady = true;
    if (pendingOpenPath) {
      const path = pendingOpenPath;
      pendingOpenPath = null;
      openProjectPath(path);
    }
  });

  ipcMain.handle('gosset:open-dialog', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
      title: 'Open',
      properties: ['openFile'],
      filters: [
        { name: 'Gosset Project', extensions: [PROJECT_EXT] },
        { name: 'Data', extensions: ['csv', 'xlsx', 'json'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    });
    if (canceled || !filePaths.length) return null;
    const path = filePaths[0];
    const isProject = path.toLowerCase().endsWith(`.${PROJECT_EXT}`);
    return {
      path,
      name: basename(path),
      // A project is JSON and is parsed in the renderer; a CSV or xlsx has to reach the backend's
      // upload endpoint as bytes, and base64 is how it crosses the IPC boundary intact. (A structured
      // clone of a Buffer would work too, but base64 is what apiClient already accepts.)
      text: isProject ? readFileSync(path, 'utf8') : null,
      base64: isProject ? null : readFileSync(path).toString('base64'),
    };
  });

  ipcMain.handle('gosset:save-dialog', async (_event, { defaultName, text }) => {
    const { canceled, filePath } = await dialog.showSaveDialog(mainWindow, {
      title: 'Save Project',
      defaultPath: defaultName,
      filters: [{ name: 'Gosset Project', extensions: [PROJECT_EXT] }],
    });
    if (canceled || !filePath) return null;
    writeFileSync(filePath, text, 'utf8');
    log.info(`saved project: ${filePath}`);
    return { path: filePath, name: basename(filePath) };
  });

  // The title bar is the one piece of window chrome the HTML cannot reach, so the renderer asks for
  // it. Kept in the shape Windows users expect: document first, app second.
  ipcMain.on('gosset:set-title', (_event, projectName) => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    mainWindow.setTitle(projectName ? `${projectName} — Gosset` : 'Gosset');
  });

  ipcMain.handle('gosset:show-item', (_event, path) => {
    // A report the user just exported: reveal it rather than opening it, so an unexpected
    // application never takes over the screen.
    if (path && existsSync(path)) shell.showItemInFolder(path);
    return null;
  });

  ipcMain.handle('gosset:open-path', async (_event, path) => {
    if (!path || !existsSync(path)) return { ok: false, error: 'That file is no longer there.' };
    const error = await shell.openPath(path);
    return error ? { ok: false, error } : { ok: true };
  });

  // ---------------------------------------------------------------------------
  // updater
  // ---------------------------------------------------------------------------

  ipcMain.on('gosset:updater-set-enabled', (_event, enabled) => {
    autoUpdateEnabled = enabled !== false;
    log.info(`updater: automatic checks ${autoUpdateEnabled ? 'on' : 'off'}`);
  });

  // The renderer's update listeners are attached. The first check fires 3s after the window is
  // created, which is sooner than the renderer finishes starting, so an offer made before this point
  // is parked rather than sent into a page that would drop it.
  ipcMain.on('gosset:updater-ready', () => {
    if (updater) updater.markRendererReady();
  });

  ipcMain.handle('gosset:updater-check', async (_event, { user = false } = {}) => {
    if (!updater) return { started: false, reason: 'unsupported' };
    await updater.check({ user });
    return { started: true };
  });

  ipcMain.handle('gosset:updater-download', async () => {
    if (!updater) return { started: false };
    await updater.download();
    return { started: true };
  });

  ipcMain.on('gosset:updater-snooze', () => {
    if (updater) updater.snooze();
  });

  // The renderer calls this only AFTER its own unsaved-work prompt has resolved — that ordering is the
  // whole guarantee that an update cannot eat someone's project. The main process deliberately does not
  // second-guess it: it has no idea what is unsaved, and a native dialog here would be a second,
  // uglier prompt asking the same question.
  ipcMain.handle('gosset:updater-install', () => {
    if (!updater) return { ok: false };
    return { ok: updater.install() };
  });

  ipcMain.handle('gosset:updater-info', () => ({
    currentVersion: app.getVersion(),
    supported: Boolean(updater && updater.supported),
    releasesUrl: `${REPO_URL}/releases`,
  }));

  // ---------------------------------------------------------------------------
  // account
  // ---------------------------------------------------------------------------

  // Every one of these returns the same shape — `auth.state()` — so the renderer has one way to
  // render itself and never has to reconcile a reply with what it already believed.
  ipcMain.handle('gosset:auth-state', () => (auth ? auth.state() : { configured: false, signedIn: false, profile: null }));

  ipcMain.handle('gosset:auth-sign-in', async () => {
    if (!auth) return { ok: false, error: 'Sign-in is unavailable in this build.' };
    try {
      return { ok: true, state: await auth.signIn() };
    } catch (err) {
      // Returned rather than thrown: a cancelled sign-in is an ordinary outcome, and an IPC rejection
      // would surface in the renderer as an opaque "Error invoking remote method".
      return { ok: false, error: String((err && err.message) || err) };
    }
  });

  ipcMain.handle('gosset:auth-sign-out', async () => {
    if (!auth) return { configured: false, signedIn: false, profile: null };
    return auth.signOut();
  });

  ipcMain.handle('gosset:auth-refresh', async () => {
    if (!auth) return { configured: false, signedIn: false, profile: null };
    return auth.refresh();
  });
}

// ---------------------------------------------------------------------------
// startup
// ---------------------------------------------------------------------------

async function main() {
  // Chromium's own cache/state alongside our log and window state, per user, no admin rights needed.
  const userDataDir = app.getPath('userData');
  log.init(userDataDir);
  log.info(`Gosset ${app.getVersion()} — electron ${process.versions.electron}, node ${process.versions.node}`);
  log.info(`packaged: ${app.isPackaged}  userData: ${userDataDir}`);

  // A cold double-click on a .gsp: the path is in this process's argv.
  pendingOpenPath = projectPathFromArgv(process.argv);
  if (pendingOpenPath) log.info(`launched with project: ${pendingOpenPath}`);

  await app.whenReady();

  // Constructed before the window so the account button can be drawn from a restored session on the
  // first paint, with no network and no flash of "Sign in" for someone who already is.
  auth = new Auth({ userDataDir, appPath: app.getAppPath() });
  log.info(`auth: ${auth.configured ? 'configured' : 'not configured'}; signed in: ${auth.state().signedIn}`);

  registerIpc();

  sidecar = new Sidecar({
    app,
    repoRoot: REPO_ROOT,
    // Reports are generated server-side and then downloaded; this is the staging directory. It must
    // be per-user and writable — the installed app directory is neither.
    outputDir: join(userDataDir, 'output'),
  });

  try {
    await sidecar.start();
  } catch (err) {
    fatal('Gosset could not start its analysis engine', err.message);
    return;
  }

  const state = new WindowState(userDataDir);
  mainWindow = createWindow(state, sidecar.baseUrl);

  // Started after the window exists, because every message it sends goes to a renderer. Its own first
  // check is 3s later and non-blocking, so nothing here delays the app being usable.
  updater = new Updater({
    getWindow: () => mainWindow,
    isEnabled: () => autoUpdateEnabled,
  });
  updater.start();

  if (IS_DEV) log.info(`dev mode — the same app is also at ${sidecar.baseUrl} in a browser`);
}

// ---------------------------------------------------------------------------
// shutdown
// ---------------------------------------------------------------------------

// Why the app is shutting down, in the log. Without these, a quit triggered by something other than
// the user closing the window (a failed startup, a lifecycle event firing earlier than expected) looks
// in the log exactly like a clean exit: the last line is whatever startup got to, and then nothing.
app.on('before-quit', () => log.info('lifecycle: before-quit'));
app.on('will-quit', () => log.info('lifecycle: will-quit'));
app.on('quit', (_event, code) => log.info(`lifecycle: quit (exit code ${code})`));

app.on('window-all-closed', () => {
  log.info('lifecycle: window-all-closed');
  // Windows/Linux: closing the window is quitting. (No macOS branch — this ships as a Windows app;
  // on macOS the convention is to stay resident, which would leave the sidecar running.)
  app.quit();
});

// will-quit rather than before-quit: this is the last point that is still guaranteed to run, and the
// kill is synchronous so the process cannot exit out from under it and orphan Python.
app.on('will-quit', () => {
  if (sidecar) sidecar.stop();
});

// A crash in the main process skips will-quit entirely, so the same cleanup is wired to process exit
// as a backstop. (The sidecar ALSO watches our pid from its side — belt and braces, because an
// orphaned sidecar holds a port and a few hundred MB with no window to close.)
process.on('exit', () => {
  if (sidecar) sidecar.stop();
});
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => {
    if (sidecar) sidecar.stop();
    app.exit(0);
  });
}
process.on('uncaughtException', (err) => {
  log.error(`uncaught: ${err.stack || err.message}`);
  if (sidecar) sidecar.stop();
  app.exit(1);
});
