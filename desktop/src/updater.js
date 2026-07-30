'use strict';

/**
 * Auto-update, over GitHub Releases.
 *
 * The feed is `latest.yml`, which electron-builder publishes next to the installer (see the publish
 * provider in electron-builder.config.cjs — without it there is no feed and nothing here can work).
 *
 * Four rules shape this module, and each exists because the obvious alternative is user-hostile:
 *
 * 1. **Nothing downloads without being asked.** `autoDownload = false`. A 186 MB download starting by
 *    itself on someone's metered connection, while they are working, is not a feature.
 * 2. **A failure is silent.** No network, GitHub unreachable, DNS captive portal: log it and stop. An
 *    app that opens a dialog every launch because the office proxy blocks GitHub has made itself worse
 *    at its actual job. The ONLY failure the user is told about is one they asked for — a manual check,
 *    or a download that broke after they clicked Update.
 * 3. **It asks once per session.** Declining means declining until the next launch, not being asked
 *    again in four hours.
 * 4. **It never interrupts the restart with unsaved work.** The renderer owns that decision; this
 *    module asks and waits (see `main.js`'s `gosset:updater-install` handler).
 */

const { app } = require('electron');

const { log } = require('./log');

/** 3s after the window is ready: late enough that startup is done, early enough to be this session. */
const FIRST_CHECK_DELAY_MS = 3_000;
/** Then every 4 hours, for the people who leave it open for days. */
const RECHECK_INTERVAL_MS = 4 * 60 * 60 * 1_000;

class Updater {
  /**
   * @param {object} opts
   * @param {() => import('electron').BrowserWindow | null} opts.getWindow
   * @param {() => boolean} opts.isEnabled  the "Check for updates automatically" preference
   */
  constructor({ getWindow, isEnabled }) {
    this.getWindow = getWindow;
    this.isEnabled = isEnabled;
    this.autoUpdater = null;
    this.timer = null;

    /** Set when the user picks Later: no further automatic prompt until the app restarts. */
    this.snoozedThisSession = false;
    /** The update we have told the renderer about, so a manual check can answer from it. */
    this.pending = null;
    this.downloading = false;
    this.downloaded = false;
    /** True while a check the USER asked for is in flight — the only kind that may report failure. */
    this.userInitiated = false;
  }

  /** Available only in a packaged app: an unpackaged Electron has no installer to replace. */
  get supported() {
    return app.isPackaged;
  }

  send(channel, payload) {
    const win = this.getWindow();
    if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
  }

  /** Lazily require and configure electron-updater. */
  init() {
    if (this.autoUpdater || !this.supported) return this.autoUpdater;

    let autoUpdater;
    try {
      ({ autoUpdater } = require('electron-updater'));
    } catch (err) {
      log.error(`electron-updater unavailable: ${err.message}`);
      return null;
    }

    autoUpdater.autoDownload = false;
    // Also off: an update that installs itself the moment the user closes the window would replace the
    // app behind their back, and the "Restart to finish updating" step is what makes it visible.
    autoUpdater.autoInstallOnAppQuit = false;
    autoUpdater.logger = {
      info: (m) => log.info(`[updater] ${m}`),
      warn: (m) => log.info(`[updater] warn: ${m}`),
      error: (m) => log.error(`[updater] ${m}`),
      debug: () => {},
    };

    // The builds are UNSIGNED (see the README), and Windows update verification checks the new
    // installer's signature against the running app's. With nothing to compare, that check fails and
    // every update is rejected — so it is disabled explicitly rather than left to a default.
    // FLIP THIS TO true the day a code-signing certificate is purchased; leaving it false with a signed
    // build would mean a tampered installer could be accepted.
    autoUpdater.verifyUpdateCodeSignature = false;

    autoUpdater.on('update-available', (info) => {
      log.info(`[updater] update available: ${info.version}`);
      this.pending = info;
      // A user-initiated check always shows the dialog. An automatic one respects the snooze.
      if (this.userInitiated || !this.snoozedThisSession) {
        this.send('gosset:update-available', {
          version: info.version,
          releaseDate: info.releaseDate || '',
          notes: normaliseNotes(info.releaseNotes),
          currentVersion: app.getVersion(),
        });
      }
      this.userInitiated = false;
    });

    autoUpdater.on('update-not-available', () => {
      log.info('[updater] no update available');
      if (this.userInitiated) {
        this.send('gosset:update-not-available', { currentVersion: app.getVersion() });
        this.userInitiated = false;
      }
    });

    autoUpdater.on('download-progress', (p) => {
      this.send('gosset:update-progress', {
        percent: Math.max(0, Math.min(100, p.percent || 0)),
        transferred: p.transferred || 0,
        total: p.total || 0,
        bytesPerSecond: p.bytesPerSecond || 0,
      });
    });

    autoUpdater.on('update-downloaded', (info) => {
      log.info(`[updater] downloaded ${info.version}`);
      this.downloading = false;
      this.downloaded = true;
      this.send('gosset:update-downloaded', { version: info.version });
    });

    autoUpdater.on('error', (err) => {
      const message = (err && err.message) || String(err);
      log.error(`[updater] ${message}`);

      // Rule 2. An automatic check that fails is a non-event: the network is the most likely cause and
      // the user did not ask. Only surface it if they are waiting for an answer — a manual check, or a
      // download they started, where silence would look like the button did nothing.
      if (this.downloading) {
        this.downloading = false;
        this.send('gosset:update-error', { message, stage: 'download' });
      } else if (this.userInitiated) {
        this.send('gosset:update-error', { message, stage: 'check' });
      }
      this.userInitiated = false;
    });

    this.autoUpdater = autoUpdater;
    return autoUpdater;
  }

