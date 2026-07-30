# Setting up Google sign-in

Gosset can show who you are: your name and picture in the menu bar, and your name on the cover of
reports you export. That is **all** it does — nothing is uploaded, no feature is gated, and the app
works exactly the same signed out. If you never do this, Gosset is fully functional; the Account panel
just says sign-in is not set up.

You need a Firebase project, which takes about five minutes. I cannot create one for you: it belongs to
your Google account.

---

## What you are creating, and why there are two IDs

Two things, from two consoles, and it is easy to conflate them:

| Value | Where from | What it is |
|---|---|---|
| `apiKey`, `authDomain`, `projectId` | **Firebase** console | Identifies the Firebase project that keeps the list of accounts |
| `clientId` | **Google Cloud** console | Identifies *this application* to Google's sign-in service |

The `clientId` must be of type **Desktop app**. This is the part people get wrong, and the failure is
confusing: a "Web application" client rejects the loopback redirect Gosset uses and Google returns
`redirect_uri_mismatch`.

---

## 1. Create the Firebase project

1. Go to <https://console.firebase.google.com> and click **Add project**.
2. Give it a name (`gosset` is fine). You do **not** need Google Analytics — turn it off.
3. Wait for it to finish, then click **Continue**.

## 2. Turn on Google sign-in

1. In the left sidebar: **Build → Authentication**, then **Get started**.
2. Open the **Sign-in method** tab.
3. Click **Google**, toggle **Enable**, choose a support email, and **Save**.

> If you skip this, sign-in fails with `OPERATION_NOT_ALLOWED`. Gosset translates that into a message
> pointing you back here.

## 3. Get `apiKey`, `authDomain` and `projectId`

1. Click the **gear icon → Project settings**.
2. Under **Your apps**, click the **web** icon (`</>`) to register a web app. Name it `Gosset`; you do
   not need Firebase Hosting.
3. You will be shown a `firebaseConfig` snippet. Copy `apiKey`, `authDomain` and `projectId` out of it.

> A web app is registered even though Gosset is a desktop app. That is deliberate: it is what mints the
> `apiKey` for the REST endpoints Gosset uses. No web page is ever deployed.

## 4. Create the Desktop OAuth client — the important step

1. Go to <https://console.cloud.google.com/apis/credentials> and make sure the project selector at the
   top shows the project you just created.
2. If prompted to configure a **consent screen**: choose **External**, fill in an app name and your
   email, and save. While it is in "Testing" mode, add your own Google address under **Test users**, or
   sign-in will be refused for accounts you have not listed.
3. **Create credentials → OAuth client ID**.
4. **Application type: Desktop app**. Name it `Gosset desktop`.
5. **Create**, then copy the **Client ID** (it ends in `.apps.googleusercontent.com`).

You can ignore the client secret. Gosset uses PKCE, and Google does not treat an installed-app secret as
confidential.

## 5. Publish the consent screen — needed for anyone but you

This is the step that decides whether **other people** can sign in, and it is easy to miss because
sign-in will already work for you without it.

A new OAuth consent screen starts in **Testing** mode, where Google permits only accounts you have
listed as test users. Everyone else gets `403: access_denied`, which reads like a bug in the app.

1. Go to <https://console.cloud.google.com/apis/credentials/consent>.
2. Check **Publishing status**.
   - **Testing** → only your listed test users can sign in.
   - **In production** → any Google account can sign in.
3. If it says Testing, click **Publish app** and confirm.

**No Google review is required for this app.** Verification is only demanded for "sensitive" or
"restricted" scopes — reading someone's Drive, Gmail, contacts. Gosset asks for `openid`, `email` and
`profile`, which are the non-sensitive basics, so publishing takes effect immediately.

Users will see an "unverified app" notice on the consent screen unless you later complete Google's brand
verification. It is cosmetic, it does not block sign-in, and it is the same trade-off as the unsigned
installer: stated plainly rather than worked around.

