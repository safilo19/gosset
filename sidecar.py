"""The backend as a desktop sidecar: one process, one port, spoken to only by the Electron shell.

This is the PyInstaller entry point (see desktop/gosset-sidecar.spec). It is a third front door onto
the same analysis code, alongside `uvicorn backend.api:app` for development and `mcp_server.py` for
MCP clients — none of them share state and none of them are a wrapper around another.

Three things here exist only because the process is frozen and parentless:

* **The port is given, never chosen.** Electron picks a free one and passes it, so the shell knows
  the URL before the server is up and never has to scrape stdout for it.
* **Output goes where the shell says.** In a checkout, reports land in ./output. Inside an installed
  app that directory is under Program Files-equivalent and must not be written to, so the shell
  passes GOSSET_OUTPUT_DIR and reports land in the user's own data directory.
* **It dies with its parent.** --parent-pid makes the sidecar poll for the shell and exit if it
  disappears, so a hard-killed Electron (Task Manager, a crash) cannot leave a Python process
  holding a port. The shell also kills the sidecar from its side; this is the backstop for when the
  shell is what died.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import threading
import time


def _watch_parent(parent_pid: int, interval: float = 2.0) -> None:
    """Exit this process once `parent_pid` is gone.

    NEVER use os.kill(pid, 0) for this on Windows. It is the standard POSIX liveness probe — signal 0
    checks permission to signal without sending anything — but CPython's Windows implementation of
    os.kill maps every signal other than CTRL_C_EVENT and CTRL_BREAK_EVENT onto TerminateProcess. So
    `os.kill(parent_pid, 0)` does not ASK whether the parent is alive, it KILLS it. This watcher's
    first tick was silently terminating the Electron shell about two seconds after launch: the shell
    logged a clean startup, spawned the sidecar, and then vanished with no error, no exception and no
    lifecycle event, because it had been shot from the process it just started.

    The Windows way is to open a handle and wait on it. WaitForSingleObject on a process handle
    returns when the process exits, so there is no polling and no interval to tune — and no signal is
    ever sent.

    os._exit rather than sys.exit either way: this runs on a daemon thread, where a raised SystemExit
    would be swallowed and the server would keep serving.
    """
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        INFINITE = 0xFFFFFFFF

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
        if not handle:
            # The parent is already gone, or not ours to open. Either way this backstop cannot run —
            # the shell still kills the sidecar from its side, which is the primary path.
            return
        try:
            kernel32.WaitForSingleObject(handle, INFINITE)
        finally:
            kernel32.CloseHandle(handle)
        os._exit(0)

    while True:
        time.sleep(interval)
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            os._exit(0)
        except PermissionError:
            pass  # alive, just not ours to signal
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gosset-sidecar", description="Gosset backend sidecar")
    parser.add_argument("--port", type=int, required=True, help="TCP port to serve on (chosen by the shell)")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (loopback only, by default)")
    parser.add_argument("--output-dir", default=None, help="where generated reports are written")
    parser.add_argument("--parent-pid", type=int, default=None, help="exit when this process disappears")
    args = parser.parse_args(argv)

    # Set before importing the app: backend.core.reports reads GOSSET_OUTPUT_DIR at import time.
    if args.output_dir:
        os.environ["GOSSET_OUTPUT_DIR"] = args.output_dir

    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(args.parent_pid,), daemon=True).start()

    import uvicorn

    from backend.api import app

    # The app object, not an "backend.api:app" import string: a frozen build has no importable
    # module path for uvicorn to re-resolve, and passing a string is what silently turns into
    # "Could not import module" inside the bundle. Reload and workers are off for the same reason —
    # both re-exec the interpreter, which under PyInstaller re-runs the bootloader instead.
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    # Required before anything may spawn a process in a frozen build; without it, any library that
    # reaches for multiprocessing (joblib, under scikit-learn) re-runs this whole script in the child
    # and forks servers until the machine gives up.
    multiprocessing.freeze_support()
    sys.exit(main())
