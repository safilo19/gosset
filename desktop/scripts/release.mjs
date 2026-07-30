/**
 * One command from "feature done" to "published release".
 *
 *   npm run release -- patch      1.0.0 -> 1.0.1
 *   npm run release -- minor      1.0.0 -> 1.1.0
 *   npm run release -- major      1.0.0 -> 2.0.0
 *   npm run release -- 1.4.2      an explicit version
 *
 *   --dry-run    print every step and change nothing
 *   --yes        skip the confirmation prompt (for non-interactive use)
 *
 * It bumps package.json, inserts a CHANGELOG section, re-stamps the generated version files, commits,
 * tags `v<version>` and pushes commit + tag. Pushing the tag is what triggers the release workflow, so
 * this is the last manual step in shipping.
 *
 * The order is deliberate and the checks are not ceremony:
 *
 *   - refuse on a dirty tree FIRST, because the commit below is `git add -A`-shaped and would sweep up
 *     unrelated work into a release commit
 *   - refuse if the tag already exists, locally or on the remote, because re-tagging a published
 *     release silently changes what a version means to everyone who already downloaded it
 *   - write the CHANGELOG section BEFORE committing, and stop if it is still the placeholder — a
 *     release whose notes say "describe this release" reaches the GitHub Release body and the app's
 *     "what's new" window, where it cannot be quietly fixed later
 */

import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { createInterface } from 'node:readline/promises';
import { join } from 'node:path';
import { desktopRoot, repoRoot } from './paths.mjs';
import { CHANGELOG_PATH, NEXT_RELEASE_MARKER, compareVersions, parseChangelog } from './changelog.mjs';

const PLACEHOLDER = 'Describe this release';

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const assumeYes = args.includes('--yes');
const bumpArg = args.find((a) => !a.startsWith('-'));

function git(...argv) {
  return execFileSync('git', argv, { cwd: repoRoot, encoding: 'utf8' }).trim();
}

function run(cmd, argv, opts = {}) {
  if (dryRun) {
    console.log(`  [dry-run] ${cmd} ${argv.join(' ')}`);
    return '';
  }
  return execFileSync(cmd, argv, { cwd: repoRoot, encoding: 'utf8', stdio: 'inherit', ...opts });
}

function fail(message) {
  console.error(`\n${message}\n`);
  process.exit(1);
}

function bump(version, kind) {
  const [major, minor, patch] = version.replace(/^v/, '').split('-')[0].split('.').map(Number);
  if (kind === 'major') return `${major + 1}.0.0`;
  if (kind === 'minor') return `${major}.${minor + 1}.0`;
  if (kind === 'patch') return `${major}.${minor}.${patch + 1}`;
  if (/^\d+\.\d+\.\d+(-[\w.]+)?$/.test(kind)) return kind;
  fail(`Unknown release kind "${kind}". Use patch, minor, major, or an explicit version like 1.4.2.`);
}

// ---------------------------------------------------------------------------
// preflight
// ---------------------------------------------------------------------------

if (!bumpArg) {
  fail('Usage: npm run release -- <patch|minor|major|x.y.z> [--dry-run] [--yes]');
}

const pkgPath = join(desktopRoot, 'package.json');
const pkgRaw = readFileSync(pkgPath, 'utf8');
const pkg = JSON.parse(pkgRaw);
const from = pkg.version;
const to = bump(from, bumpArg);

if (compareVersions(to, from) <= 0) {
  fail(`New version ${to} is not newer than the current ${from}.`);
}

const branch = git('rev-parse', '--abbrev-ref', 'HEAD');
const dirty = git('status', '--porcelain');
if (dirty && !dryRun) {
  fail(
    `The working tree is not clean, and this script commits everything staged and unstaged.\n` +
      `Commit or stash first:\n\n${dirty}`,
  );
}
if (branch !== 'main') {
  console.log(`! On branch "${branch}", not main. The workflow triggers on the tag, so this still works.`);
}

const tag = `v${to}`;
const localTags = git('tag', '--list', tag);
if (localTags) fail(`Tag ${tag} already exists locally. Delete it or pick another version.`);
try {
  const remote = git('ls-remote', '--tags', 'origin', tag);
  if (remote.trim()) {
    fail(
      `Tag ${tag} already exists on origin — that version has been released.\n` +
        `Re-tagging would change what ${tag} means for anyone who already downloaded it. Bump again instead.`,
    );
  }
} catch {
  console.log('! Could not reach origin to check for an existing tag; continuing.');
}

// ---------------------------------------------------------------------------
// changelog
// ---------------------------------------------------------------------------

const today = new Date().toISOString().slice(0, 10);
let changelog = readFileSync(CHANGELOG_PATH, 'utf8');

if (!changelog.includes(NEXT_RELEASE_MARKER)) {
  fail(`CHANGELOG.md is missing its "${NEXT_RELEASE_MARKER}" marker, which is where new sections go.`);
}

