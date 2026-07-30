/**
 * The handful of paths the build scripts and the electron-builder config all have to agree on.
 *
 * One module so that "where does the frozen sidecar go" has a single answer. build-sidecar.mjs
 * writes there and electron-builder.config.cjs reads from there; if those two ever disagree the
 * installer silently ships without a backend, and the app fails only once installed.
 */

import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

/** desktop/scripts -> desktop */
export const desktopRoot = resolve(here, '..');

/** desktop -> the repository root, which is what PyInstaller's spec paths are relative to. */
export const repoRoot = resolve(desktopRoot, '..');

/**
 * Build artifacts, deliberately outside the repository — see the comment in build-sidecar.mjs for
 * why (OneDrive holds handles on synced files and breaks rebuilds).
 */
export const buildDir =
  process.env.GOSSET_BUILD_DIR ||
  join(process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local'), 'gosset-build');

/** The --onedir bundle PyInstaller produces: a directory containing gosset-sidecar.exe. */
export const sidecarDistDir = join(buildDir, 'sidecar', 'gosset-sidecar');

/** Where electron-builder writes the installer. */
export const electronOutDir = join(buildDir, 'electron');
