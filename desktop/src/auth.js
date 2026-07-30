'use strict';

/**
 * Google sign-in, for a desktop app.
 *
 * Identity only: Gosset shows who you are and puts your name on a report cover. Nothing is uploaded,
 * nothing is gated, and the app is fully usable signed out — see the offline rules at the bottom.
 *
 * ── Why this is not the Firebase JS SDK ──────────────────────────────────────────────────────────
 *
 * The obvious implementation, `signInWithPopup(auth, new GoogleAuthProvider())`, DOES NOT WORK HERE,
 * and it fails in a way that looks like a bug in your code:
 *
 *   - Google refuses OAuth inside embedded browser frames. An Electron BrowserWindow is one, so the
 *     consent screen returns `403: disallowed_useragent` instead of signing anyone in. This is a
 *     deliberate Google policy against apps that could read the user's credentials out of the frame,
 *     and there is no flag that turns it off.
 *   - The popup/redirect helpers also assume a real web origin with a Firebase-authorised domain.
 *     This app is served from `http://127.0.0.1:<port>` by its own Python sidecar.
 *
 * The supported pattern for an installed application is OAuth 2.0 Authorization Code **with PKCE**,
 * opened in the user's REAL browser, redirected back to a loopback server this process owns
 * (RFC 8252). That is what this module does, and it has three further advantages worth keeping:
 *
 *   1. The frontend has no bundler — it is unbuilt ES modules — so not needing the ~150 KB Firebase
 *      SDK avoids vendoring a dependency the app would otherwise have no way to build.
 *   2. Every token stays in the MAIN process. The renderer is a web page talking to localhost; it
 *      never receives a refresh token, and cannot leak one.
 *   3. It is plain HTTPS calls, so it works identically in a packaged app and a dev checkout.
 *
 * Firebase still does the account bookkeeping: the Google ID token is exchanged for a Firebase
 * session through the Identity Toolkit REST API, so the user appears in the Firebase console and the
 * same account can later back real features without re-doing sign-in.
 */

