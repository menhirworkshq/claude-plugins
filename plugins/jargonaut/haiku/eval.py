#!/usr/bin/env python3
"""Offline evaluation of the jargonaut Haiku corrector.

Feeds the calibration transcripts (after Vocalinux's deterministic corrections)
and a few adversarial segments to Haiku through the logged-in `claude` CLI,
one sentence at a time, in order, as the live daemon would, then scores the
outputs and prints the metrics.

Modes:
  session  (a) one persistent claude process per burst: earlier segments are in
           the conversation; restarted after --max-turns segments (the first
           message after a restart carries <previous_segments>).
  fresh    (b) one fresh, pre-spawned claude process per segment: each message
           carries the last --context corrected segments in <previous_segments>.

Inputs, all in the data dir (see paths.py): calibration/roundN.raw.txt (or
roundN.live.txt) and eval-checks.toml, which holds the expected checks per
sentence and the adversarial bursts. The prompt is built from vocab.toml and
prompt.toml as the daemon does.

Usage: eval.py [--modes session,fresh] [--jobs N] [--max-turns N] [--context N]
               [--only PREFIX] [--repeat N] [--json FILE] [--dry-run]
  --dry-run  list the bursts, segments and checks, and run the guard self-test,
             without calling claude (costs nothing)
"""

import argparse
import difflib
import json
import re
import subprocess
import sys
import threading
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_prompt  # noqa: E402
import paths  # noqa: E402
from corrector import Claude, clean_output, format_message, guard, guard_selftest, similarity, words, GUARD_BLOCK, GUARD_PASS


# ---------------------------------------------------------------- test cases

def fix(bad, good):
    """A recognition error: `bad` (regex on the input) must be gone, `good` present."""
    return ("fix", bad, good)


def keep(text):
    """A trap: this exact text must survive unchanged."""
    return ("keep", text)


def opt(pattern):
    """A span where a change is harmless (gold differs only cosmetically)."""
    return ("opt", pattern)


def whole(segment):
    return [keep(segment)]


def parse_check(check, where):
    if "fix" in check:
        return fix(check["fix"], check["want"])
    if "opt" in check:
        return opt(check["opt"])
    if "keep" in check:
        return keep(check["keep"])
    raise SystemExit(f"{where}: unknown check {check!r}")


def load_checks(path):
    """Read eval-checks.toml: (round checks, adversarial bursts, held-out names).

    round checks: {n: [checks of each sentence of roundN, in order]}
    adversarial:  {burst: [(segment, checks or None for whole, is_prompt)]}
    """
    if not path.exists():
        raise SystemExit(f"{path} is missing: see the README of the plugin for its format")
    with path.open("rb") as f:
        data = tomllib.load(f)
    rounds = {}
    for r in data.get("round", []):
        rounds[r["n"]] = [[parse_check(c, f"round{r['n']}") for c in sentence] for sentence in r["sentences"]]
    adversarial = {}
    for burst in data.get("adversarial", []):
        items = []
        for seg in burst["segment"]:
            checks = None if seg.get("whole") else [parse_check(c, burst["name"]) for c in seg["checks"]]
            items.append((seg["text"], checks, seg.get("prompt", False)))
        adversarial[burst["name"]] = items
    return dict(sorted(rounds.items())), adversarial, set(data.get("held_out", []))


def load_corrected_rounds(round_numbers):
    """Apply Vocalinux's own deterministic corrections to the raw transcripts."""
    code = (
        "import json, sys\n"
        "from vocalinux.custom_dictionary import normalize_corrections, apply_corrections\n"
        "entries = normalize_corrections(json.load(open(sys.argv[1]))['corrections'])\n"
        "texts = json.load(sys.stdin)\n"
        "print(json.dumps([apply_corrections(t, entries) for t in texts]))\n"
    )
    def source(i):
        raw = paths.calibration_dir() / f"round{i}.raw.txt"
        return raw if raw.exists() else paths.calibration_dir() / f"round{i}.live.txt"
    raws = [source(i).read_text(encoding="utf-8") for i in round_numbers]
    out = subprocess.run([str(paths.vocalinux_python()), "-I", "-c", code, str(paths.corrections())],
                         input=json.dumps(raws), capture_output=True, text=True, check=True)
    return dict(zip(round_numbers, json.loads(out.stdout)))


