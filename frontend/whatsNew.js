// "What's new in Gosset <version>" — shown once, after an update.
//
// The rule that shapes this: it must never be shown twice, and it must never be shown to someone who
// did not just update. Both come from one stored value, `lastRunVersion`:
//
//   stored missing        a fresh install (or a build predating this feature) -> record and stay quiet
//   stored === current    an ordinary launch -> nothing
//   stored < current      just updated -> show every release in between, then record
//   stored > current      a downgrade -> record and stay quiet
//
// The store is written AFTER the window opens rather than when it closes, deliberately: if it were
// written on close, an app killed with the window open would show the same notes again on the next
// launch. Being shown once is the promise; a crash is not a reason to break it.
//
// It also works entirely offline in both themes — the notes come from the generated changelogData.js
// bundled with the running build, not from the network.

import { h } from './resultView.js';
import * as brand from './brand/brand.js';
import { releasesBetween } from './changelogData.js';

const WIN_ID = 'whats-new';

/**
 * @param {object} opts
 * @param {object} opts.wm            windowManager
 * @param {string|null} opts.lastRunVersion
 * @param {(version: string) => void} opts.rememberVersion
 * @param {(text: string) => void} [opts.log]
 * @returns {boolean} whether the window was shown
 */
export function maybeShow({ wm, lastRunVersion, rememberVersion, log }) {
  const current = brand.version;

  // First run, a downgrade, or the same version: record where we are and say nothing.
  if (!lastRunVersion || cmp(lastRunVersion, current) >= 0) {
    rememberVersion(current);
    return false;
  }

  const releases = releasesBetween(lastRunVersion, current);
  // An update with no changelog entry (a build made between releases) gets no dialog — an empty
  // "what's new" card is worse than none.
  if (!releases.length) {
    rememberVersion(current);
    return false;
  }

  open({ wm, releases, current, from: lastRunVersion });
  // Recorded now, not on close. See the note at the top.
  rememberVersion(current);
  if (log) log(`> Updated to ${brand.name} ${current}.`);
  return true;
}

/** Force it open regardless of stored state — Help > What's New. */
export function show({ wm }) {
  const current = brand.version;
  const releases = releasesBetween(null, current);
  open({ wm, releases, current, from: null });
}

function cmp(a, b) {
  const split = (v) => {
    const [core, pre = ''] = String(v).replace(/^v/, '').split('-');
    return { nums: core.split('.').map((n) => parseInt(n, 10) || 0), pre };
  };
  const A = split(a);
  const B = split(b);
  for (let i = 0; i < 3; i += 1) {
    const d = (A.nums[i] || 0) - (B.nums[i] || 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  if (A.pre === B.pre) return 0;
  if (!A.pre) return 1;
  if (!B.pre) return -1;
  return A.pre < B.pre ? -1 : 1;
}

function open({ wm, releases, current, from }) {
  if (wm.has(WIN_ID)) {
    wm.focus(WIN_ID);
    return;
  }

  const markHost = h('div', { class: 'brand-mark-accent whatsnew-mark' });
  brand.mountMark(markHost, 32);

  // One section per version, so someone who skipped releases can see which change came from where
  // rather than one undifferentiated list.
  const sections = releases.map((r) => {
    const groups = [];
    let lastGroup = null;
    for (const b of r.bullets) {
      if (b.group && b.group !== lastGroup) {
        groups.push(h('p', { class: 'whatsnew-group', text: b.group }));
        lastGroup = b.group;
      }
      const list = groups[groups.length - 1]?.tagName === 'UL' ? groups[groups.length - 1] : null;
      if (list) list.append(h('li', { text: b.text }));
      else groups.push(h('ul', { class: 'whatsnew-list' }, [h('li', { text: b.text })]));
    }
    return h('section', { class: 'whatsnew-release' }, [
      h('div', { class: 'whatsnew-release-head' }, [
        h('span', { class: 'whatsnew-version', text: r.version }),
        r.date ? h('span', { class: 'whatsnew-date', text: r.date }) : null,
      ]),
      ...groups,
    ]);
  });

  const content = h('div', { class: 'whatsnew' }, [
    h('div', { class: 'whatsnew-head' }, [
      markHost,
      h('div', {}, [
        h('p', { class: 'whatsnew-title', text: `What's new in ${brand.name} ${current}` }),
        from && releases.length > 1
          ? h('p', { class: 'whatsnew-sub', text: `Everything since ${from} — you skipped ${releases.length - 1} release${releases.length > 2 ? 's' : ''}.` })
          : h('p', { class: 'whatsnew-sub', text: brand.namesake }),
      ]),
    ]),
    h('div', { class: 'whatsnew-body' }, sections),
    h('div', { class: 'dialog-actions' }, [
      h('button', { type: 'button', class: 'btn btn-primary', text: 'Got it', onClick: () => wm.close(WIN_ID) }),
    ]),
  ]);

  wm.createWindow({ id: WIN_ID, title: `What's new in ${brand.name}`, kind: 'result', width: 520, content });
  requestAnimationFrame(() => wm.fitToContent(WIN_ID));
}
