// Auto-update, as the user experiences it: ordinary app windows, not native alerts.
//
// Everything here is inert in a browser. `desktop.updater()` returns null there, so File > Options
// hides its update section and no code path can reach a feature the browser build does not have.
//
// The division of labour with the main process is deliberate. The main process owns the network and
// the installer; this module owns every decision a person makes — whether to download, whether to
// restart now, and what happens to unsaved work first. That last one is why the restart button lives
// here: only the app knows there is an unsaved project, and an update that silently discarded someone's
// work would be the worst bug this app could have.

import { h } from './resultView.js';
import * as desktop from './desktopBridge.js';
import * as brand from './brand/brand.js';
import { releasesBetween } from './changelogData.js';

let wm = null;
let deps = {};

/**
 * @param {object} d
 * @param {object} d.wm                   windowManager
 * @param {() => boolean} d.hasUnsavedWork
 * @param {() => Promise<boolean>} d.saveBeforeQuit  runs the save flow; false means "cancel the restart"
 * @param {(text: string) => void} d.log  session-window line
 * @param {() => boolean} d.autoCheckEnabled
 */
export function init(d) {
  deps = d;
  wm = d.wm;

  const updater = desktop.updater();
  if (!updater) return;

  // Tell the main process the current preference before its first check fires (3s after the window).
  updater.setEnabled(deps.autoCheckEnabled());

  updater.onAvailable((info) => openUpdateWindow(info));
  updater.onNotAvailable((info) => {
    // Only ever sent for a check the user asked for.
    notifyUpToDate(info);
  });
  updater.onError((err) => showError(err));
  updater.onProgress((p) => applyProgress(p));
  updater.onDownloaded((info) => applyDownloaded(info));
}

/** Called when File > Options is applied, so the main process's automatic check follows the setting. */
export function setEnabled(enabled) {
  const updater = desktop.updater();
  if (updater) updater.setEnabled(enabled);
}

/** The Options "Check now" button. */
export async function checkNow() {
  const updater = desktop.updater();
  if (!updater) return;
  await updater.check(true);
}

export async function currentInfo() {
  const updater = desktop.updater();
  if (!updater) return { currentVersion: brand.version, supported: false, releasesUrl: '' };
  try {
    return await updater.info();
  } catch {
    return { currentVersion: brand.version, supported: false, releasesUrl: '' };
  }
}

// ---------------------------------------------------------------------------
// the update window
// ---------------------------------------------------------------------------

const WIN_ID = 'update';

/** Live references into the open window, so progress events can patch it in place. */
let ui = null;

function formatMB(bytes) {
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

/**
 * The notes to show for an offered update.
 *
 * Prefers the app's OWN changelog over the release-notes string in latest.yml: the changelog is the
 * text that was actually written for users, and it covers every version being skipped, whereas the
 * feed carries only whatever the release body happened to contain. Falls back to the feed when the
 * bundled changelog does not know the version yet — which is normal, since the running app predates it.
 */
function notesFor(info) {
  const fromChangelog = releasesBetween(brand.version, info.version);
  if (fromChangelog.length) {
    return fromChangelog.flatMap((r) => r.bullets.map((b) => b.text));
  }
  return (info.notes || '')
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*[-*]\s*/, '').trim())
    .filter((line) => line && !line.startsWith('#'))
    .slice(0, 8);
}

function openUpdateWindow(info) {
  if (wm.has(WIN_ID)) {
    wm.focus(WIN_ID);
    return;
  }

  const bullets = notesFor(info);
  const markHost = h('div', { class: 'brand-mark-accent update-mark' });
  brand.mountMark(markHost, 28);

  const status = h('p', { class: 'update-status', text: '' });
  status.hidden = true;

  const bar = h('div', { class: 'update-bar-fill' });
  const barWrap = h('div', { class: 'update-bar' }, [bar]);
  barWrap.hidden = true;

  const primary = h('button', { type: 'button', class: 'btn btn-primary', text: 'Update now' });
  const later = h('button', { type: 'button', class: 'btn', text: 'Later' });

  const content = h('div', { class: 'update-panel' }, [
    h('div', { class: 'update-head' }, [
      markHost,
      h('div', {}, [
        h('p', { class: 'update-title', text: `${brand.name} ${info.version} is available` }),
        h('p', {
          class: 'update-sub',
          text: `You have ${info.currentVersion || brand.version}.`,
        }),
      ]),
    ]),
    bullets.length
      ? h('ul', { class: 'update-notes' }, bullets.slice(0, 8).map((t) => h('li', { text: t })))
      : h('p', { class: 'update-sub', text: 'Release notes are on the Releases page.' }),
    barWrap,
    status,
    h('div', { class: 'dialog-actions' }, [primary, later]),
  ]);

  const win = wm.createWindow({
    id: WIN_ID,
    title: `Update ${brand.name}`,
    kind: 'result',
    width: 460,
    content,
  });

  ui = { win, status, bar, barWrap, primary, later, version: info.version, stage: 'offer' };

  later.addEventListener('click', () => {
    // Snooze, not dismiss: no further automatic prompt until the app restarts. Deliberately silent —
    // a session-log line here would be noise about a thing the user just declined.
    const updater = desktop.updater();
    if (updater) updater.snooze();
    ui = null;
    win.close();
  });

  primary.addEventListener('click', () => onPrimary(info));

  requestAnimationFrame(() => wm.fitToContent(WIN_ID));
}

