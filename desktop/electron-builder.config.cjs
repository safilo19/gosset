/**
 * electron-builder: the Windows NSIS installer.
 *
 * A .cjs config rather than YAML because two paths have to be COMPUTED, not written down:
 * the PyInstaller bundle and the installer output both live outside the repository (see
 * scripts/paths.mjs for why — this repo sits in a OneDrive folder, and build artifacts in a synced
 * directory break rebuilds). YAML cannot express that, and hardcoding an absolute path would break
 * on CI.
 *
 * The version is NOT set here. electron-builder reads it from package.json, which is the single
 * source of truth that scripts/stamp-version.mjs propagates into the app's About window and the PDF
 * footers. Setting it in two places is how they drift.
 */

const { existsSync } = require('node:fs');
const { join } = require('node:path');

// paths.mjs is ESM and this config is CJS, so the constants are recomputed here rather than imported.
// Kept deliberately trivial and in one place; if these ever diverge the installer ships with no
// backend, so build-sidecar.mjs asserts its own output exists and the check below asserts it again.
const buildDir =
  process.env.GOSSET_BUILD_DIR ||
  join(process.env.LOCALAPPDATA || require('node:os').homedir(), 'gosset-build');
const sidecarDir = join(buildDir, 'sidecar', 'gosset-sidecar');

// Fail the build here, with a sentence that says what to do, rather than shipping an installer whose
// app cannot start. This is the single most expensive mistake this config could make: the installer
// looks fine, installs fine, and the app dies on launch on someone else's machine.
if (!existsSync(join(sidecarDir, 'gosset-sidecar.exe'))) {
  throw new Error(
    `The Python sidecar is not built.\n` +
      `  expected: ${join(sidecarDir, 'gosset-sidecar.exe')}\n` +
      `  fix:      run \`npm run build:sidecar\` in desktop/ first (or \`npm run build\`, which does both).`,
  );
}

module.exports = {
  appId: 'com.gosset.workbench',
  productName: 'Gosset',
  copyright: `Copyright © ${new Date().getFullYear()} Gosset. All rights reserved.`,

  directories: {
    // build/ holds icon.ico and gsp.ico, generated from mark.svg by scripts/make_app_icons.py.
    buildResources: 'build',
    output: join(buildDir, 'electron'),
  },

  // Only the shell's own code. The frontend and the Python backend both travel inside the sidecar
  // bundle (the frontend is SERVED by FastAPI, not loaded from disk by Electron), so packaging them
  // here as well would ship two copies and let them disagree.
  files: ['src/**/*', 'package.json'],

  extraResources: [
    {
      from: sidecarDir,
      to: 'sidecar/gosset-sidecar',
      // .pyc caches and PyInstaller's own build leftovers are not runtime files.
      filter: ['**/*', '!**/__pycache__/**', '!**/*.pyc'],
    },
  ],

  // The bundle is ~265 MB of already-compressed wheels and DLLs; 'maximum' spends several minutes of
  // build time to save very little, because there is little left to squeeze.
  compression: 'normal',

  // The publish provider. Its FIRST job is not publishing — declaring it is what makes electron-builder
  // emit `latest.yml` and the `.blockmap` alongside the installer, and those two files ARE the update
  // feed: electron-updater fetches latest.yml to learn what the newest version is, and the blockmap is
  // what lets it download only the changed chunks of a 186 MB installer instead of all of it. Without
  // a publish config you get a perfectly good installer that no existing install can ever discover.
  //
  // owner/repo are explicit rather than inferred from the git remote, so the update feed does not
  // silently change if someone builds from a fork.
  //
  // No token appears here. In Actions, GITHUB_TOKEN arrives through the environment; locally,
  // `--publish never` means this config is only ever read for its filenames.
  publish: [
    {
      provider: 'github',
      owner: 'safilo19',
      repo: 'personal-analytics-mcp',
      // Publish immediately rather than as a draft: a draft release is invisible to electron-updater,
      // so a drafted release would look to every installed copy exactly like no release at all.
      releaseType: 'release',
    },
  ],

  win: {
    target: [{ target: 'nsis', arch: ['x64'] }],
    icon: 'build/icon.ico',
    // The executable's icon and version metadata still get written (that is the "edit" half).
    signAndEditExecutable: true,

    // No signing — see the README's download section: the installer is unsigned because a
    // code-signing certificate costs money, so SmartScreen shows "unrecognized app" on first run.
    // That is stated plainly to users rather than worked around.
    //
    // BUILD PREREQUISITE, because there is no config setting that avoids it: electron-builder fetches
    // its winCodeSign toolchain even with no certificate present. It logs
    // `no signing info identified, signing is skipped` and downloads it anyway, and that archive
    // carries macOS symlinks whose extraction needs a privilege Windows does not grant by default:
    //
    //     ERROR: Cannot create symbolic link ... darwin/10.12/lib/libcrypto.dylib
    //     A required privilege is not held by the client
    //
    // after which the build fails on its fourth retry. Neither CSC_IDENTITY_AUTO_DISCOVERY=false nor
    // a custom no-op `sign` hook prevents the download — both were tried and measured.
    //
    // The fix is to seed that cache yourself, WITHOUT the darwin tree (which a Windows build never
    // touches). The release workflow has a step that does it; for a local build, run the same thing
    // once — see "The installer" in the README.
    fileAssociations: [
      {
        ext: 'gsp',
        name: 'Gosset Project',
        description: 'Gosset Project',
        icon: 'build/gsp.ico',
        // Editor, not Viewer: opening a project and then saving over it is the normal flow.
        role: 'Editor',
      },
    ],
  },

  nsis: {
    // Per-user, so installing needs no administrator and no UAC prompt. The consequence to keep in
    // mind: the app lands in %LOCALAPPDATA%\Programs\Gosset, which is per-user and writable — which
    // is exactly why the app must NOT write reports there (it uses userData/output instead).
    oneClick: false,
    perMachine: false,
    allowElevation: false,
    allowToChangeInstallationDirectory: true,

    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: 'Gosset',

    // The uninstaller removes the shortcuts and the file association. It deliberately does NOT
    // remove %APPDATA%\Gosset — that holds the user's window position, options and any reports they
    // exported, and an uninstaller that deletes documents is a bug.
    deleteAppDataOnUninstall: false,

    // A stable GUID so an upgrade replaces the previous install instead of appearing as a second
    // "Gosset" entry in Apps & features. Never change this once a release has shipped.
    guid: 'e3a3f4f2-6d1c-4a95-9b8e-2f7c5a1d0b64',

    artifactName: 'Gosset-Setup-${version}.${ext}',
    uninstallDisplayName: 'Gosset ${version}',
  },
};