## 6. Give the values to Gosset

Copy the example file and fill it in:

```bash
cd desktop
cp firebase.config.example.json firebase.config.json
```

```json
{
  "apiKey": "AIzaSy…",
  "authDomain": "gosset-xxxxx.firebaseapp.com",
  "projectId": "gosset-xxxxx",
  "clientId": "000000000000-xxxxxxxx.apps.googleusercontent.com",
  "clientSecret": ""
}
```

`firebase.config.json` is **gitignored** — it names your project, and a fork should use its own.

Then restart Gosset (or rebuild, for an installed copy) and use **Help → Account**.

### Configuring an installed copy without rebuilding

Gosset also reads the file from its per-user data directory, which wins over the packaged one:

```
%APPDATA%\Gosset\firebase.config.json
```

Useful for trying values out against an installed build. For CI, the same values can come from
`GOSSET_FIREBASE_API_KEY`, `GOSSET_FIREBASE_CLIENT_ID`, `GOSSET_FIREBASE_CLIENT_SECRET` and
`GOSSET_FIREBASE_PROJECT_ID`.

---

## Are these values secrets?

**No, and it matters that you know that**, because they end up in a public repository's build.

A Firebase web `apiKey` and an OAuth `clientId` are *public identifiers*. They ship inside every web and
mobile app that uses Firebase and are visible to anyone who looks. They are not credentials: neither one
grants access to anything on its own. What actually protects a Firebase project is its **security
rules**, and Gosset's OAuth client is additionally limited to redirecting to loopback addresses on the
machine running the app.

What *would* be a secret is a **service account key** (a JSON file with a `private_key`). Gosset never
needs one. If you ever find yourself downloading one for this, something has gone wrong.

The genuinely sensitive item at runtime is the **refresh token** issued after you sign in. Gosset
encrypts it with the OS keychain — DPAPI on Windows, via Electron's `safeStorage` — and if encryption is
unavailable it discards the token rather than writing it to disk in the clear, meaning you sign in again
next launch.

---

## How the sign-in actually works

Worth knowing, because it explains why it opens your browser rather than a window inside the app:

1. Gosset starts a one-shot HTTP server on `127.0.0.1` on a random port.
2. It opens **your normal browser** at Google's consent page, with a PKCE challenge and that loopback
   address as the redirect.
3. You sign in to Google — in your own browser, with your own password manager and 2FA. Gosset never
   sees your password, and cannot: the page is not inside the app.
4. Google redirects back to the loopback server with a one-time code.
5. Gosset exchanges the code (proving it holds the PKCE verifier) for a Google identity token, then
   trades that with Firebase for a session, and stores your name, email and picture.

Google **blocks** OAuth inside embedded browser frames, which is why the usual
`signInWithPopup` cannot work in a desktop app: an Electron window counts as one, and the consent screen
returns `403: disallowed_useragent`. Opening the real browser is the supported pattern
([RFC 8252](https://datatracker.ietf.org/doc/html/rfc8252)), and it is better for you anyway.

---

## Troubleshooting

| What you see | Cause |
|---|---|
| *Sign-in is not set up in this build* | No `firebase.config.json` found, or it lacks `apiKey`/`clientId` |
| `OPERATION_NOT_ALLOWED` | Google provider not enabled — step 2 |
| `redirect_uri_mismatch` | The OAuth client is not type **Desktop app** — step 4 |
| `invalid_client` | `clientId` does not match the project, or is a Web client |
| `API key not valid` | `apiKey` belongs to a different project |
| `403: access_denied` for other users | Consent screen still in **Testing** — publish it, step 5 |
| `403: access_denied` for you | Consent screen in Testing and your address is not a listed test user — step 4.2 |
| Browser opens but nothing happens | The one-shot server has a five-minute timeout; try again |

Gosset translates the first several of these into plain-language messages in the Account panel, so you
should not often be reading raw codes. The full detail is in `%APPDATA%\Gosset\gosset.log`.
