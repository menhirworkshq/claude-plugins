#!/usr/bin/env python3
"""Install the jargonaut runtime: the code Vocalinux and systemd run.

The daemon and the hook run outside Claude Code, so they must not depend on
where Claude Code keeps the plugin (its cache folder changes on every update).
This script installs them at a fixed place, the app dir
($XDG_DATA_HOME/jargonaut/app), and writes launchers and the user unit that
only know that place:

  ~/.local/bin/jargonaut-hook    Vocalinux's post-processing script
  ~/.local/bin/jargonaut-daemon  what the unit runs
  ~/.config/systemd/user/jargonaut.service

Modes:
  (default)  copy this plugin folder to the app dir; a plugin update changes
             nothing until install.py runs again
  --link     make the app dir a symlink to this folder (a checkout or a
             worktree), so edits take effect on the next segment or restart

Usage: install.py [--link] [--no-service] [--check] [--session-check]
  --no-service     write the files but do not touch systemd
  --check          exit 1 when the installed runtime differs from this folder
  --session-check  for the SessionStart hook: print a JSON notice when the
                   installed copy is older than this plugin, nothing otherwise
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import paths

UNIT = "jargonaut.service"
# Not part of the runtime: Claude Code components and local caches.
EXCLUDE = {"skills", "hooks", ".claude-plugin", "__pycache__", ".git"}


def runtime_files(root):
    """Relative paths of the files that make up the runtime, sorted."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE)
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            files.append((Path(dirpath) / name).relative_to(root))
    return sorted(files)


def fingerprint(root):
    """A hash of the runtime files, to tell 2 copies apart without git."""
    h = hashlib.sha256()
    for rel in runtime_files(root):
        h.update(str(rel).encode() + b"\0" + (root / rel).read_bytes() + b"\0")
    return h.hexdigest()[:12]


def installed_state(app):
    """('missing' | 'link' | 'copy', detail)."""
    if app.is_symlink():
        return "link", Path(os.readlink(app))
    version = app / "VERSION"
    if version.is_file():
        return "copy", json.loads(version.read_text(encoding="utf-8"))
    return "missing", None


def launcher(target, missing):
    return (
        "#!/bin/sh\n"
        "# Written by jargonaut install.py; rerun it instead of editing this file.\n"
        f"target={shlex.quote(str(target))}\n"
        f'[ -f "$target" ] || {missing}\n'
        # An absolute interpreter: Vocalinux and systemd give no login PATH.
        'exec /usr/bin/python3 "$target" "$@"\n'
    )


def write_atomic(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        path.unlink()  # older installs linked the unit into the plugin folder
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def install_app(app, source, link):
    """Replace the app dir by a copy of (or a link to) source, atomically."""
    app.parent.mkdir(parents=True, exist_ok=True)
    staging = app.with_name(app.name + ".new")
    if staging.is_symlink() or staging.is_file():
        staging.unlink()
    elif staging.exists():
        shutil.rmtree(staging)
    if link:
        staging.symlink_to(source, target_is_directory=True)
    else:
        for rel in runtime_files(source):
            (staging / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, staging / rel)
        info = {"fingerprint": fingerprint(source), "source": str(source)}
        (staging / "VERSION").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    old = app.with_name(app.name + ".old")
    if app.is_symlink() or app.exists():
        if old.exists() and not old.is_symlink():
            shutil.rmtree(old)
        elif old.is_symlink():
            old.unlink()
        os.replace(app, old)
    os.replace(staging, app)
    if old.is_symlink():
        old.unlink()
    elif old.exists():
        shutil.rmtree(old)


def write_entry_points(app):
    bin_dir = paths.bin_dir()
    write_atomic(bin_dir / "jargonaut-hook",
                 # Without the runtime, type the text unchanged: dictation keeps working.
                 launcher(app / "haiku" / "postproc_hook.py", "exec cat"), 0o755)
    write_atomic(bin_dir / "jargonaut-daemon",
                 launcher(app / "haiku" / "postproc_daemon.py",
                          '{ echo "jargonaut is not installed: run install.py" >&2; exit 1; }'), 0o755)
    unit = (app / "systemd" / UNIT).read_text(encoding="utf-8")
    write_atomic(paths.unit_dir() / UNIT, unit, 0o644)


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def restart_service():
    systemctl("daemon-reload")
    if systemctl("is-enabled", UNIT).stdout.strip() == "enabled":
        systemctl("restart", UNIT)
        return "restarted"
    result = systemctl("enable", "--now", UNIT)
    return "enabled and started" if result.returncode == 0 else f"could not start: {result.stderr.strip()}"


def up_to_date(app, source):
    kind, detail = installed_state(app)
    if kind == "link":
        return Path(detail).resolve() == source
    if kind == "copy":
        return detail.get("fingerprint") == fingerprint(source)
    return False


def session_check(app, source):
    kind, detail = installed_state(app)
    # Not installed (the user has not run the install skill) or linked to a
    # checkout on purpose: nothing to say.
    if kind != "copy" or detail.get("fingerprint") == fingerprint(source):
        return 0
    message = ("jargonaut: the installed runtime differs from this version of the plugin "
               "(the daemon and the Vocalinux hook still run the old code). "
               "Run /jargonaut:install to update it.")
    print(json.dumps({
        "systemMessage": message,
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message},
    }))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description="Install the jargonaut runtime, launchers and user unit.")
    parser.add_argument("--link", action="store_true", help="link the app dir to this folder instead of copying it")
    parser.add_argument("--no-service", action="store_true", help="do not reload, enable or restart the unit")
    parser.add_argument("--check", action="store_true", help="exit 1 if the installed runtime differs from this folder")
    parser.add_argument("--session-check", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    source, app = paths.PLUGIN_DIR, paths.app_dir()

    if args.session_check:
        return session_check(app, source)
    if args.check:
        if up_to_date(app, source):
            return 0
        print(f"{app} is not the runtime of {source}: run {Path(__file__).name}", file=sys.stderr)
        return 1
    if source == app.resolve() and not app.is_symlink():
        raise SystemExit("run install.py from the plugin folder, not from the installed copy")

    install_app(app, source, args.link)
    write_entry_points(app)
    how = f"linked to {source}" if args.link else f"copied from {source} ({fingerprint(source)})"
    print(f"runtime {how} into {app}")
    print(f"hook: {paths.hook()}")
    if not args.no_service:
        print(f"{UNIT}: {restart_service()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
