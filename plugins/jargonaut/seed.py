#!/usr/bin/env python3
"""Collect candidate vocabulary terms, printing only tokens and counts.

The install skill runs this instead of reading the sources itself, so the raw
lines (which may hold pasted credentials) never reach the model context: only
term-like tokens, seen at least --min times, come out, one per line as
`count<TAB>token`, grouped by source. Tokens that look like secrets (long
random strings, known key prefixes) are dropped too.

Each source is opt-in; the skill asks the user before passing each one.

Usage: seed.py [--code DIR]... [--history] [--prompts] [--min N] [--limit N]
  --code DIR   repository names, go.mod modules, package.json names, Taskfile
               and Makefile targets, Kubernetes kinds under DIR
  --history    the first word (the command) of each ~/.bash_history and
               ~/.zsh_history line
  --prompts    term-like tokens of the user messages in
               ~/.claude/projects/*/*.jsonl
"""

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", "dist", "build", ".cache", "target"}
# Never opened, whatever the source.
SECRET_FILE = re.compile(r"(^\.env|secret|credential|token|\.pem$|\.key$|\.p12$|vault|password)", re.I)
SECRET_TOKEN = re.compile(r"^(sk-|ghp_|gho_|github_pat_|glpat-|xox[abp]-|AKIA|AIza|eyJ)|[=@/\\]")
# CamelCase, kebab-case, dotted names, words with digits, all-caps acronyms.
TERM_LIKE = re.compile(
    r"^(?:[A-Za-z]+[a-z][A-Z][A-Za-z0-9]*"     # camelCase / PascalCase
    r"|[A-Za-z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)+"  # kebab-case, dotted
    r"|[A-Za-z]+[0-9][A-Za-z0-9]*"           # with digits
    r"|[A-Z]{2,6})$")                           # acronym
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9.\-_]*[A-Za-z0-9]")
MAX_FILE_BYTES = 512 * 1024


def entropy(s):
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def plausible(token):
    """A term a person would say, not a hash, key or path."""
    if len(token) < 2 or len(token) > 40 or SECRET_TOKEN.search(token):
        return False
    if len(token) >= 16 and entropy(token) > 3.5:
        return False
    return True


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") and not SECRET_FILE.search(d)]
        for name in filenames:
            if not SECRET_FILE.search(name):
                yield Path(dirpath) / name


def read(path):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def from_code(root):
    found = Counter()
    for gitdir in root.glob("**/.git"):
        if not any(part in SKIP_DIRS for part in gitdir.parent.parts):
            found[gitdir.parent.name] += 3  # a repository name is a term on its own
    for path in walk(root):
        name = path.name
        if name == "go.mod":
            m = re.search(r"^module\s+(\S+)", read(path), re.M)
            if m:
                found.update([m.group(1).rsplit("/", 1)[-1]])
        elif name == "package.json":
            try:
                pkg = json.loads(read(path) or "{}").get("name")
            except ValueError:
                pkg = None
            if isinstance(pkg, str):
                found.update([pkg.rsplit("/", 1)[-1]])
        elif re.fullmatch(r"Taskfile(\.dist)?\.ya?ml", name):
            text = read(path)
            block = text.split("\ntasks:", 1)[-1] if "\ntasks:" in text else ""
            found.update(re.findall(r"^  ([A-Za-z][\w:-]*):\s*$", block, re.M))
        elif name in ("Makefile", "makefile", "GNUmakefile"):
            found.update(re.findall(r"^([A-Za-z][\w-]*):(?!=)", read(path), re.M))
        elif path.suffix in (".yaml", ".yml"):
            found.update(re.findall(r"^kind:\s*([A-Z][A-Za-z0-9]+)\s*$", read(path), re.M))
    return found


def from_history():
    found = Counter()
    for name in (".bash_history", ".zsh_history"):
        for line in read(Path.home() / name).splitlines():
            line = re.sub(r"^: \d+:\d+;", "", line).strip()  # zsh extended history
            words = line.split()
            if not words:
                continue
            word = words[0]
            if word in ("sudo", "env", "time", "exec", "nohup") and len(words) > 1:
                word = words[1]
            word = word.rsplit("/", 1)[-1]
            if re.fullmatch(r"[A-Za-z][\w.+-]*", word) and "=" not in word:
                found[word] += 1
    return found


def user_texts(record):
    if record.get("type") != "user":
        return
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                yield part.get("text", "")


def from_prompts():
    found = Counter()
    for path in (Path.home() / ".claude" / "projects").glob("*/*.jsonl"):
        try:
            lines = path.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with lines:
            for line in lines:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                for text in user_texts(record):
                    # Tool output and system reminders are not what the user said.
                    text = re.sub(r"<([a-z-]+)>.*?</\1>", " ", text, flags=re.S)
                    found.update(t for t in TOKEN.findall(text) if TERM_LIKE.match(t))
    return found


def main(argv):
    parser = argparse.ArgumentParser(description="Print candidate vocabulary terms with counts, never raw lines.")
    parser.add_argument("--code", type=Path, action="append", default=[], metavar="DIR")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--prompts", action="store_true")
    parser.add_argument("--min", type=int, default=3, help="minimum count (default 3)")
    parser.add_argument("--limit", type=int, default=150, help="maximum terms per source (default 150)")
    args = parser.parse_args(argv)
    sources = [(f"code {d}", lambda d=d: from_code(d.expanduser())) for d in args.code]
    if args.history:
        sources.append(("shell history (commands)", from_history))
    if args.prompts:
        sources.append(("Claude Code prompts", from_prompts))
    if not sources:
        parser.error("give at least 1 source: --code DIR, --history or --prompts")
    for title, collect in sources:
        counts = collect()
        kept = [(n, t) for t, n in counts.items() if n >= args.min and plausible(t)]
        kept.sort(key=lambda x: (-x[0], x[1].casefold()))
        print(f"# {title}: {len(kept)} terms")
        for n, t in kept[:args.limit]:
            print(f"{n}\t{t}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
