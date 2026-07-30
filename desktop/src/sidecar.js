'use strict';

/**
 * Owning the Python backend process: find a port, start it, wait for it, and make sure it dies.
 *
 * The shell's contract with the sidecar is deliberately narrow — a port on the command line and a
 * /health endpoint to poll. Nothing is scraped from stdout, so a log-format change in uvicorn cannot
 * break startup, and the window URL is known before the server exists.
 */

const { spawn } = require('node:child_process');
const { createServer } = require('node:net');
const { existsSync } = require('node:fs');
const { join } = require('node:path');
const http = require('node:http');

const { log } = require('./log');

/** How long to wait for the backend before giving up. A cold first launch loads numpy, pandas,
 *  scipy, statsmodels and sklearn off disk; on a slow spinning disk with an antivirus scanning a
 *  freshly installed 265 MB tree, 20s is not enough and 60s is not generous. */
const HEALTH_TIMEOUT_MS = 90_000;
const HEALTH_INTERVAL_MS = 250;

/**
 * The port the app prefers, every launch.
 *
 * THE PORT IS PART OF THE APP'S IDENTITY, and that is not obvious. The window loads
 * `http://127.0.0.1:<port>`, and Chromium partitions localStorage **by origin** — so a different port
 * means a different storage bucket. The app keeps every File > Options preference, the theme, the
 * recent-files list and the "last version run" marker in localStorage. With an OS-assigned port those
 * all silently reset on every launch: the user sets a theme, restarts, and it is gone, with nothing to
 * suggest why. It also meant the "What's new" window could never appear, because the version marker it
 * compares against was always absent.
 *
 * The fix is a stable origin, so the port is fixed rather than requested from the kernel. Nothing is
 * lost by fixing it: the single-instance lock means Gosset never competes with itself for this port.
 *
 * 48219 is arbitrary but deliberately unremarkable — high, outside the ephemeral range Windows hands
 * out by default (49152+), and not a port any common development server claims.
 */
const PREFERRED_PORT = 48219;
/** How many ports past the preferred one to try before giving up on a stable origin. */
const PORT_SCAN = 8;

/** Can we bind this port on loopback right now? */
function canBind(port) {
  return new Promise((resolve) => {
    const server = createServer();
    server.unref();
    server.once('error', () => resolve(false));
    // Bind loopback specifically: the sidecar binds 127.0.0.1, so a port free on 0.0.0.0 is not
    // necessarily the same question.
    server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)));
  });
}

/** An OS-assigned free port — the last resort, which costs a stable origin. */
function anyFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

/**
 * The port to serve on: the preferred one if it is free, then a short deterministic walk, and only
 * then whatever the kernel offers.
 *
 * The walk is deterministic rather than random for the same reason the first choice is fixed — a
 * machine where 48219 is permanently taken should still land on the SAME fallback every launch and keep
 * its settings. Falling through to an arbitrary port is logged, because it has a consequence the user
 * would otherwise experience as "the app forgot my preferences".
 *
 * There is still a window between close() and the sidecar binding it, which is why waitForHealth()
 * checks the pid it gets back rather than trusting that whatever answers on the port is ours.
 */
async function choosePort() {
  for (let port = PREFERRED_PORT; port < PREFERRED_PORT + PORT_SCAN; port += 1) {
    if (await canBind(port)) return { port, stable: true };
  }
  const port = await anyFreePort();
  return { port, stable: false };
}

/** Where the frozen sidecar lives, in an installed app and in a dev checkout. */
function resolveSidecarPath(app) {
  const exe = process.platform === 'win32' ? 'gosset-sidecar.exe' : 'gosset-sidecar';

  const candidates = [
    // Installed: electron-builder puts the PyInstaller bundle under resources/ via extraResources.
    join(process.resourcesPath || '', 'sidecar', 'gosset-sidecar', exe),
    // A local `electron-builder --dir` pack.
    join(app.getAppPath(), '..', 'sidecar', 'gosset-sidecar', exe),
    // A dev machine that has run `npm run build:sidecar` but is launching with `npm start`.
    join(
      process.env.GOSSET_BUILD_DIR ||
        join(process.env.LOCALAPPDATA || '', 'gosset-build'),
      'sidecar',
      'gosset-sidecar',
      exe,
    ),
  ];

  for (const candidate of candidates) {
    if (candidate && existsSync(candidate)) return { kind: 'frozen', command: candidate, args: [] };
  }
  return null;
}

/**
 * The Python-from-source fallback, for developing the shell without a 10-minute PyInstaller build.
 * Never used by an installed app: an end user has no .venv and no interpreter.
 */
function resolvePythonFallback(repoRoot) {
  const venv =
    process.platform === 'win32'
      ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
      : join(repoRoot, '.venv', 'bin', 'python');
  const command = existsSync(venv) ? venv : process.env.GOSSET_PYTHON;
  if (!command) return null;
  return { kind: 'source', command, args: [join(repoRoot, 'sidecar.py')] };
}

