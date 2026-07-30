/**
 * Read CHANGELOG.md into structured releases.
 *
 * One parser, three consumers — the release script (to insert a section), the release workflow (to
 * copy a section into the GitHub Release body), and the app's "What's new" window (to show every
 * version a user skipped). Keeping the format knowledge here is what makes "one changelog, two
 * surfaces" true rather than aspirational: three regexes in three places would drift, and the failure
 * mode is silent — a release whose notes are empty everywhere except the file nobody reads.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { repoRoot } from './paths.mjs';

export const CHANGELOG_PATH = join(repoRoot, 'CHANGELOG.md');

/** The marker the release script inserts new sections directly beneath. */
export const NEXT_RELEASE_MARKER = '<!-- next-release -->';

/**
 * Every release section, newest first.
 *
 * Each is `{ version, date, body, bullets }`: `body` is the raw markdown between this heading and the
 * next (good for a GitHub Release body, which renders markdown), `bullets` is the flattened list of
 * bullet texts with their `### Added` / `### Fixed` group attached (good for the app, which renders
 * its own list and has no markdown renderer).
 */
export function parseChangelog(text = readFileSync(CHANGELOG_PATH, 'utf8')) {
  const releases = [];
  // ## [1.2.3] - 2026-07-30    (the link-reference form Keep a Changelog uses)
  const heading = /^##\s*\[([^\]]+)\]\s*(?:-\s*(\S+))?\s*$/gm;

  const matches = [...text.matchAll(heading)];
  for (let i = 0; i < matches.length; i += 1) {
    const m = matches[i];
    const start = m.index + m[0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : text.length;
    let body = text.slice(start, end);

    // Drop the trailing link-reference definitions ("[1.0.0]: https://…"), which are markdown
    // plumbing rather than release notes and would otherwise show up as a bullet in the app.
    body = body.replace(/^\[[^\]]+\]:\s*\S+\s*$/gm, '').trim();

    releases.push({
      version: m[1].trim(),
      date: (m[2] || '').trim(),
      body,
      bullets: bulletsFrom(body),
    });
  }
  return releases;
}

/** `[{ group, text }]` — group is 'Added' / 'Fixed' / '' for bullets before any subheading. */
function bulletsFrom(body) {
  const bullets = [];
  let group = '';
  for (const rawLine of body.split(/\r?\n/)) {
    const line = rawLine.trim();
    const sub = line.match(/^###\s+(.+?)\s*$/);
    if (sub) {
      group = sub[1];
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      bullets.push({ group, text: line.replace(/^[-*]\s+/, '').trim() });
      continue;
    }
    // A wrapped continuation line belongs to the bullet above it, not to nothing.
    if (line && bullets.length && !line.startsWith('#') && !/^\[[^\]]+\]:/.test(line)) {
      const last = bullets[bullets.length - 1];
      // Only treat it as a continuation if the previous raw line was indented or the bullet is open.
      if (/^\s+/.test(rawLine)) last.text += ` ${line}`;
    }
  }
  return bullets;
}

/** One release by exact version string, or null. */
export function releaseFor(version, text) {
  const wanted = String(version).replace(/^v/, '');
  return parseChangelog(text).find((r) => r.version === wanted) || null;
}

/**
 * Semver compare, enough for this project's plain `x.y.z[-pre]` versions: returns <0, 0 or >0.
 * A prerelease sorts before its release (1.1.0-rc.1 < 1.1.0), which is what makes "show everything
 * the user missed" behave when an rc is involved.
 */
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
  if (!A.pre) return 1; // a release outranks its own prerelease
  if (!B.pre) return -1;
  return A.pre < B.pre ? -1 : 1;
}

/**
 * Every release strictly newer than `fromVersion` and no newer than `toVersion`, newest first.
 *
 * This is what lets someone who skipped 1.1 and 1.2 see all of it on updating to 1.3, rather than only
 * the newest section. `fromVersion` null (a first run, or an install that predates the stored key)
 * yields just `toVersion`, because showing a brand-new user the entire project history as a
 * "what's new" dialog would be noise, not a welcome.
 */
export function releasesBetween(fromVersion, toVersion, text) {
  const all = parseChangelog(text);
  if (!fromVersion) return all.filter((r) => r.version === String(toVersion).replace(/^v/, ''));
  return all.filter(
    (r) => compareVersions(r.version, fromVersion) > 0 && compareVersions(r.version, toVersion) <= 0,
  );
}
