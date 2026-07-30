// The signed-in identity, as the app shows it: a menu-bar button and an Account window.
//
// Identity only. Signing in changes what Gosset DISPLAYS — a name in the menu bar and a byline on an
// exported report — and nothing else. No analysis, no file, no menu item depends on being signed in,
// and none should: an offline statistics application that stops working without an account would have
// given up the thing that makes it worth running locally.
//
// Everything here is inert in a browser (`desktop.auth()` is null), so the dev-mode app simply has no
// account button rather than one that cannot work.

import { h } from './resultView.js';
import * as desktop from './desktopBridge.js';
import * as brand from './brand/brand.js';

const WIN_ID = 'account';
/** Where a user goes to remove the Google grant itself, which signing out deliberately does not do. */
const GOOGLE_PERMISSIONS_URL = 'https://myaccount.google.com/permissions';

let wm = null;
let logLine = null;
let button = null;

/** Last known `{configured, signedIn, profile}`. The single source for what to draw. */
let state = { configured: false, signedIn: false, profile: null };

/** Callbacks for anything that cares who is signed in (the report byline). */
const listeners = new Set();

/**
 * @param {object} deps
 * @param {object} deps.wm                windowManager
 * @param {(text: string) => void} deps.log
 */
export async function init(deps) {
  wm = deps.wm;
  logLine = deps.log;

  const api = desktop.auth();
  if (!api) {
    // Browser: no account button, and Help > Account must not be a live item that does nothing.
    // aria-disabled rather than `disabled`, because Chrome suppresses pointer events on a disabled
    // control so its title never appears — and the title is the entire explanation (CLAUDE.md trap 10).
    // menuHelp.js promotes a disabled item's title into the help card's Needs line, so hovering it
    // explains itself.
    const item = document.querySelector('.menu-item[data-action="account"]');
    if (item) {
      item.setAttribute('aria-disabled', 'true');
      item.classList.add('menu-item-disabled');
      item.title = 'Signing in needs the desktop app — it opens your browser and uses the system keychain.';
    }
    return;
  }

  mountButton();

  try {
    state = await api.state();
  } catch {
    state = { configured: false, signedIn: false, profile: null };
  }
  render();
  notify();

  // Validate the stored session in the background, well after startup. Never on the critical path:
  // this touches the network, and a slow or absent connection must not delay the app or change what is
  // already on screen. A revoked session clears itself; being offline does not (see auth.js::refresh).
  if (state.signedIn) {
    setTimeout(async () => {
      try {
        const next = await api.refresh();
        if (next.signedIn !== state.signedIn) {
          state = next;
          render();
          notify();
          if (!next.signedIn && logLine) logLine('> Your Google session is no longer valid. Sign in again to show your name on reports.');
        }
      } catch {
        /* offline: keep showing the cached identity, which is the point of caching it */
      }
    }, 8000);
  }
}

/** The signed-in display name, or '' — what the report byline uses. */
export function displayName() {
  if (!state.signedIn || !state.profile) return '';
  return state.profile.name || state.profile.email || '';
}

export function isSignedIn() {
  return Boolean(state.signedIn);
}

/** Notified whenever the identity changes, so a dialog already open can update its byline. */
export function onChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) {
    try {
      fn(displayName());
    } catch {
      /* a listener must not break the account UI */
    }
  }
}

// ---------------------------------------------------------------------------
// the menu-bar button
// ---------------------------------------------------------------------------

function mountButton() {
  const host = document.getElementById('account-slot');
  if (!host) return;
  button = h('button', { type: 'button', class: 'account-button', title: 'Account' });
  button.addEventListener('click', () => openAccountWindow());
  host.appendChild(button);
  host.hidden = false;
}

/** Initials, for when there is no picture — or the picture fails to load. */
function initialsOf(profile) {
  const source = (profile.name || profile.email || '?').trim();
  const parts = source.split(/[\s.@_-]+/).filter(Boolean);
  const letters = parts.length >= 2 ? `${parts[0][0]}${parts[1][0]}` : source.slice(0, 2);
  return letters.toUpperCase();
}

function render() {
  if (!button) return;
  button.textContent = '';

  if (!state.signedIn) {
    button.classList.remove('account-button-signed-in');
    button.append(h('span', { class: 'account-label', text: 'Sign in' }));
    button.title = state.configured ? 'Sign in with Google' : 'Sign-in is not configured in this build';
    return;
  }

  const profile = state.profile || {};
  button.classList.add('account-button-signed-in');

  const avatar = h('span', { class: 'account-avatar', text: initialsOf(profile) });
  if (profile.picture) {
    // The <img> is layered over the initials rather than replacing them, so a picture that fails to
    // load — offline, or a URL Google has rotated — leaves the initials visible instead of a gap.
    const img = h('img', { class: 'account-avatar-img', src: profile.picture, alt: '', referrerpolicy: 'no-referrer' });
    img.addEventListener('error', () => img.remove());
    avatar.appendChild(img);
  }

  // First name only: the menu bar is a single row shared with the worksheet chip, and a full name plus
  // a long worksheet name is what makes that row start eliding.
  const short = (profile.name || profile.email || '').split(/\s+/)[0] || '';
  button.append(avatar, h('span', { class: 'account-label', text: short }));
  button.title = `${profile.name || ''} — ${profile.email || ''}`.trim().replace(/^—\s*/, '');
}