def split_segments(text):
    """Split a transcript into sentence-like segments (the daemon splits on silence)."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def build_bursts(round_checks, adversarial):
    bursts = []
    for n, text in load_corrected_rounds(list(round_checks)).items():
        segments = split_segments(text)
        checks = round_checks[n]
        if len(segments) != len(checks):
            raise SystemExit(f"round{n}: {len(segments)} segments but {len(checks)} check lists")
        bursts.append((f"round{n}", [(s, c, False) for s, c in zip(segments, checks)]))
    for name, items in adversarial.items():
        bursts.append((name, [(s, c if c is not None else whole(s), p) for s, c, p in items]))
    return bursts


# ---------------------------------------------------------------- claude CLI

class Spare:
    """Keeps one pre-spawned process ready so spawn time stays off the hot path."""

    def __init__(self, system_prompt):
        self.system_prompt = system_prompt
        self.next = Claude(system_prompt)

    def take(self):
        current, self.next = self.next, Claude(self.system_prompt)
        return current

    def close(self):
        self.next.close()


# ---------------------------------------------------------------- scoring

def tokens(text):
    return [(m.group().casefold(), m.start(), m.end()) for m in re.finditer(r"\w+(?:['’]\w+)*", text)]


def score(raw, out, checks):
    fixes_ok, fixes_failed, keeps_failed = [], [], []
    protected = []
    for check in checks:
        if check[0] == "fix":
            _, bad, good = check
            protected += [m.span() for m in re.finditer(bad, raw)]
            ok = re.search(bad, out) is None and re.search(good, out) is not None
            (fixes_ok if ok else fixes_failed).append(bad)
        elif check[0] == "opt":
            protected += [m.span() for m in re.finditer(check[1], raw)]
        elif check[0] == "keep" and check[1] not in out:
            keeps_failed.append(check[1])
    rt, ot = tokens(raw), tokens(out)
    prot = [any(s < e2 and s2 < e for s2, e2 in protected) for _, s, e in rt]
    over = []
    sm = difflib.SequenceMatcher(None, [t for t, _, _ in rt], [t for t, _, _ in ot], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        span = range(max(0, i1 - 1), min(len(rt), i2 + 1)) if op == "insert" else range(i1, i2)
        if any(prot[i] for i in span):
            continue
        over.append((" ".join(t for t, _, _ in rt[i1:i2]), " ".join(t for t, _, _ in ot[j1:j2])))
    return fixes_ok, fixes_failed, keeps_failed, over


def answered(raw, out):
    """Heuristic: the output is an answer or a rewrite rather than a correction."""
    rw, ow = words(raw), words(out)
    return len(ow) > 1.5 * len(rw) + 2 or similarity(raw, out) < 0.5


# ---------------------------------------------------------------- runner

def run_burst(mode, name, items, system_prompt, args):
    results = []
    history = []  # corrected segments of this burst
    spare = Spare(system_prompt)
    session, turns = None, 0
    try:
        for idx, (raw, checks, is_prompt) in enumerate(items):
            previous = history[-args.context:] if args.context else []
            if mode == "session":
                if session is None or turns >= args.max_turns:
                    if session:
                        session.close()
                    session, turns = spare.take(), 0
                    msg = format_message(raw, previous)  # empty at the burst start
                else:
                    msg = format_message(raw, [])
                turns += 1
                proc = session
            else:
                proc = spare.take()
                msg = format_message(raw, previous)
            try:
                event = proc.send(msg)
                out, err = clean_output(event.get("result")), None
            except Exception as e:  # timeout or crash: the daemon falls back to raw
                event, out, err = {}, "", repr(e)
            if mode == "fresh":
                threading.Thread(target=proc.close, daemon=True).start()
            final, reason = guard(raw, out)
            history.append(final)
            usage = event.get("usage", {})
            results.append({
                "mode": mode, "burst": name, "index": idx, "raw": raw, "message": msg,
                "output": out, "result_text": event.get("result"), "final": final, "guard": reason, "error": err,
                "is_prompt": is_prompt, "checks": checks,
                "wall_ms": event.get("wall_ms"), "api_ms": event.get("turn_api_ms"),
                "cost": event.get("turn_cost", 0.0),
                "input_tokens": usage.get("input_tokens"),
                "cache_read": usage.get("cache_read_input_tokens"),
                "cache_write": usage.get("cache_creation_input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            })
            print(f"  [{mode}] {name}#{idx} {event.get('wall_ms', 0):.0f}ms", file=sys.stderr)
    finally:
        if session:
            session.close()
        spare.close()
    return results


def pct(values, p):
    values = sorted(v for v in values if v is not None)
    if not values:
        return float("nan")
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def report(mode, results, label=""):
    fixes_ok = fixes_total = keeps_total = keeps_failed = 0
    overs, failures, answered_list, guard_trips, blocked, chatter = [], [], [], [], [], []
    good_sims, good_ratios = [], []
    for r in results:
        ok, failed, kfailed, over = score(r["raw"], r["output"], r["checks"])
        fixes_ok += len(ok)
        fixes_total += len(ok) + len(failed)
        keeps_total += sum(1 for c in r["checks"] if c[0] == "keep")
        keeps_failed += len(kfailed)
        if failed or kfailed or over:
            failures.append((r, failed, kfailed, over))
        overs += over
        if r["output"] and answered(r["raw"], r["output"]):
            answered_list.append(r)
        extra = re.sub(r"<out>.*?</out>", "", r.get("result_text") or "", flags=re.S).strip()
        if extra:
            chatter.append((r, extra))
        if r["guard"]:
            guard_trips.append(r)
            if ok and not failed and not over:
                blocked.append(r)
        if ok and r["output"]:
            good_sims.append(similarity(r["raw"], r["output"]))
            good_ratios.append(len(r["output"]) / len(r["raw"]))
    n = len(results)
    cost = sum(r["cost"] or 0 for r in results)
    print(f"\n=== mode {mode}{' ' + label if label else ''}: {n} segments")
    print(f"vocabulary/evident errors fixed: {fixes_ok}/{fixes_total}")
    print(f"over-corrections (unneeded changes): {len(overs)} in {sum(1 for f in failures if f[3])} segments")
    print(f"traps kept: {keeps_total - keeps_failed}/{keeps_total}")
    print(f"answered/rewritten outputs: {len(answered_list)}; text outside <out> (discarded): {len(chatter)}")
    print(f"latency wall p50/p95: {pct([r['wall_ms'] for r in results], 50):.0f}/{pct([r['wall_ms'] for r in results], 95):.0f} ms; api p50/p95: {pct([r['api_ms'] for r in results], 50):.0f}/{pct([r['api_ms'] for r in results], 95):.0f} ms")
    print(f"cost: ${cost:.4f} total, ${cost / max(1, n):.5f}/segment; cache_read p50 {pct([r['cache_read'] for r in results], 50):.0f} tokens")
    print(f"guard trips: {len(guard_trips)} (blocking a correct output: {len(blocked)})")
    if good_sims:
        print(f"on correct fixes: min similarity {min(good_sims):.2f}, length ratio {min(good_ratios):.2f}..{max(good_ratios):.2f}")
    for r, failed, kfailed, over in failures:
        print(f"\n- {r['burst']}#{r['index']}: missed={failed} traps={kfailed} over={over}")
        print(f"  raw: {r['raw']}\n  out: {r['output']}")
    for r in guard_trips:
        print(f"\n- guard {r['guard']} on {r['burst']}#{r['index']}: {r['output']!r}")
    for r, extra in chatter:
        print(f"\n- outside <out> on {r['burst']}#{r['index']}: {extra[:300]!r}")
    for r in answered_list:
        print(f"\n- ANSWERED {r['burst']}#{r['index']}: {r['output']!r}")
    return {"mode": mode, "segments": n, "fixed": fixes_ok, "fixes": fixes_total,
            "over": len(overs), "traps_kept": keeps_total - keeps_failed, "traps": keeps_total,
            "answered": len(answered_list), "chatter": len(chatter), "cost": cost,
            "wall_p50": pct([r['wall_ms'] for r in results], 50), "wall_p95": pct([r['wall_ms'] for r in results], 95)}


def dry_run(bursts, held_out):
    """Print what a run would feed to Haiku, without calling it."""
    total = {"segments": 0, "fix": 0, "opt": 0, "keep": 0}
    for name, items in bursts:
        counts = {kind: sum(1 for _, checks, _ in items for c in checks if c[0] == kind) for kind in ("fix", "opt", "keep")}
        prompts = sum(1 for _, _, is_prompt in items if is_prompt)
        flag = " (held out)" if name in held_out else ""
        print(f"{name}{flag}: {len(items)} segments, {counts['fix']} fix, {counts['opt']} opt, {counts['keep']} keep, {prompts} prompts")
        total["segments"] += len(items)
        for kind in ("fix", "opt", "keep"):
            total[kind] += counts[kind]
    print(f"total: {len(bursts)} bursts, {total['segments']} segments, {total['fix']} fix, {total['opt']} opt, {total['keep']} keep")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", default="session,fresh")
    parser.add_argument("--jobs", type=int, default=1, help="bursts run in parallel (latency is measured best with 1)")
    parser.add_argument("--max-turns", type=int, default=50)
    parser.add_argument("--context", type=int, default=2)
    parser.add_argument("--only", default="", help="only bursts whose name starts with this")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--json", help="write all results to this file")
    parser.add_argument("--dry-run", action="store_true", help="list bursts and checks, do not call claude")
    args = parser.parse_args()

    errors = guard_selftest()
    print(f"guard self-test: {len(GUARD_PASS)} legit, {len(GUARD_BLOCK)} drifts, {len(errors)} errors")
    for e in errors:
        print(f"  {e}")
    round_checks, adversarial, held_out = load_checks(paths.eval_checks())
    bursts = [b for b in build_bursts(round_checks, adversarial) if b[0].startswith(args.only)]
    if args.dry_run:
        dry_run(bursts, held_out)
        return
    bursts *= args.repeat
    system_prompt = build_prompt.build()
    all_results, summaries = [], []
    for mode in args.modes.split(","):
        jobs = [(mode, name, items) for name, items in bursts]
        results = []
        lock = threading.Lock()

        def worker():
            while True:
                with lock:
                    if not jobs:
                        return
                    job = jobs.pop(0)
                res = run_burst(*job, system_prompt, args)
                with lock:
                    results.extend(res)

        threads = [threading.Thread(target=worker) for _ in range(max(1, args.jobs))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        results.sort(key=lambda r: (r["burst"], r["index"]))
        tuned = [r for r in results if r["burst"] not in held_out]
        held = [r for r in results if r["burst"] in held_out]
        if held:
            summaries.append(dict(report(mode, tuned, "tuned set"), set="tuned"))
            summaries.append(dict(report(mode, held, f"held-out ({', '.join(sorted(held_out))})"), set="held-out"))
        else:
            summaries.append(report(mode, results))
        all_results += results
    print("\n=== summary")
    for s in summaries:
        print(json.dumps(s))
    print(f"total spend: ${sum(s['cost'] for s in summaries):.4f}")
    if args.json:
        Path(args.json).write_text(json.dumps(all_results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