async function onPrimary(info) {
  if (!ui) return;
  const updater = desktop.updater();
  if (!updater) return;

  if (ui.stage === 'offer') {
    ui.stage = 'downloading';
    ui.primary.disabled = true;
    ui.primary.textContent = 'Downloading…';
    ui.later.textContent = 'Hide';
    ui.barWrap.hidden = false;
    ui.status.hidden = false;
    ui.status.textContent = 'Starting download…';
    await updater.download();
    return;
  }

  if (ui.stage === 'ready') {
    // The guarantee: unsaved work is dealt with BEFORE the app is replaced. saveBeforeQuit runs the
    // app's ordinary save flow and returns false if the user cancels out of it — in which case the
    // restart is abandoned and the update simply stays downloaded, ready for next time.
    if (deps.hasUnsavedWork && deps.hasUnsavedWork()) {
      ui.primary.disabled = true;
      ui.status.textContent = 'Saving your work first…';
      let proceed = false;
      try {
        proceed = await deps.saveBeforeQuit();
      } catch {
        proceed = false;
      }
      if (!proceed) {
        ui.primary.disabled = false;
        ui.status.textContent = 'Restart cancelled. The update is downloaded and will install next time you restart.';
        return;
      }
    }
    ui.status.textContent = 'Restarting…';
    ui.primary.disabled = true;
    const res = await updater.install();
    if (!res || !res.ok) {
      ui.primary.disabled = false;
      ui.status.textContent = 'Could not start the installer. Try restarting Gosset manually.';
    }
  }
}

function applyProgress(p) {
  if (!ui || ui.stage !== 'downloading') return;
  const pct = Math.round(p.percent || 0);
  ui.bar.style.width = `${pct}%`;
  const size = p.total ? ` — ${formatMB(p.transferred)} of ${formatMB(p.total)}` : '';
  ui.status.textContent = `Downloading ${pct}%${size}`;
}

function applyDownloaded(info) {
  if (deps.log) deps.log(`> Update ${info.version} downloaded — restart to finish updating.`);
  if (!ui) return;
  ui.stage = 'ready';
  ui.bar.style.width = '100%';
  ui.status.textContent = 'Download complete.';
  ui.primary.disabled = false;
  ui.primary.textContent = 'Restart to finish updating';
  ui.later.textContent = 'Later';
  requestAnimationFrame(() => wm.fitToContent(WIN_ID));
}

/**
 * An error the user is entitled to see: either they pressed Check now, or their download broke.
 * A background check that fails never reaches here — see updater.js, rule 2.
 */
async function showError({ message, stage }) {
  const { releasesUrl } = await currentInfo();
  const manual = releasesUrl
    ? h('p', { class: 'update-sub' }, [
        'You can ',
        h('a', { href: releasesUrl, target: '_blank', rel: 'noreferrer', text: 'download the latest version manually' }),
        '.',
      ])
    : null;

  if (ui && stage === 'download') {
    ui.stage = 'offer';
    ui.barWrap.hidden = true;
    ui.primary.disabled = false;
    ui.primary.textContent = 'Try again';
    ui.status.hidden = false;
    ui.status.textContent = `The download did not complete: ${message}`;
    if (manual && !ui.win.body.querySelector('.update-manual')) {
      manual.classList.add('update-manual');
      ui.status.after(manual);
    }
    requestAnimationFrame(() => wm.fitToContent(WIN_ID));
    return;
  }

  const content = h('div', { class: 'update-panel' }, [
    h('p', { class: 'update-title', text: 'Could not check for updates' }),
    h('p', { class: 'update-sub', text: message }),
    manual,
    h('div', { class: 'dialog-actions' }, [
      h('button', { type: 'button', class: 'btn btn-primary', text: 'Close', onClick: () => wm.close('update-error') }),
    ]),
  ]);
  wm.createWindow({ id: 'update-error', title: 'Update', kind: 'result', width: 420, content });
  requestAnimationFrame(() => wm.fitToContent('update-error'));
}

/** The answer to a manual "Check now" when there is nothing newer. */
function notifyUpToDate({ currentVersion, unsupported }) {
  const content = h('div', { class: 'update-panel' }, [
    h('p', { class: 'update-title', text: unsupported ? 'Updates are not available in this build' : `${brand.name} is up to date` }),
    h('p', {
      class: 'update-sub',
      text: unsupported
        ? 'Automatic updates work in the installed desktop app. This looks like a development build.'
        : `You are running version ${currentVersion || brand.version}, which is the latest.`,
    }),
    h('div', { class: 'dialog-actions' }, [
      h('button', { type: 'button', class: 'btn btn-primary', text: 'Close', onClick: () => wm.close('update-uptodate') }),
    ]),
  ]);
  wm.createWindow({ id: 'update-uptodate', title: 'Update', kind: 'result', width: 400, content });
  requestAnimationFrame(() => wm.fitToContent('update-uptodate'));
}