const { BrowserWindow, safeStorage, shell } = require('electron');
const { createServer } = require('node:http');
const { createHash, randomBytes } = require('node:crypto');
const { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');

const { log } = require('./log');

const GOOGLE_AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth';
const GOOGLE_TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token';
const IDENTITY_TOOLKIT = 'https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp';
const SECURE_TOKEN = 'https://securetoken.googleapis.com/v1/token';

/** Only what an identity needs. No Drive, no Gmail, nothing that would make the consent screen scary. */
const SCOPES = ['openid', 'email', 'profile'];

/** How long to wait for the person to finish signing in in their browser before giving up. */
const SIGN_IN_TIMEOUT_MS = 5 * 60 * 1000;

// ---------------------------------------------------------------------------
// configuration
// ---------------------------------------------------------------------------

/**
 * Read firebase.config.json, or report that it is absent.
 *
 * Absent is a NORMAL state, not an error: the repository ships without credentials, and a source
 * checkout must still build and run. Sign-in reports "not configured" and everything else works.
 *
 * Looked for in three places so a user can configure a build they did not compile: an override in
 * their own data directory wins, then the packaged copy, then environment variables for CI.
 */
function loadConfig({ userDataDir, appPath }) {
  const candidates = [
    join(userDataDir, 'firebase.config.json'),
    join(appPath, 'firebase.config.json'),
    join(appPath, '..', 'firebase.config.json'),
  ];

  for (const path of candidates) {
    try {
      if (!existsSync(path)) continue;
      const parsed = JSON.parse(readFileSync(path, 'utf8'));
      if (parsed && parsed.apiKey && parsed.clientId) {
        log.info(`auth: config from ${path}`);
        return { ...parsed, source: path };
      }
      log.error(`auth: ${path} is missing apiKey or clientId; ignoring it`);
    } catch (err) {
      log.error(`auth: could not read ${path}: ${err.message}`);
    }
  }

  if (process.env.GOSSET_FIREBASE_API_KEY && process.env.GOSSET_FIREBASE_CLIENT_ID) {
    log.info('auth: config from environment');
    return {
      apiKey: process.env.GOSSET_FIREBASE_API_KEY,
      clientId: process.env.GOSSET_FIREBASE_CLIENT_ID,
      clientSecret: process.env.GOSSET_FIREBASE_CLIENT_SECRET || '',
      projectId: process.env.GOSSET_FIREBASE_PROJECT_ID || '',
      source: 'environment',
    };
  }

  log.info('auth: no Firebase configuration found — sign-in will report that it is unconfigured');
  return null;
}

// ---------------------------------------------------------------------------
// PKCE
// ---------------------------------------------------------------------------

const base64url = (buf) => buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

/**
 * A PKCE pair plus a state value.
 *
 * PKCE is what makes this safe without a client secret: the authorization code is bound to a verifier
 * only this process knows, so a code intercepted on its way back through the loopback redirect cannot
 * be redeemed by anyone else. `state` is checked on return to reject a request we did not start.
 */
function createPkce() {
  const verifier = base64url(randomBytes(32));
  const challenge = base64url(createHash('sha256').update(verifier).digest());
  return { verifier, challenge, state: base64url(randomBytes(16)) };
}

// ---------------------------------------------------------------------------
// the loopback redirect server
// ---------------------------------------------------------------------------

/**
 * Serve exactly one OAuth redirect, then stop.
 *
 * Bound to 127.0.0.1 on an OS-assigned port. Unlike the app's own port (which is fixed, because the
 * page origin owns localStorage), an ephemeral one is right here: it exists for seconds, the redirect
 * URI is sent to Google at the start of the flow, and a fixed port would be a fixed target.
 *
 * The browser gets a real HTML page back rather than a bare 200, because this is the last thing the
 * user sees of the process and "you can close this tab" is the whole message.
 */
function awaitRedirect({ expectedState, onListening }) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, arg) => {
      if (settled) return;
      settled = true;
      // Close after the response has flushed, or the browser shows a connection error instead of the
      // "you can close this tab" page.
      setTimeout(() => server.close(), 250);
      clearTimeout(timer);
      fn(arg);
    };

    const server = createServer((req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      if (url.pathname !== '/' && url.pathname !== '/callback') {
        res.writeHead(404).end();
        return;
      }

      const error = url.searchParams.get('error');
      const code = url.searchParams.get('code');
      const state = url.searchParams.get('state');

      const page = (title, message) =>
        `<!doctype html><meta charset="utf-8"><title>${title}</title>` +
        `<body style="font-family:system-ui,Segoe UI,sans-serif;background:#edeff2;color:#161616;` +
        `display:flex;align-items:center;justify-content:center;height:100vh;margin:0">` +
        `<div style="text-align:center;max-width:26rem;padding:2rem;background:#fff;border:1px solid #d5dae1;border-radius:4px">` +
        `<h1 style="font-size:1.1rem;margin:0 0 .5rem">${title}</h1>` +
        `<p style="margin:0;color:#6f6f6f;font-size:.9rem;line-height:1.5">${message}</p></div>`;

      if (error) {
        res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
        res.end(page('Sign-in cancelled', 'You can close this tab and return to Gosset.'));
        finish(reject, new Error(error === 'access_denied' ? 'Sign-in was cancelled.' : `Google returned: ${error}`));
        return;
      }

      // A mismatched state means this redirect belongs to a flow we did not start. Refuse it rather
      // than redeem a code an attacker chose.
      if (!code || state !== expectedState) {
        res.writeHead(400, { 'content-type': 'text/html; charset=utf-8' });
        res.end(page('Sign-in could not be completed', 'The response did not match this request. Please try again from Gosset.'));
        finish(reject, new Error('The sign-in response did not match this request.'));
        return;
      }

      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      res.end(page('Signed in to Gosset', 'You can close this tab and return to the app.'));
      finish(resolve, code);
    });

    const timer = setTimeout(
      () => finish(reject, new Error('Sign-in timed out. The browser window was left open too long.')),
      SIGN_IN_TIMEOUT_MS,
    );

    server.on('error', (err) => finish(reject, err));
    server.listen(0, '127.0.0.1', () => onListening(server.address().port));
  });
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function postForm(url, params) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(params).toString(),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(describeRemoteError(body, res.status));
  }
  return body;
}

async function postJson(url, payload) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(describeRemoteError(body, res.status));
  return body;
}

/**
 * Turn a Google/Firebase error body into something a person can act on.
 *
 * These APIs report configuration mistakes as opaque codes, and the two below are overwhelmingly the
 * most likely ones during setup — telling the user which console page to fix is worth more than the
 * raw string, which explains nothing.
 */
function describeRemoteError(body, status) {
  const raw = (body && (body.error_description || body.error?.message || body.error)) || `HTTP ${status}`;
  const code = String(raw);
  if (/OPERATION_NOT_ALLOWED/i.test(code)) {
    return 'Google sign-in is not enabled for this Firebase project. Enable it under Authentication → Sign-in method.';
  }
  if (/invalid_client|unauthorized_client/i.test(code)) {
    return 'The OAuth client ID was rejected. Check that it is a "Desktop app" client and matches firebase.config.json.';
  }
  if (/redirect_uri_mismatch/i.test(code)) {
    return 'Google rejected the redirect address. The OAuth client must be of type "Desktop app", which allows loopback redirects.';
  }
  if (/API key not valid|INVALID_API_KEY/i.test(code)) {
    return 'The Firebase apiKey in firebase.config.json is not valid for this project.';
  }
  return code;
}

