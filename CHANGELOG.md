# Changelog

All notable changes to Gosset are recorded here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[semantic versioning](https://semver.org/spec/v2.0.0.html).

**This file is written for the people who use Gosset, not for the people who write it.** A bullet says
what changed for someone running the app — "Added Poisson regression with rate ratios", never
"refactored the glm module". If a change is invisible from the interface it does not need a line.

It has two audiences and one source: `npm run release` inserts the section below, and the release
workflow copies that same section into the GitHub Release body and the app's "What's new" window. So
these bullets are read by users three times over — write them accordingly. Three to eight per release.

<!-- next-release -->
## [1.0.8] - 2026-07-30

### Fixed

- A failed update check no longer writes the whole server response, including GitHub session cookies, into Gosset's log file.

## [1.0.7] - 2026-07-30

### Added

- The update window now tells you how large the download is before you start it, which matters on a metered or slow connection.

## [1.0.6] - 2026-07-30

### Fixed

- Installing an update no longer opens the setup wizard. Choosing "Restart to finish updating" quit Gosset and then waited for someone to click through an installer; if you closed that window, you were left with no app running and the old version still installed.
- Gosset now asks about unsaved work before restarting to update in every case. Data typed straight into the worksheet did not count as work, so an update could restart over the top of it without asking.
- The update window shows only the release notes. It was also listing the download and Windows-warning instructions from the release page, including advice to download the installer by hand.
- Update installation no longer runs a signature check that cannot pass for these unsigned builds.

## [1.0.5] - 2026-07-30

### Changed

- The update window now names the version you are coming from as well as the one you are going to, so it is clear what the jump is.

## [1.0.4] - 2026-07-30

### Fixed

- An update could download and install itself without asking. Gosset now refuses any download it did not get permission for, and cancels one that starts on its own.
- The "a new version is available" window could fail to appear even when there was one, if the app was still starting when the check finished.

## [1.0.3] - 2026-07-30

### Fixed

- Gosset no longer forgets your settings when it restarts. The theme, the options in File > Options and the recent-files list were all being reset on every launch.
- Because of that same problem, the "What's new" window could never appear after an update. It now does.

## [1.0.2] - 2026-07-30

### Added

- The Help menu now has "What's New" and "Check for Updates", so you no longer have to open About to find either.

### Changed

- Checking for updates from the Help menu tells you when you are already up to date, instead of doing nothing visible.

## [1.0.1] - 2026-07-30

### Added

- Gosset now updates itself. It checks for new releases in the background and offers to install them, showing what changed before you decide. It never downloads anything without asking.
- A "What's new" window after each update, listing everything that changed since the version you were running — including any releases you skipped.
- File > Options has an Updates section: turn automatic checks off, check for one now, and see which version you are running.
- About now links to the release notes.


## [1.0.0] - 2026-07-30

Gosset's first desktop release.

### Added

- Gosset is now a proper Windows application with an installer, a desktop shortcut and a Start Menu
  entry. It no longer needs a terminal, a Python install or a browser tab.
- Project files use the `.gsp` extension and are registered with Windows, so double-clicking one opens
  it — with the app closed or already running. Older `.baproj` files still open.
- File > Open and Save Project use the native Windows file dialogs, so a project can be saved anywhere
  rather than only into the downloads folder.
- The window remembers its size and position between sessions, and the title bar shows the open
  project's name.

### Fixed

- The branded PDF export could fail on a clean install because one of its dependencies was missing from
  the published requirements.
- Reports are now written to a per-user folder instead of the application directory.

[1.0.8]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.8
[1.0.7]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.7
[1.0.6]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.6
[1.0.5]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.5
[1.0.4]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.4
[1.0.3]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.3
[1.0.2]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.2
[1.0.1]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.1
[1.0.0]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.0
