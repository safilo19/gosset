'use strict';

/**
 * Remember where the window was, and put it back there — but only if that is still somewhere real.
 *
 * The saved rectangle is validated against the CURRENT displays on every restore. A window remembered
 * on a second monitor that is no longer attached, or on a screen whose resolution shrank, would
 * otherwise be restored somewhere the user cannot see or reach: fully offscreen, or with its title
 * bar above the top of the display, which on Windows leaves it undraggable.
 */

const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const { dirname, join } = require('node:path');

const MIN_WIDTH = 1200;
const MIN_HEIGHT = 760;

const DEFAULTS = { width: 1440, height: 900, maximized: false };

class WindowState {
  constructor(userDataDir) {
    this.file = join(userDataDir, 'window-state.json');
    this.state = { ...DEFAULTS };
    try {
      Object.assign(this.state, JSON.parse(readFileSync(this.file, 'utf8')));
    } catch {
      /* first run, or a file we cannot parse — the defaults are correct either way */
    }
  }

  /** Options for `new BrowserWindow(...)`, with the position dropped if it is no longer usable. */
  bounds(screen) {
    const width = Math.max(MIN_WIDTH, Math.round(this.state.width) || DEFAULTS.width);
    const height = Math.max(MIN_HEIGHT, Math.round(this.state.height) || DEFAULTS.height);
    const { x, y } = this.state;

    if (typeof x !== 'number' || typeof y !== 'number') return { width, height };

    // "Visible" means a decent slice of the title bar is on some display, not merely that the
    // rectangles intersect by a pixel.
    const onScreen = screen.getAllDisplays().some(({ workArea }) => {
      const overlapX = Math.min(x + width, workArea.x + workArea.width) - Math.max(x, workArea.x);
      const overlapY = Math.min(y + height, workArea.y + workArea.height) - Math.max(y, workArea.y);
      return overlapX > 200 && overlapY > 80;
    });

    return onScreen ? { width, height, x, y } : { width, height };
  }

  /**
   * Track a window's geometry.
   *
   * Only the RESTORED bounds are recorded. getBounds() on a maximized window returns the maximized
   * rectangle, so saving that would mean un-maximizing restores to a window that exactly fills the
   * screen but is not maximized — subtly wrong, and irreversible once saved.
   */
  track(win) {
    const record = () => {
      if (win.isDestroyed()) return;
      this.state.maximized = win.isMaximized();
      if (!win.isMaximized() && !win.isMinimized() && !win.isFullScreen()) {
        Object.assign(this.state, win.getBounds());
      }
    };

    let timer = null;
    const debounced = () => {
      clearTimeout(timer);
      // Resize fires continuously while dragging an edge; writing a file per event would be hundreds
      // of writes for one drag.
      timer = setTimeout(() => {
        record();
        this.save();
      }, 400);
    };

    win.on('resize', debounced);
    win.on('move', debounced);
    win.on('maximize', debounced);
    win.on('unmaximize', debounced);
    // close, not closed: the window still exists here, so its bounds are still readable. Synchronous
    // save, because the app may be quitting and an async write would not land.
    win.on('close', () => {
      clearTimeout(timer);
      record();
      this.save();
    });
  }

  save() {
    try {
      mkdirSync(dirname(this.file), { recursive: true });
      writeFileSync(this.file, JSON.stringify(this.state, null, 2), 'utf8');
    } catch {
      /* losing the window position is not worth an error dialog */
    }
  }
}

module.exports = { WindowState, MIN_WIDTH, MIN_HEIGHT };