// ---------------------------------------------------------------------------
// persistence
// ---------------------------------------------------------------------------

/**
 * The session on disk.
 *
 * Split deliberately into two files with different sensitivities:
 *
 *   account.json  the PROFILE — name, email, picture URL, and when it was captured. Not a secret, and
 *                 it must be readable with no network and no decryption, because the whole point of an
 *                 offline-first app is that closing the laptop lid does not sign you out.
 *   session.bin   the refresh token, encrypted with Electron's safeStorage, which on Windows is DPAPI
 *                 keyed to the user account. A refresh token is a long-lived credential; it does not
 *                 belong in localStorage (readable by any page the renderer loads) or in plain text.
 *
 * If encryption is unavailable, the refresh token is DISCARDED rather than written in the clear. The
 * cost is signing in again next launch; the alternative is a bearer credential sitting in a file.
 */
class SessionStore {
  constructor(userDataDir) {
    this.dir = userDataDir;
    this.profilePath = join(userDataDir, 'account.json');
    this.secretPath = join(userDataDir, 'session.bin');
  }

  readProfile() {
    try {
      const parsed = JSON.parse(readFileSync(this.profilePath, 'utf8'));
      return parsed && parsed.email ? parsed : null;
    } catch {
      return null;
    }
  }

  writeProfile(profile) {
    try {
      mkdirSync(this.dir, { recursive: true });
      writeFileSync(this.profilePath, JSON.stringify(profile, null, 2), 'utf8');
    } catch (err) {
      log.error(`auth: could not save the profile: ${err.message}`);
    }
  }

  readRefreshToken() {
    try {
      if (!existsSync(this.secretPath)) return null;
      if (!safeStorage.isEncryptionAvailable()) return null;
      return safeStorage.decryptString(readFileSync(this.secretPath)) || null;
    } catch (err) {
      // A machine-key change or a corrupt file. Not fatal: it means signing in again.
      log.info(`auth: stored session could not be decrypted (${err.message}); it will be discarded`);
      return null;
    }
  }

  writeRefreshToken(token) {
    try {
      if (!token) return;
      if (!safeStorage.isEncryptionAvailable()) {
        log.error('auth: OS encryption unavailable — the session will NOT be remembered rather than stored in plain text');
        return;
      }
      mkdirSync(this.dir, { recursive: true });
      writeFileSync(this.secretPath, safeStorage.encryptString(token));
    } catch (err) {
      log.error(`auth: could not save the session: ${err.message}`);
    }
  }

