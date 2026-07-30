'use strict';

/**
 * A log file, because an installed app has no console to print to.
 *
 * When the shell fails before a window exists — no sidecar, a port that would not bind, a corrupt
 * install — this file is the only evidence of what happened. It is written next to the app's other
 * per-user state and truncated at startup so it stays readable rather than becoming an archive.
 */

const { appendFileSync, mkdirSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');

let logPath = null;

function stamp() {
  return new Date().toISOString().replace('T', ' ').replace('Z', '');
}

function write(level, message) {
  const line = `${stamp()}  ${level.padEnd(5)} ${message}\n`;
  // Still goes to stdout: `npm start` in desktop/ is a real console, and that is where a developer
  // is looking.
  process.stdout.write(line);
  if (!logPath) return;
  try {
    appendFileSync(logPath, line, 'utf8');
  } catch {
    /* a log that cannot be written must never take the app down */
  }
}

const log = {
  /** Called once the app knows its userData directory. */
  init(userDataDir) {
    try {
      mkdirSync(userDataDir, { recursive: true });
      logPath = join(userDataDir, 'gosset.log');
      writeFileSync(logPath, `${stamp()}  ---   Gosset starting\n`, 'utf8');
    } catch {
      logPath = null;
    }
  },
  get path() {
    return logPath;
  },
  info(message) {
    write('INFO', message);
  },
  error(message) {
    write('ERROR', message);
  },
};

module.exports = { log };