function probeHealth(port) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: '127.0.0.1', port, path: '/health', timeout: 2000 },
      (res) => {
        let body = '';
        res.on('data', (chunk) => {
          body += chunk;
        });
        res.on('end', () => {
          if (res.statusCode !== 200) return resolve(null);
          try {
            resolve(JSON.parse(body));
          } catch {
            resolve(null);
          }
        });
      },
    );
    req.on('timeout', () => {
      req.destroy();
      resolve(null);
    });
    req.on('error', () => resolve(null));
  });
}

/**
 * Poll /health until the sidecar answers, it dies, or we run out of patience.
 *
 * `isAlive` is checked every tick so that a sidecar which crashes on startup — a missing DLL, a
 * corrupt install — reports its exit immediately instead of making the user watch a splash screen
 * for the full 90 seconds.
 */
async function waitForHealth(port, isAlive, timeoutMs = HEALTH_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const health = await probeHealth(port);
    if (health && health.status === 'ok') return health;
    if (!isAlive()) throw new Error('The Gosset backend stopped before it finished starting.');
    await new Promise((r) => setTimeout(r, HEALTH_INTERVAL_MS));
  }
  throw new Error(`The Gosset backend did not answer on port ${port} within ${timeoutMs / 1000}s.`);
}

class Sidecar {
  constructor({ app, repoRoot, outputDir }) {
    this.app = app;
    this.repoRoot = repoRoot;
    this.outputDir = outputDir;
    this.child = null;
    this.port = null;
    this.health = null;
    this.exited = false;
    this.stderrTail = [];
  }

  get baseUrl() {
    return `http://127.0.0.1:${this.port}`;
  }

  isAlive() {
    return Boolean(this.child) && !this.exited;
  }

  async start() {
    const chosen = await choosePort();
    this.port = chosen.port;
    if (!chosen.stable) {
      log.error(
        `port ${PREFERRED_PORT}-${PREFERRED_PORT + PORT_SCAN - 1} are all in use, falling back to ${this.port}. ` +
          `Preferences and the recent-files list are stored per origin, so they will not carry over from ` +
          `previous launches while this is the case.`,
      );
    }

    const target = resolveSidecarPath(this.app) || resolvePythonFallback(this.repoRoot);
    if (!target) {
      throw new Error(
        'No Gosset backend found. In a development checkout run `npm run build:sidecar` in desktop/, ' +
          'or create the .venv described in the README.',
      );
    }
    log.info(`sidecar: ${target.kind} — ${target.command}`);

    const args = [
      ...target.args,
      '--port',
      String(this.port),
      '--output-dir',
      this.outputDir,
      // The backstop for a hard-killed shell: the sidecar polls this pid and exits when it vanishes,
      // so Task-Manager-ending Gosset cannot leave Python holding a port.
      '--parent-pid',
      String(process.pid),
    ];

    this.child = spawn(target.command, args, {
      // A CONSOLE-subsystem exe (see the spec for why) would flash a terminal window without this.
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      cwd: target.kind === 'source' ? this.repoRoot : undefined,
    });

    this.child.stdout.on('data', (d) => log.info(`[sidecar] ${String(d).trimEnd()}`));
    this.child.stderr.on('data', (d) => {
      const text = String(d).trimEnd();
      log.info(`[sidecar] ${text}`);
      // Kept so a startup failure can be shown to the user rather than only written to a log file
      // they do not know exists.
      this.stderrTail.push(text);
      if (this.stderrTail.length > 40) this.stderrTail.shift();
    });

    this.child.on('exit', (code, signal) => {
      this.exited = true;
      log.info(`sidecar exited: code=${code} signal=${signal}`);
    });
    this.child.on('error', (err) => {
      this.exited = true;
      log.error(`sidecar failed to spawn: ${err.message}`);
    });

    try {
      this.health = await waitForHealth(this.port, () => this.isAlive());
    } catch (err) {
      const tail = this.stderrTail.slice(-12).join('\n');
      throw new Error(tail ? `${err.message}\n\n${tail}` : err.message);
    }

    log.info(`sidecar healthy on ${this.baseUrl} (pid ${this.health.pid}, v${this.health.version})`);
    return this.health;
  }

  /**
   * Stop the sidecar, and mean it.
   *
   * On Windows a Python process serving HTTP does not reliably die from child.kill()'s
   * TerminateProcess when it has worker threads mid-request, and there is no SIGTERM to be polite
   * with. taskkill /T also takes any process tree it started (joblib's loky workers under
   * scikit-learn), which child.kill() would orphan.
   */
  stop() {
    if (!this.child || this.exited) return;
    const pid = this.child.pid;
    log.info(`stopping sidecar pid ${pid}`);
    try {
      if (process.platform === 'win32') {
        // Synchronous: this runs from will-quit, and an async kill would race the process exiting.
        require('node:child_process').execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], {
          stdio: 'ignore',
          windowsHide: true,
        });
      } else {
        this.child.kill('SIGTERM');
      }
    } catch (err) {
      log.error(`taskkill failed for pid ${pid}: ${err.message}`);
      try {
        this.child.kill();
      } catch {
        /* already gone */
      }
    }
    this.exited = true;
  }
}

module.exports = { Sidecar, choosePort, probeHealth, PREFERRED_PORT };
