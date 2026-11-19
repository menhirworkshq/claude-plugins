#!/usr/bin/env python3
"""Generate jargonaut outputs from vocab.toml.

Today it writes Vocalinux's deterministic corrections: every heard form of an
entry that is not ambiguous. Ambiguous heard forms are ordinary text too, so
they are left to the LLM pass.

Usage: generate.py [--check]
  --check  exit 1 if the generated file differs from the one on disk

Reads vocab.toml from the config dir and writes
$XDG_CONFIG_HOME/vocalinux/custom-dictionary-corrections.json (see paths.py
for the overrides).
"""

import argparse
import json
import os
import sys
import tempfile
import tomllib
import unicodedata
from pathlib import Path

import paths

# Vocalinux ignores entries past this limit.
MAX_CORRECTIONS = 500


def load_terms(path):
    with path.open("rb") as f:
        return tomllib.load(f).get("term", [])


def key(text):
    return unicodedata.normalize("NFC", text.strip()).casefold()


def build_corrections(terms):
    safe = {}
    ambiguous = {}
    errors = []
    for entry in terms:
        target = ambiguous if entry.get("ambiguous", False) else safe
        for heard in entry.get("heard", []):
            k = key(heard)
            previous = safe.get(k) or ambiguous.get(k)
            if previous and previous[1] != entry["term"]:
                errors.append(f"{heard!r} is heard as both {previous[1]!r} and {entry['term']!r}")
            target[k] = (heard, entry["term"])
    for k in safe.keys() & ambiguous.keys():
        errors.append(f"{safe[k][0]!r} is both safe and ambiguous")
    if len(safe) > MAX_CORRECTIONS:
        errors.append(f"{len(safe)} corrections, Vocalinux reads at most {MAX_CORRECTIONS}")
    if errors:
        raise SystemExit(f"{paths.vocab()}: " + "; ".join(errors))
    # Sorted so the file only changes when the vocabulary does.
    corrections = [{"heard": h, "replacement": r} for _, (h, r) in sorted(safe.items())]
    return {"version": 1, "corrections": corrections}


def render(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main(argv):
    parser = argparse.ArgumentParser(description="Write Vocalinux's corrections from vocab.toml.")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file on disk is out of date, write nothing")
    args = parser.parse_args(argv)
    vocab, corrections_path = paths.vocab(), paths.corrections()
    data = build_corrections(load_terms(vocab))
    content = render(data)
    if args.check:
        current = corrections_path.read_text(encoding="utf-8") if corrections_path.exists() else ""
        if current != content:
            print(f"{corrections_path} is out of date, run {Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"{corrections_path} is up to date ({len(data['corrections'])} corrections)")
        return 0
    write_atomic(corrections_path, content)
    print(f"{corrections_path}: {len(data['corrections'])} corrections")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