  clear() {
    for (const path of [this.profilePath, this.secretPath]) {
      try {
        if (existsSync(path)) unlinkSync(path);
      } catch (err) {
        log.error(`auth: could not remove ${path}: ${err.message}`);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

class Auth {
  constructor({ userDataDir, appPath }) {
    this.config = loadConfig({ userDataDir, appPath });
    this.store = new SessionStore(userDataDir);
    /** The signed-in profile, or null. Restored from disk at construction so it is available offline. */
    this.profile = this.store.readProfile();
    this.signingIn = false;

    if (this.profile) log.info(`auth: restored session for ${this.profile.email}`);
  }

  get configured() {
    return Boolean(this.config);
  }

  /** What the renderer needs to draw the account button. Never includes a token. */
  state() {
    return {
      configured: this.configured,
      signedIn: Boolean(this.profile),
      profile: this.profile
        ? {
            name: this.profile.name || '',
            email: this.profile.email || '',
            picture: this.profile.picture || '',
            provider: this.profile.provider || 'google.com',
            signedInAt: this.profile.signedInAt || '',
          }
        : null,
    };
  }

  /**
   * Run the whole flow: browser → loopback → Google tokens → Firebase session → profile on disk.
   *
   * Rejects with a message written for the person who pressed the button, not the developer.
   */
  async signIn() {
    if (!this.configured) {
      throw new Error(
        'Sign-in is not set up in this build of Gosset. See docs/FIREBASE_SETUP.md to add a Firebase project.',
      );
    }
    if (this.signingIn) throw new Error('A sign-in is already in progress. Check your browser.');
    this.signingIn = true;

    try {
      const { verifier, challenge, state } = createPkce();
      let redirectUri = null;

      const codePromise = awaitRedirect({
        expectedState: state,
        onListening: (port) => {
          redirectUri = `http://127.0.0.1:${port}`;
          const url = new URL(GOOGLE_AUTH_ENDPOINT);
          url.searchParams.set('client_id', this.config.clientId);
          url.searchParams.set('redirect_uri', redirectUri);
          url.searchParams.set('response_type', 'code');
          url.searchParams.set('scope', SCOPES.join(' '));
          url.searchParams.set('code_challenge', challenge);
          url.searchParams.set('code_challenge_method', 'S256');
          url.searchParams.set('state', state);
          // Ask every time rather than silently reusing a Google session: on a shared machine, a
          // sign-in button that instantly adopts whoever used the browser last is a surprise.
          url.searchParams.set('prompt', 'select_account');

          log.info('auth: opening the system browser for consent');
          // The SYSTEM browser, not a BrowserWindow — see the note at the top of this file. This is
          // also why the user can use their existing Google session and password manager.
          shell.openExternal(url.toString());
        },
      });

      const code = await codePromise;
      log.info('auth: authorization code received');

      // Exchange the code. A "Desktop app" client is public, so PKCE is the proof; client_secret is
      // sent only if the config carries one (Google issues one for installed apps and does not treat
      // it as confidential, but omitting it works and is one less pseudo-secret to ship).
      const tokenParams = {
        client_id: this.config.clientId,
        code,
        code_verifier: verifier,
        grant_type: 'authorization_code',
        redirect_uri: redirectUri,
      };
      if (this.config.clientSecret) tokenParams.client_secret = this.config.clientSecret;

      const googleTokens = await postForm(GOOGLE_TOKEN_ENDPOINT, tokenParams);
      if (!googleTokens.id_token) throw new Error('Google did not return an identity token.');

      // Hand the Google identity to Firebase, so the account exists in the project and the same
      // sign-in can later support features that need a Firebase session.
      const firebase = await postJson(`${IDENTITY_TOOLKIT}?key=${encodeURIComponent(this.config.apiKey)}`, {
        postBody: `id_token=${googleTokens.id_token}&providerId=google.com`,
        requestUri: redirectUri,
        returnIdpCredential: true,
        returnSecureToken: true,
      });

      const profile = {
        uid: firebase.localId || '',
        name: firebase.displayName || firebase.fullName || '',
        email: firebase.email || '',
        picture: firebase.photoUrl || '',
        provider: 'google.com',
        signedInAt: new Date().toISOString(),
      };

      this.profile = profile;
      this.store.writeProfile(profile);
      this.store.writeRefreshToken(firebase.refreshToken || '');
      log.info(`auth: signed in as ${profile.email}`);
      return this.state();
    } finally {
      this.signingIn = false;
    }
  }

  /**
   * Forget the session locally.
   *
   * Deliberately does NOT revoke the Google grant. Signing out of an app should not reach into the
   * user's Google account and remove a permission they may have granted elsewhere; the app's own
   * copy of the identity is what it is entitled to delete. The account panel links to Google's
   * permissions page for anyone who wants the grant gone too.
   *
   * Also clears the Electron session cookies for accounts.google.com if any exist, so a subsequent
   * sign-in on a shared machine cannot silently reuse the previous person's session.
   */
  async signOut() {
    const who = this.profile ? this.profile.email : '(nobody)';
    this.profile = null;
    this.store.clear();
    try {
      const win = BrowserWindow.getAllWindows()[0];
      if (win) await win.webContents.session.clearStorageData({ storages: ['cookies'], origin: 'https://accounts.google.com' });
    } catch {
      /* the flow uses the system browser, so there is usually nothing here to clear */
    }
    log.info(`auth: signed out ${who}`);
    return this.state();
  }

  /**
   * Refresh the Firebase session, if there is one to refresh.
   *
   * Not needed to DISPLAY an identity — the cached profile covers that, offline. It exists so a stale
   * session can be detected: if the refresh token has been revoked (password change, account removed,
   * grant withdrawn), the local session is cleared rather than showing a name that no longer has an
   * account behind it. Called opportunistically, never on the startup path, and silent on failure to
   * reach the network.
   */
  async refresh() {
    if (!this.configured || !this.profile) return this.state();
    const refreshToken = this.store.readRefreshToken();
    if (!refreshToken) return this.state();

    try {
      await postForm(`${SECURE_TOKEN}?key=${encodeURIComponent(this.config.apiKey)}`, {
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
      });
      return this.state();
    } catch (err) {
      const message = String(err.message || err);
      // Only a definite rejection signs the user out. A network failure must not: that would mean
      // going offline logs you out, which is exactly what this app promises not to do.
      if (/TOKEN_EXPIRED|USER_DISABLED|USER_NOT_FOUND|INVALID_REFRESH_TOKEN|invalid_grant/i.test(message)) {
        log.info(`auth: stored session is no longer valid (${message}); signing out`);
        return this.signOut();
      }
      log.info(`auth: session refresh skipped (${message})`);
      return this.state();
    }
  }
}

module.exports = { Auth, loadConfig };
