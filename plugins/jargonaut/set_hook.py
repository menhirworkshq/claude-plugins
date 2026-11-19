#!/usr/bin/env python3
"""Point Vocalinux's post-processing script path at the jargonaut hook.

Usage: set_hook.py [--force] [--hook PATH] [--allow-running]

Vocalinux's config.json holds secrets, so this script never prints its content:
only the current script path and the names of the post_processing settings.
A different script path already set is kept unless --force is given (exit
code 3), so that the caller can ask the user first. The file is rewritten
atomically, keeping its mode and its 4-space indentation.

Vocalinux reads config.json once at start and rewrites it whole on every save,
so an edit made while it runs is ignored and can be reverted: the script refuses
to run while Vocalinux runs (exit code 4).
"""

import argparse
import json
import os
import sys
import tempfile

import paths

EXIT_OTHER_HOOK = 3
EXIT_RUNNING = 4


def vocalinux_running():
    """Whether a Vocalinux process runs, from /proc (Linux only)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        # The GUI runs as `python .../bin/vocalinux-gui`, its helpers from the vocalinux package.
        if any(os.path.basename(a).startswith(b"vocalinux") or b"/site-packages/vocalinux/" in a for a in argv[:2]):
            return True
    return False


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="replace a different script path")
    parser.add_argument("--hook", default=str(paths.hook()), help="script path to set (default: %(default)s)")
    parser.add_argument("--allow-running", action="store_true",
                        help="skip the running check, for a config file Vocalinux does not use")
    args = parser.parse_args(argv)

    if not args.allow_running and vocalinux_running():
        print("Vocalinux is running: quit it first, it would ignore and later revert the change", file=sys.stderr)
        return EXIT_RUNNING

    config_path = paths.vocalinux_config()
    try:
        text = config_path.read_text()
        config = json.loads(text)
    except FileNotFoundError:
        print(f"{config_path} does not exist: open Vocalinux's Settings once, then run again", file=sys.stderr)
        return 1
    except json.JSONDecodeError:
        print(f"{config_path} is not valid JSON; not touching it", file=sys.stderr)
        return 1

    section = config.setdefault("post_processing", {})
    if not isinstance(section, dict):
        print("post_processing is not an object in the Vocalinux config; not touching it", file=sys.stderr)
        return 1
    others = sorted(k for k in section if k != "script_path")
    if others:
        print("other post_processing settings: " + ", ".join(others))

    current = section.get("script_path") or ""
    hook = os.path.expanduser(args.hook)
    if current == hook:
        print(f"script path already set to {hook}")
        return 0
    if current and not args.force:
        print(f"another script path is set: {current}", file=sys.stderr)
        print("run again with --force to replace it", file=sys.stderr)
        return EXIT_OTHER_HOOK

    section["script_path"] = hook
    mode = config_path.stat().st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=config_path.parent, prefix=".config.json.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
            if text.endswith("\n"):
                f.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, config_path)
    except BaseException:
        os.unlink(tmp)
        raise
    print(f"script path set to {hook}" + (f" (was {current})" if current else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
