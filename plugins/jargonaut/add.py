#!/usr/bin/env python3
"""Add heard forms to vocab.toml without reformatting it.

Usage: add.py [--ambiguous] [--hint TEXT] TERM HEARD [HEARD...]

The forms go to the entry of TERM with the same ambiguity; when there is none,
a new entry is appended under the calibration section at the end of the file.
vocab.toml is read from the config dir (see paths.py).
"""

import argparse
import json
import re
import sys
import tomllib

import paths

SECTION = "# Added during calibration"


def toml_str(value):
    # JSON strings are valid TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def find_entry(lines, term, ambiguous):
    """Return (start, end) line indexes of the matching [[term]] block, or None."""
    starts = [i for i, line in enumerate(lines) if line.strip() == "[[term]]"]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = tomllib.loads("".join(lines[start:end]))["term"][0]
        if block["term"] == term and block.get("ambiguous", False) == ambiguous:
            return start, end
    return None


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--ambiguous", action="store_true")
    parser.add_argument("--hint")
    parser.add_argument("term")
    parser.add_argument("heard", nargs="+")
    args = parser.parse_args(argv)

    vocab = paths.vocab()
    lines = vocab.read_text(encoding="utf-8").splitlines(keepends=True)
    found = find_entry(lines, args.term, args.ambiguous)
    if found:
        start, end = found
        entry = tomllib.loads("".join(lines[start:end]))["term"][0]
        known = {h.casefold() for h in entry.get("heard", [])}
        heard = entry.get("heard", []) + [h for h in args.heard if h.casefold() not in known]
        new_line = f"heard = [{', '.join(toml_str(h) for h in heard)}]\n"
        index = next((i for i in range(start, end) if re.match(r"heard\s*=", lines[i])), None)
        if index is None:
            lines.insert(start + 2, new_line)
        else:
            lines[index] = new_line
    else:
        if not any(line.strip() == SECTION for line in lines):
            lines.append(f"\n{SECTION}\n")
        block = ["\n[[term]]\n", f"term = {toml_str(args.term)}\n"]
        block.append(f"heard = [{', '.join(toml_str(h) for h in args.heard)}]\n")
        if args.ambiguous:
            block.append("ambiguous = true\n")
        if args.hint:
            block.append(f"hint = {toml_str(args.hint)}\n")
        lines.extend(block)

    content = "".join(lines)
    tomllib.loads(content)
    vocab.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
