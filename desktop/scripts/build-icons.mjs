/**
 * Run the icon generator with whichever Python is available.
 *
 * A thin wrapper so `npm run icons` works the same on a dev machine (venv) and on CI (global python),
 * and so electron-builder's `prebuild` can depend on it without the workflow knowing about Python
 * paths.
 */

import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { repoRoot } from './paths.mjs';

const venv = resolve(repoRoot, '.venv', 'Scripts', 'python.exe');
const python = process.env.GOSSET_PYTHON || (existsSync(venv) ? venv : 'python');

const result = spawnSync(python, [join('desktop', 'scripts', 'make_app_icons.py')], {
  cwd: repoRoot,
  stdio: 'inherit',
});

if (result.error) throw result.error;
process.exit(result.status ?? 1);
