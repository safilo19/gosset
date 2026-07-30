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

[1.0.0]: https://github.com/safilo19/personal-analytics-mcp/releases/tag/v1.0.0
