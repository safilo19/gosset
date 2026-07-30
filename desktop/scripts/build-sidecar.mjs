/**
 * Freeze the Python backend into desktop/../<build dir>/sidecar with PyInstaller.
 *
 * Build output lives OUTSIDE the repository, under %LOCALAPPDATA%\gosset-build by default
 * (override with GOSSET_BUILD_DIR). That is not tidiness — this repo is kept in a OneDrive folder,
 * and a 265 MB tree of build artifacts inside a synced directory means OneDrive holds handles open
 * on files PyInstaller is trying to replace. `--clean` then fails with WinError 5 on a random
 * .dist-info directory, differently each run. Keeping the artifacts out of the synced tree removes
 * the whole class of failure, and stops a rebuild from pushing 265 MB through the user's sync quota.
 *
 * On a CI runner there is no OneDrive and LOCALAPPDATA is an ordinary directory, so the same path
 * logic works unchanged — which is the point of resolving it here rather than in the workflow.
 */

import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { buildDir, repoRoot, sidecarDistDir } from './paths.mjs';

const workDir = join(buildDir, 'pyinstaller-work');
const distDir = join(buildDir, 'sidecar');

/** The venv interpreter if there is one, else whatever `python` is on PATH (CI installs globally). */
function pythonExe() {
  if (process.env.GOSSET_PYTHON) return process.env.GOSSET_PYTHON;
  const venv = resolve(repoRoot, '.venv', 'Scripts', 'python.exe');
  return existsSync(venv) ? venv : 'python';
}

mkdirSync(workDir, { recursive: true });
// Remove the previous bundle ourselves rather than relying on PyInstaller's --clean: we want the
// failure to be "could not delete the old bundle", named plainly, not a traceback from inside shutil.
if (existsSync(distDir)) {
  try {
    rmSync(distDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
  } catch (err) {
    console.error(`\nCould not remove the previous bundle at ${distDir}`);
    console.error('Something is holding a file open in it — usually a gosset-sidecar.exe still');
    console.error('running from a previous launch. Close it and try again.\n');
    throw err;
  }
}

const python = pythonExe();
console.log(`> PyInstaller  (python: ${python})`);
console.log(`> output       ${distDir}`);

const result = spawnSync(
  python,
  [
    '-m', 'PyInstaller',
    '--noconfirm',
    '--distpath', distDir,
    '--workpath', workDir,
    join('desktop', 'gosset-sidecar.spec'),
  ],
  { cwd: repoRoot, stdio: 'inherit' },
);

if (result.error) throw result.error;
if (result.status !== 0) {
  console.error(`\nPyInstaller exited ${result.status}.`);
  process.exit(result.status ?? 1);
}

const exe = join(sidecarDistDir, 'gosset-sidecar.exe');
if (!existsSync(exe)) {
  console.error(`\nPyInstaller reported success but ${exe} is not there.`);
  process.exit(1);
}
console.log(`\n> sidecar built: ${exe}`);