  /** Schedule the first check and the recurring one. Safe to call once, after the window exists. */
  start() {
    if (!this.supported) {
      log.info('updater: skipped (not a packaged build)');
      return;
    }
    if (!this.init()) return;

    setTimeout(() => this.check({ user: false }), FIRST_CHECK_DELAY_MS);
    this.timer = setInterval(() => this.check({ user: false }), RECHECK_INTERVAL_MS);
    // Never let the interval hold the process open on its own.
    if (this.timer.unref) this.timer.unref();
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  /**
   * Ask GitHub whether there is something newer.
   * `user: true` means a human pressed "Check now", which is what licenses an error message.
   */
  async check({ user = false } = {}) {
    if (!this.supported) {
      if (user) this.send('gosset:update-not-available', { currentVersion: app.getVersion(), unsupported: true });
      return;
    }
    if (!user && !this.isEnabled()) {
      log.info('updater: automatic checks are off');
      return;
    }
    if (!user && this.snoozedThisSession) return;
    if (this.downloading || this.downloaded) return;

    const updater = this.init();
    if (!updater) return;

    this.userInitiated = user;
    try {
      await updater.checkForUpdates();
    } catch (err) {
      // checkForUpdates rejects AND emits 'error'; the handler above decides what the user sees, so
      // this only has to avoid an unhandled rejection.
      log.info(`[updater] check failed: ${(err && err.message) || err}`);
    }
  }

  /** Begin the download the user just consented to. */
  async download() {
    const updater = this.init();
    if (!updater || this.downloading) return;
    this.downloading = true;
    this.send('gosset:update-progress', { percent: 0, transferred: 0, total: 0, bytesPerSecond: 0 });
    try {
      await updater.downloadUpdate();
    } catch (err) {
      this.downloading = false;
      this.send('gosset:update-error', { message: (err && err.message) || String(err), stage: 'download' });
    }
  }

  /** Snooze until the next launch. */
  snooze() {
    this.snoozedThisSession = true;
    log.info('updater: snoozed for this session');
  }

  /**
   * Quit and install. Only ever called once the renderer has confirmed there is no unsaved work.
   *
   * isSilent=false so the installer's progress is visible, isForceRunAfter=true so the app comes back
   * up — an update that quietly exits and leaves the user staring at a desktop reads as a crash.
   */
  install() {
    const updater = this.init();
    if (!updater || !this.downloaded) return false;
    log.info('updater: quitAndInstall');
    // setImmediate so the IPC reply reaches the renderer before the process starts tearing down.
    setImmediate(() => updater.quitAndInstall(false, true));
    return true;
  }
}

/**
 * electron-updater hands over release notes as a string, or an array of `{version, note}` when several
 * releases are being skipped at once. Flatten to plain text and strip the HTML it sometimes contains —
 * this goes into a DOM the app builds itself, and the app never renders untrusted markup.
 */
function normaliseNotes(notes) {
  if (!notes) return '';
  const raw = Array.isArray(notes)
    ? notes.map((n) => (typeof n === 'string' ? n : `${n.version ? `## ${n.version}\n` : ''}${n.note || ''}`)).join('\n\n')
    : String(notes);
  return raw
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|li|h\d)>/gi, '\n')
    .replace(/<li>/gi, '- ')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

module.exports = { Updater, normaliseNotes };
