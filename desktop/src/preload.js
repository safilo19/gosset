'use strict';

/**
 * The only channel between the web app and the desktop shell.
 *
 * `window.gosset` is also the app's feature-detect: frontend/app.js checks for it and falls back to
 * the browser behaviour (an <input type=file> and a blob download) when it is absent, which is what
 * keeps `uvicorn backend.api:app` + localhost working exactly as before. So every method here has to
 * have a browser equivalent the app can degrade to — nothing in the app may become desktop-only.
 *
 * Deliberately narrow: named operations, never a filesystem. The renderer can ask to open a project
 * the user picked in a dialog; it cannot ask to read an arbitrary path. contextIsolation is on, so
 * this object is a bridge and not a shared global.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('gosset', {
  /** Present, and true, only in the desktop shell. The app branches on this. */
  isDesktop: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },

  /**
   * Native open dialog. Resolves to null if the user cancelled, otherwise
   * `{path, name, text, base64}` — `text` for a .gsp (parsed in the renderer), `base64` for a data
   * file (posted to the upload endpoint).
   */
  openFileDialog: () => ipcRenderer.invoke('gosset:open-dialog'),

  /** Native save dialog; writes `text` to the chosen path. Resolves to null if cancelled. */
  saveProjectDialog: (defaultName, text) =>
    ipcRenderer.invoke('gosset:save-dialog', { defaultName, text }),

  /** Set the window title bar. Pass a falsy name to reset it to plain "Gosset". */
  setTitle: (projectName) => ipcRenderer.send('gosset:set-title', projectName),

  /** Reveal a generated file in Explorer. */
  showItemInFolder: (path) => ipcRenderer.invoke('gosset:show-item', path),

  /** Open a generated file in whatever application owns its type. */
  openPath: (path) => ipcRenderer.invoke('gosset:open-path', path),

  /**
   * Register the handler for a project arriving from outside the app — a .gsp double-clicked in
   * Explorer, either as the launch that started Gosset or into an already-running window.
   *
   * Calling this is also the renderer's signal that it is ready to receive one: the main process
   * parks a launch-time path until this fires, because a project delivered before app.js has
   * attached its listener would be silently dropped and the user would see an empty worksheet with
   * no explanation.
   */
  onOpenProject: (handler) => {
    ipcRenderer.on('gosset:open-project', (_event, payload) => handler(payload));
    ipcRenderer.send('gosset:renderer-ready');
  },

  /**
   * Auto-update.
   *
   * The renderer owns the entire user-facing side: the dialogs are ordinary app windows in the app's
   * own design language, and the decision to restart is taken there because only the renderer knows
   * whether there is unsaved work. The main process owns the network and the installer.
   *
   * Everything here is a no-op in a browser (see desktopBridge.js), which is what keeps the update UI
   * out of the dev-mode app entirely rather than showing it a feature it cannot have.
   */
  updater: {
    /** `{currentVersion, supported, releasesUrl}` */
    info: () => ipcRenderer.invoke('gosset:updater-info'),

    /** Mirror the "Check for updates automatically" preference into the main process. */
    setEnabled: (enabled) => ipcRenderer.send('gosset:updater-set-enabled', enabled),

    /** `user: true` for the Options "Check now" button — the only check allowed to report failure. */
    check: (user = false) => ipcRenderer.invoke('gosset:updater-check', { user }),

    /** Start the download the user consented to. Progress arrives via onProgress. */
    download: () => ipcRenderer.invoke('gosset:updater-download'),

    /** Do not prompt again automatically until the next launch. */
    snooze: () => ipcRenderer.send('gosset:updater-snooze'),

    /** Quit and install. Call ONLY after the unsaved-work prompt has resolved. */
    install: () => ipcRenderer.invoke('gosset:updater-install'),

    /**
     * Attach the update-available handler AND tell the main process the renderer is listening.
     *
     * The handshake is the point: the first check happens 3s after the window appears, before the
     * renderer has finished starting, so the main process parks the offer until this fires. Without it
     * a genuinely available update produced no popup at all.
     */
    onAvailable: (fn) => {
      ipcRenderer.on('gosset:update-available', (_e, p) => fn(p));
      ipcRenderer.send('gosset:updater-ready');
    },

    onNotAvailable: (fn) => ipcRenderer.on('gosset:update-not-available', (_e, p) => fn(p)),
    onProgress: (fn) => ipcRenderer.on('gosset:update-progress', (_e, p) => fn(p)),
    onDownloaded: (fn) => ipcRenderer.on('gosset:update-downloaded', (_e, p) => fn(p)),
    onError: (fn) => ipcRenderer.on('gosset:update-error', (_e, p) => fn(p)),
  },

  /**
   * Google sign-in, identity only.
   *
   * Deliberately narrow: the renderer can start a sign-in, end one, and ask who is signed in. It can
   * never obtain a token — every credential stays in the main process (see desktop/src/auth.js), so a
   * page loaded here has nothing to steal. `state()` is the single shape all of these resolve to, so
   * the UI has one way to render itself.
   */
  auth: {
    /** `{configured, signedIn, profile: {name, email, picture, provider, signedInAt} | null}` */
    state: () => ipcRenderer.invoke('gosset:auth-state'),

    /** Opens the SYSTEM browser. Resolves `{ok, state}` or `{ok: false, error}` — cancelling is not an error. */
    signIn: () => ipcRenderer.invoke('gosset:auth-sign-in'),

    /** Forgets the local session. Does not revoke the Google grant — that is the user's to remove. */
    signOut: () => ipcRenderer.invoke('gosset:auth-sign-out'),

    /** Opportunistic validity check; clears a revoked session but never signs you out for being offline. */
    refresh: () => ipcRenderer.invoke('gosset:auth-refresh'),
  },
});
