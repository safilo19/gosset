// The changelog, as data the app can render.
//
// GENERATED FILE — do not edit by hand. `npm run stamp` (desktop/scripts/stamp-version.mjs) rebuilds it
// from CHANGELOG.md, which is the single source, and the release script and the CI build both run that
// first.
//
// It is generated rather than fetched for two reasons that both matter: the "What's new" window has to
// work with no network (Gosset is an offline app), and it must show the notes for the version the user
// is ACTUALLY running, which is the copy bundled with that build — not whatever main happens to say.

/** @type {{version: string, date: string, bullets: {group: string, text: string}[]}[]} newest first */
export const RELEASES = [
  {
    version: "1.0.7",
    date: "2026-07-30",
    bullets: [
      { group: "Added", text: "The update window now tells you how large the download is before you start it, which matters on a metered or slow connection." },
    ],
  },
  {
    version: "1.0.6",
    date: "2026-07-30",
    bullets: [
      { group: "Fixed", text: "Installing an update no longer opens the setup wizard. Choosing \"Restart to finish updating\" quit Gosset and then waited for someone to click through an installer; if you closed that window, you were left with no app running and the old version still installed." },
      { group: "Fixed", text: "Gosset now asks about unsaved work before restarting to update in every case. Data typed straight into the worksheet did not count as work, so an update could restart over the top of it without asking." },
      { group: "Fixed", text: "The update window shows only the release notes. It was also listing the download and Windows-warning instructions from the release page, including advice to download the installer by hand." },
      { group: "Fixed", text: "Update installation no longer runs a signature check that cannot pass for these unsigned builds." },
    ],
  },
  {
    version: "1.0.5",
    date: "2026-07-30",
    bullets: [
      { group: "Changed", text: "The update window now names the version you are coming from as well as the one you are going to, so it is clear what the jump is." },
    ],
  },
  {
    version: "1.0.4",
    date: "2026-07-30",
    bullets: [
      { group: "Fixed", text: "An update could download and install itself without asking. Gosset now refuses any download it did not get permission for, and cancels one that starts on its own." },
      { group: "Fixed", text: "The \"a new version is available\" window could fail to appear even when there was one, if the app was still starting when the check finished." },
    ],
  },
  {
    version: "1.0.3",
    date: "2026-07-30",
    bullets: [
      { group: "Fixed", text: "Gosset no longer forgets your settings when it restarts. The theme, the options in File > Options and the recent-files list were all being reset on every launch." },
      { group: "Fixed", text: "Because of that same problem, the \"What's new\" window could never appear after an update. It now does." },
    ],
  },
  {
    version: "1.0.2",
    date: "2026-07-30",
    bullets: [
      { group: "Added", text: "The Help menu now has \"What's New\" and \"Check for Updates\", so you no longer have to open About to find either." },
      { group: "Changed", text: "Checking for updates from the Help menu tells you when you are already up to date, instead of doing nothing visible." },
    ],
  },
  {
    version: "1.0.1",
    date: "2026-07-30",
    bullets: [
      { group: "Added", text: "Gosset now updates itself. It checks for new releases in the background and offers to install them, showing what changed before you decide. It never downloads anything without asking." },
      { group: "Added", text: "A \"What's new\" window after each update, listing everything that changed since the version you were running — including any releases you skipped." },
      { group: "Added", text: "File > Options has an Updates section: turn automatic checks off, check for one now, and see which version you are running." },
      { group: "Added", text: "About now links to the release notes." },
    ],
  },
  {
    version: "1.0.0",
    date: "2026-07-30",
    bullets: [
      { group: "Added", text: "Gosset is now a proper Windows application with an installer, a desktop shortcut and a Start Menu entry. It no longer needs a terminal, a Python install or a browser tab." },
      { group: "Added", text: "Project files use the .gsp extension and are registered with Windows, so double-clicking one opens it — with the app closed or already running. Older .baproj files still open." },
      { group: "Added", text: "File > Open and Save Project use the native Windows file dialogs, so a project can be saved anywhere rather than only into the downloads folder." },
      { group: "Added", text: "The window remembers its size and position between sessions, and the title bar shows the open project's name." },
      { group: "Fixed", text: "The branded PDF export could fail on a clean install because one of its dependencies was missing from the published requirements." },
      { group: "Fixed", text: "Reports are now written to a per-user folder instead of the application directory." },
    ],
  },
];

/** Semver compare for this project's plain `x.y.z[-pre]` versions: <0, 0 or >0. */
export function compareVersions(a, b) {
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

/**
 * Every release newer than `from` and no newer than `to`, newest first.
 *
 * This is what makes a user who skipped two versions see all three sets of notes rather than only the
 * newest. `from` null yields just `to`: showing someone's first launch the entire project history as a
 * "what's new" dialog would be noise rather than a welcome.
 */
export function releasesBetween(from, to) {
  if (!from) return RELEASES.filter((r) => r.version === String(to).replace(/^v/, ''));
  return RELEASES.filter((r) => compareVersions(r.version, from) > 0 && compareVersions(r.version, to) <= 0);
}
