#!/usr/bin/env python3
"""Install the launchers that Vocalinux and systemd use to reach this plugin.

Writes, for the plugin folder this script lives in:
  ~/.local/bin/jargonaut-hook    the post-processing script Vocalinux runs
  ~/.local/bin/jargonaut-daemon  the daemon the user unit runs
  ~/.config/systemd/user/jargonaut.service

Vocalinux and the unit only know the launchers, so after the plugin moves or
is updated, run this script again from the new folder and restart the service.

Usage: launchers.py [--bin-dir DIR] [--unit-dir DIR] [--check]
  --check  exit 1 if a launcher or the unit is missing or out of date
"""

import argparse
import os
import shlex
import sys
import tempfile
from pathlib import Path

import paths

LAUNCHERS = {
    "jargonaut-hook": "haiku/postproc_hook.py",
    "jargonaut-daemon": "haiku/postproc_daemon.py",
}
UNIT = "jargonaut.service"


def launcher(target):
    # An absolute interpreter: Vocalinux and systemd do not give a login PATH.
    return f"#!/bin/sh\nexec /usr/bin/python3 {shlex.quote(str(target))} \"$@\"\n"


def wanted(bin_dir, unit_dir):
    files = {bin_dir / name: (launcher(paths.PLUGIN_DIR / rel), 0o755) for name, rel in LAUNCHERS.items()}
    files[unit_dir / UNIT] = ((paths.PLUGIN_DIR / "systemd" / UNIT).read_text(encoding="utf-8"), 0o644)
    return files


def write_atomic(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        path.unlink()  # an older install linked the unit into the plugin folder
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def main(argv):
    parser = argparse.ArgumentParser(description="Install the jargonaut launchers and user unit.")
    parser.add_argument("--bin-dir", type=Path, default=paths.bin_dir())
    parser.add_argument("--unit-dir", type=Path, default=paths.unit_dir())
    parser.add_argument("--check", action="store_true", help="exit 1 if anything is missing or out of date")
    args = parser.parse_args(argv)

    stale = []
    for path, (content, mode) in wanted(args.bin_dir, args.unit_dir).items():
        current = path.read_text(encoding="utf-8") if path.is_file() and not path.is_symlink() else None
        if current == content:
            continue
        stale.append(path)
        if not args.check:
            write_atomic(path, content, mode)
            print(f"wrote {path}")
    if args.check:
        for path in stale:
            print(f"{path} is missing or out of date, run {Path(__file__).name}", file=sys.stderr)
        return 1 if stale else 0
    if not stale:
        print(f"launchers already point at {paths.PLUGIN_DIR}")
    elif any(p.name == UNIT for p in stale):
        print("unit changed: run `systemctl --user daemon-reload`")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
