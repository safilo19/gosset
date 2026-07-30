/**
 * Propagate desktop/package.json's `version` to the two places that display it.
 *
 * package.json is the source of truth because electron-builder already treats it as one — it stamps
 * the installer filename, the Windows file properties and the uninstall entry from that field, and
 * nothing can override it. So rather than have a second number that must be kept in step by hand
 * (which is how "About says 1.0.0 and the PDF footer says 1.0.0-dev" happens), the number is copied
 * OUT of package.json into two generated files:
 *
 *   backend/version.py            -> reports.APP_VERSION -> the PDF/Word footers and report metadata
 *   frontend/brand/version.js     -> brand.version       -> the About window
 *
 * Both are committed, so a source checkout runs with no Node.js involved; this script only has to run
 * when the version CHANGES. `prebuild` and `start` run it anyway, and --check makes CI fail if a
 * committed file has drifted from package.json rather than shipping a mismatched build.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { repoRoot, desktopRoot } from './paths.mjs';

const checkOnly = process.argv.includes('--check');

const { version } = JSON.parse(readFileSync(join(desktopRoot, 'package.json'), 'utf8'));
if (!/^\d+\.\d+\.\d+(-[\w.]+)?$/.test(version)) {
  throw new Error(`desktop/package.json version "${version}" is not a plain semver string.`);
}

const targets = [
  {
    path: join(repoRoot, 'backend', 'version.py'),
    body: `"""The app version, for Python.

GENERATED FILE — do not edit by hand. The single source of truth is \`version\` in
desktop/package.json; \`npm run stamp\` (desktop/scripts/stamp-version.mjs) rewrites this file and
frontend/brand/version.js from it, and the build and the release workflow both run it first.

It is committed rather than generated at import time so that a plain \`uvicorn backend.api:app\`
checkout needs no Node.js to start.
"""

VERSION = "${version}"
`,
  },
  {
    path: join(repoRoot, 'frontend', 'brand', 'version.js'),
    body: `// The app version, for the frontend.
//
// GENERATED FILE — do not edit by hand. The single source of truth is \`version\` in
// desktop/package.json; \`npm run stamp\` (desktop/scripts/stamp-version.mjs) rewrites this file and
// backend/version.py from it, and the build and the release workflow both run it first.
//
// brand.js re-exports this as \`brand.version\`, which is what the About window shows.

export const VERSION = '${version}';
`,
  },
];

/**
 * Compare ignoring line endings.
 *
 * These files are written with \n, but git normalises to CRLF on checkout for a Windows working tree
 * — so on a fresh clone (and on a CI runner) the bytes on disk differ from `body` even though the
 * VERSION in them is identical. A byte-exact comparison therefore reported "drift" on a perfectly
 * consistent checkout, which is exactly how this check failed on its first real run while passing
 * locally, where the files were still as this script had written them.
 *
 * The check's job is to catch a version number that disagrees with package.json, and a line ending
 * is not a version number.
 */
const sameContent = (a, b) => a.replace(/\r\n/g, '\n') === b.replace(/\r\n/g, '\n');

let drifted = 0;
for (const { path, body } of targets) {
  let current = null;
  try {
    current = readFileSync(path, 'utf8');
  } catch {
    /* first run */
  }
  // Skip rewriting a file that only differs by line endings, too: rewriting it would produce a
  // spurious diff on every Windows checkout.
  if (current !== null && sameContent(current, body)) continue;

  if (checkOnly) {
    console.error(`DRIFT  ${path} does not match version ${version} from package.json`);
    drifted += 1;
  } else {
    writeFileSync(path, body, 'utf8');
    console.log(`stamped ${version} -> ${path}`);
  }
}

if (checkOnly) {
  if (drifted) {
    console.error(`\n${drifted} file(s) out of date. Run \`npm run stamp\` in desktop/ and commit the result.`);
    process.exit(1);
  }
  console.log(`version ${version} is consistent across backend/version.py and frontend/brand/version.js`);
} else if (targets.every(({ path, body }) => sameContent(readFileSync(path, 'utf8'), body))) {
  console.log(`version ${version} is up to date`);
}
