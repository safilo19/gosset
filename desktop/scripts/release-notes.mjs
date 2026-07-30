/**
 * Print one version's CHANGELOG section as the GitHub Release body.
 *
 *   node desktop/scripts/release-notes.mjs 1.0.1
 *
 * The release workflow pipes this into the release body, so the notes a maintainer wrote once appear
 * on the Releases page and inside the app's "What's new" window without being typed twice. The
 * install/SmartScreen boilerplate is appended here rather than kept in the workflow YAML, because it
 * belongs to "what a release page says" and not to "how a release is built".
 *
 * Exits 0 with empty output when the version has no section — the caller decides whether that is fatal
 * (it is, for a tagged release).
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { releaseFor } from './changelog.mjs';
import { desktopRoot } from './paths.mjs';

const version = (process.argv[2] || '').replace(/^v/, '');
if (!version) {
  console.error('Usage: node release-notes.mjs <version>');
  process.exit(2);
}

const release = releaseFor(version);
if (!release) process.exit(0); // no section: print nothing, let the caller fail

const { repository } = JSON.parse(readFileSync(join(desktopRoot, 'package.json'), 'utf8'));
const repoUrl = (repository?.url || '').replace(/\.git$/, '');

const body = `## Gosset ${version}

${release.body}

---

### Installing

Download **\`Gosset-Setup-${version}.exe\`** below and run it.

> **Windows will warn you on first run.** The installer is not code-signed, so SmartScreen shows
> "Windows protected your PC — unrecognized app". Click **More info**, then **Run anyway**. This is
> expected for every release until a code-signing certificate is in place; it means Windows has not
> seen this file signed by a known publisher, not that the file is known to be harmful.

Gosset installs per-user — no administrator rights — and adds a desktop shortcut, a Start Menu entry,
and a \`.gsp\` file association so double-clicking a project opens it.

If you already have Gosset installed, you do not need this page: the app checks for updates on its own
and will offer to install this version.

Everything runs locally. No account, no network access, no telemetry.

${repoUrl ? `**Full changelog:** [CHANGELOG.md](${repoUrl}/blob/main/CHANGELOG.md)` : ''}`;

process.stdout.write(body.trim());