// A section for this version may already exist — someone wrote the notes as they worked, which is the
// better habit anyway. Accept it if it has real bullets, and skip the insert-and-prompt dance entirely.
// Only a section that is empty or still holds the placeholder is a problem, and that is caught below.
const existing = parseChangelog(changelog);
const preWritten = existing.find((r) => r.version === to);
const notesAlreadyWritten = Boolean(
  preWritten && preWritten.bullets.length && !preWritten.bullets.some((b) => b.text.includes(PLACEHOLDER)),
);
if (preWritten && !notesAlreadyWritten) {
  fail(
    `CHANGELOG.md already has a [${to}] section, but it is empty or still holds the placeholder.\n` +
      `Write its notes, or remove the section and run this again.`,
  );
}
if (notesAlreadyWritten) {
  console.log(`Using the [${to}] section already in CHANGELOG.md (${preWritten.bullets.length} note(s)).`);
}

const section = [
  '',
  `## [${to}] - ${today}`,
  '',
  '### Added',
  '',
  `- ${PLACEHOLDER} in plain language, from the point of view of someone using the app.`,
  '',
].join('\n');

const repoUrl = (pkg.repository?.url || '').replace(/\.git$/, '');
const linkRef = `[${to}]: ${repoUrl}/releases/tag/${tag}`;

console.log(`\nGosset release: ${from} -> ${to}  (tag ${tag})\n`);

if (!dryRun && !notesAlreadyWritten) {
  // Insert directly under the marker so the newest release is always at the top.
  changelog = changelog.replace(NEXT_RELEASE_MARKER, `${NEXT_RELEASE_MARKER}${section}`);
  // Link references live at the bottom; add this version's above the previous newest.
  const firstRef = changelog.search(/^\[[^\]]+\]:\s*\S+\s*$/m);
  changelog =
    firstRef === -1
      ? `${changelog.trimEnd()}\n\n${linkRef}\n`
      : `${changelog.slice(0, firstRef)}${linkRef}\n${changelog.slice(firstRef)}`;
  writeFileSync(CHANGELOG_PATH, changelog, 'utf8');
  console.log(`Wrote a [${to}] section to CHANGELOG.md.`);
}

// ---------------------------------------------------------------------------
// the human part: the notes have to actually be written
// ---------------------------------------------------------------------------

if (!dryRun) {
  if (!notesAlreadyWritten) {
    console.log(`\nEdit CHANGELOG.md now — replace the placeholder bullet with 3-8 real, user-facing lines.`);
    console.log(`These reach the GitHub Release body and the app's "What's new" window.\n`);
  }

  if (!assumeYes && !notesAlreadyWritten) {
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    const answer = await rl.question(`Press Enter when the notes are written (or type "abort"): `);
    rl.close();
    if (answer.trim().toLowerCase() === 'abort') {
      console.log('\nAborted. CHANGELOG.md still has the new section — edit or revert it.');
      process.exit(1);
    }
  }

  const written = readFileSync(CHANGELOG_PATH, 'utf8');
  const release = parseChangelog(written).find((r) => r.version === to);
  if (!release || !release.bullets.length) {
    fail(`The [${to}] section has no bullets. Write the notes, then run this again.`);
  }
  if (release.bullets.some((b) => b.text.includes(PLACEHOLDER))) {
    fail(
      `The [${to}] section still contains the placeholder bullet.\n` +
        `Those notes go into the GitHub Release and the app's "What's new" window — write them first.`,
    );
  }
  console.log(`\n${release.bullets.length} note(s) for ${to}:`);
  for (const b of release.bullets) console.log(`  - ${b.text}`);
}

// ---------------------------------------------------------------------------
// bump, stamp, commit, tag, push
// ---------------------------------------------------------------------------

if (!dryRun) {
  // Rewrite only the version line, so the file keeps its formatting and key order.
  writeFileSync(pkgPath, pkgRaw.replace(/"version":\s*"[^"]*"/, `"version": "${to}"`), 'utf8');
  console.log(`\nBumped desktop/package.json to ${to}.`);
}

console.log('\nStamping the generated version files…');
run(process.execPath, [join(desktopRoot, 'scripts', 'stamp-version.mjs')]);

console.log('\nCommitting…');
run('git', ['add', '-A']);
run('git', ['commit', '-m', `Release ${to}`]);
run('git', ['tag', '-a', tag, '-m', `Gosset ${to}`]);

console.log('\nPushing commit and tag…');
run('git', ['push', 'origin', branch]);
run('git', ['push', 'origin', tag]);

const releasesUrl = `${repoUrl}/releases`;
console.log(
  dryRun
    ? '\nDry run complete — nothing was changed.\n'
    : `\nReleased ${tag}. The workflow is building the installer now:\n  ${repoUrl}/actions\nIt will appear at:\n  ${releasesUrl}\n`,
);