// ---------------------------------------------------------------------------
// the Account window
// ---------------------------------------------------------------------------

export function openAccountWindow() {
  const api = desktop.auth();
  if (!api) return;
  if (wm.has(WIN_ID)) {
    wm.focus(WIN_ID);
    return;
  }

  const body = h('div', { class: 'account-panel' });
  const win = wm.createWindow({ id: WIN_ID, title: 'Account', kind: 'result', width: 420, content: body });
  paintPanel(body, api);
  requestAnimationFrame(() => wm.fitToContent(WIN_ID));
  return win;
}

function repaint(api) {
  const win = wm.get ? wm.get(WIN_ID) : null;
  const body = document.querySelector('.account-panel');
  if (body) {
    paintPanel(body, api);
    requestAnimationFrame(() => wm.fitToContent(WIN_ID));
  }
  render();
  notify();
  return win;
}

function paintPanel(body, api) {
  body.textContent = '';

  // Not configured: say so plainly, and say where the instructions are. A "Sign in" button that fails
  // with an API error teaches the user nothing.
  if (!state.configured) {
    body.append(
      h('p', { class: 'account-heading', text: 'Sign-in is not set up' }),
      h('p', {
        class: 'account-sub',
        text: `This build of ${brand.name} has no Firebase project configured, so there is nothing to sign in to. Everything else works exactly as it does signed in — signing in only puts your name on the app and on report covers.`,
      }),
      h('p', { class: 'account-sub' }, [
        'Setting it up is documented in ',
        h('a', { href: `${brand.repoUrl}/blob/main/docs/FIREBASE_SETUP.md`, target: '_blank', rel: 'noreferrer', text: 'FIREBASE_SETUP.md' }),
        '.',
      ]),
      h('div', { class: 'dialog-actions' }, [
        h('button', { type: 'button', class: 'btn btn-primary', text: 'Close', onClick: () => wm.close(WIN_ID) }),
      ]),
    );
    return;
  }

  if (!state.signedIn) {
    const error = h('p', { class: 'account-error' });
    error.hidden = true;
    const signIn = h('button', { type: 'button', class: 'btn btn-primary', text: 'Continue with Google' });

    signIn.addEventListener('click', async () => {
      signIn.disabled = true;
      signIn.textContent = 'Waiting for your browser…';
      error.hidden = true;
      try {
        const result = await api.signIn();
        if (result && result.ok) {
          state = result.state;
          if (logLine) logLine(`> Signed in as ${displayName()}.`);
          repaint(api);
          return;
        }
        error.textContent = (result && result.error) || 'Sign-in did not complete.';
        error.hidden = false;
      } catch (err) {
        error.textContent = err.message || String(err);
        error.hidden = false;
      }
      signIn.disabled = false;
      signIn.textContent = 'Continue with Google';
    });

    body.append(
      h('p', { class: 'account-heading', text: `Sign in to ${brand.name}` }),
      h('p', {
        class: 'account-sub',
        text: 'Your name and picture appear in the menu bar and on the cover of reports you export. Nothing is uploaded, and Gosset works exactly the same signed out.',
      }),
      h('p', { class: 'account-sub account-sub-quiet', text: 'Opens your usual browser to sign in with Google.' }),
      error,
      h('div', { class: 'dialog-actions' }, [
        signIn,
        h('button', { type: 'button', class: 'btn', text: 'Not now', onClick: () => wm.close(WIN_ID) }),
      ]),
    );
    return;
  }

  // Signed in.
  const profile = state.profile || {};
  const avatar = h('div', { class: 'account-avatar account-avatar-lg', text: initialsOf(profile) });
  if (profile.picture) {
    const img = h('img', { class: 'account-avatar-img', src: profile.picture, alt: '', referrerpolicy: 'no-referrer' });
    img.addEventListener('error', () => img.remove());
    avatar.appendChild(img);
  }

  const signOut = h('button', { type: 'button', class: 'btn', text: 'Sign out' });
  signOut.addEventListener('click', async () => {
    signOut.disabled = true;
    state = await api.signOut();
    if (logLine) logLine('> Signed out.');
    repaint(api);
  });

  body.append(
    h('div', { class: 'account-identity' }, [
      avatar,
      h('div', {}, [
        h('p', { class: 'account-name', text: profile.name || '(no name)' }),
        h('p', { class: 'account-email', text: profile.email || '' }),
      ]),
    ]),
    h('dl', { class: 'account-meta' }, [
      h('dt', { text: 'Signed in with' }),
      h('dd', { text: 'Google' }),
      h('dt', { text: 'Since' }),
      h('dd', { text: formatWhen(profile.signedInAt) }),
    ]),
    h('p', {
      class: 'account-sub',
      text: 'Your name appears on the cover of reports you export. No analysis data leaves this computer.',
    }),
    h('p', { class: 'account-sub account-sub-quiet' }, [
      'Signing out here forgets your details on this computer. To remove Gosset’s access to your Google account entirely, use ',
      h('a', { href: GOOGLE_PERMISSIONS_URL, target: '_blank', rel: 'noreferrer', text: 'Google’s permissions page' }),
      '.',
    ]),
    h('div', { class: 'dialog-actions' }, [
      h('button', { type: 'button', class: 'btn btn-primary', text: 'Close', onClick: () => wm.close(WIN_ID) }),
      signOut,
    ]),
  );
}

function formatWhen(iso) {
  if (!iso) return 'unknown';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'unknown';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
}
