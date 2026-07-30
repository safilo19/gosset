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
});
