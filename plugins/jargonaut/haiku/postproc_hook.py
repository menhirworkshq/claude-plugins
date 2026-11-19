#!/usr/bin/env python3
"""Vocalinux post-processing hook (post_processing.script_path).

Reads a segment on stdin and writes the text to type on stdout. Fail-safe by
design: it always prints something non-empty (empty stdout would drop the
segment) and always exits 0.

Modes, chosen by a flag file so no Vocalinux setting has to change:
  shadow (default): print the input unchanged right away, then ask the daemon
          in a detached child and only log what Haiku would have typed.
  live (the flag file ~/.config/jargonaut/live exists): ask the daemon
          within BUDGET_S and print its correction; print the input unchanged
          on any error, timeout or guard trip.

Every segment is logged as one JSON line in ~/.local/state/jargonaut/
(haiku-YYYY-MM-DD.jsonl, one file per day, directory 700, files 600, files
older than 30 days are deleted).

Environment overrides (for tests): JARGONAUT_SOCKET, JARGONAUT_STATE_DIR,
JARGONAUT_LIVE_FLAG, JARGONAUT_HOOK_BUDGET_S (see paths.py).
"""

import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
try:  # never fail before printing: without paths, the hook falls back to shadow and raw
    sys.path.insert(0, os.path.dirname(HERE))
    import paths
except Exception:
    paths = None

BUDGET_S = float(os.environ.get("JARGONAUT_HOOK_BUDGET_S", 4.0))
LOG_RETENTION_DAYS = 30


def emit(text):
    """Write the output and close stdout; never raises."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except Exception:
        pass


def ask_daemon(raw, budget_s):
    """Return (response dict or None, error or None)."""
    import json
    import socket
    import time

    deadline = time.monotonic() + budget_s
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(min(0.3, budget_s))
        sock.connect(paths.socket_path())
        # Leave the daemon a margin to answer before our own deadline.
        budget_ms = max(0, int((deadline - time.monotonic() - 0.15) * 1000))
        sock.settimeout(max(0.01, deadline - time.monotonic()))
        sock.sendall((json.dumps({"text": raw, "budget_ms": budget_ms}, ensure_ascii=False) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "timeout"
            sock.settimeout(remaining)
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        if not data:
            return None, "empty response"
        resp = json.loads(data)
        if not isinstance(resp, dict):
            return None, "bad response"
        if "error" in resp:
            return None, f"daemon error: {resp['error']}"
        return resp, None
    except socket.timeout:
        return None, "timeout"
    except (FileNotFoundError, ConnectionRefusedError):
        return None, "daemon down"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        sock.close()


def recheck(raw, final):
    """Defense in depth: re-apply the output guards to what the daemon sent."""
    if not isinstance(final, str) or not final.strip():
        return raw, "empty"
    if final == raw:
        return raw, None
    sys.path.insert(0, HERE)
    from corrector import guard
    return guard(raw, final)


def write_log(entry):
    import datetime
    import glob
    import json
    import time

    directory = str(paths.state_dir())
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, f"haiku-{datetime.date.today().isoformat()}.jsonl")
    new_file = not os.path.exists(path)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if new_file:  # once a day: drop logs past the retention
        cutoff = time.time() - LOG_RETENTION_DAYS * 86400
        for old in glob.glob(os.path.join(directory, "haiku-*.jsonl")):
            try:
                if os.path.getmtime(old) < cutoff:
                    os.unlink(old)
            except OSError:
                pass


def process(raw, mode, start):
    """Ask the daemon, log, and return the text the live mode should type."""
    import datetime
    import time

    core = raw.strip()
    lead, trail = raw[: len(raw) - len(raw.lstrip())], raw[len(raw.rstrip()):]
    resp, err = ask_daemon(core, max(0.05, BUDGET_S - (time.monotonic() - start))) if core else (None, "blank input")
    corrected, decision = "", err
    final = core
    if resp is not None:
        corrected = resp.get("corrected") or ""
        try:
            final, decision = recheck(core, resp.get("final"))
        except Exception as e:
            final, decision = core, f"recheck failed: {e!r}"
        decision = resp.get("guard") or decision
    entry = {
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "mode": mode,
        "raw": core,
        "corrected": corrected,
        "final": final,
        "changed": final != core,
        "guard": decision,
        "latency_ms": round((time.monotonic() - start) * 1000),
    }
    if resp is not None:
        for key in ("haiku_ms", "cost", "turn", "new_session"):
            entry[key] = resp.get(key)
    try:
        write_log(entry)
    except Exception:
        pass
    return lead + final + trail if final.strip() else raw


def detach():
    """Fork a child that outlives us, with no tie to Vocalinux's pipes."""
    if os.fork() > 0:
        return False
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    return True


def main():
    import time

    start = time.monotonic()
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass
    if not raw.strip():
        emit(raw)
        return
    try:
        live = os.path.exists(paths.live_flag())
    except Exception:
        live = False
    if not live:
        emit(raw)
        try:
            sys.stdout.close()
        except Exception:
            pass
        try:
            if detach():
                try:
                    process(raw, "shadow", start)
                finally:
                    os._exit(0)
        except Exception:
            pass
        return
    out = raw
    try:
        out = process(raw, "live", start)
    except Exception:
        out = raw
    emit(out if out.strip() else raw)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
