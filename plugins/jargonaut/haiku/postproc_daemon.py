#!/usr/bin/env python3
"""jargonaut daemon: corrects dictated segments with Haiku.

Holds a persistent `claude -p` stream-json session (one session per dictation
burst, see the README) and answers requests from postproc_hook.py on a Unix
socket, $XDG_RUNTIME_DIR/jargonaut.sock (mode 600).

At startup it builds the system prompt from vocab.toml and prompt.toml (see
build_prompt.py) and writes it to prompt.md in the state dir, so a restart is
enough to pick up a vocabulary change.

Protocol: one JSON line per connection each way.
  request:  {"text": "...", "budget_ms": 3500}
  response: {"final": "...", "corrected": "...", "guard": null | "reason",
             "haiku_ms": 1600, "cost": 0.0002, "turn": 3, "new_session": false}
`final` is what the live mode would type: the correction, or the raw text when
a guard, a failure or the circuit breaker stepped in. `corrected` is the
parsed model output ("" when there is none).

Session policy:
  - a new session after SESSION_IDLE_S without a segment, or after MAX_TURNS;
  - a spare process is always pre-started, so a new session does not pay the
    claude startup (about 2 s) on the hot path;
  - after a timeout or a crash the session is dropped (it would be out of sync);
  - circuit breaker: after BREAKER_FAILURES consecutive failures, Haiku is
    skipped for BREAKER_COOLDOWN_S.

Usage: postproc_daemon.py [--socket PATH]

Environment: JARGONAUT_SOCKET, JARGONAUT_SESSION_IDLE_S, JARGONAUT_MAX_TURNS,
JARGONAUT_BREAKER_COOLDOWN_S, JARGONAUT_CLAUDE_BIN, plus the directories of
paths.py.
"""

import argparse
import json
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_prompt  # noqa: E402
import paths  # noqa: E402
from corrector import Claude, ClaudeError, clean_output, format_message, guard  # noqa: E402

SESSION_IDLE_S = float(os.environ.get("JARGONAUT_SESSION_IDLE_S", 20))
MAX_TURNS = int(os.environ.get("JARGONAUT_MAX_TURNS", 50))
CONTEXT_SEGMENTS = 2  # carried as <previous_segments> into a session restarted on MAX_TURNS
BREAKER_FAILURES = 2
# Restarting a spare that cannot start (claude missing) or dies at once (logged
# out, broken update) backs off from 1 s up to this, and resets once a spare
# has stayed alive for SPARE_HEALTHY_S.
SPARE_BACKOFF_MAX_S = float(os.environ.get("JARGONAUT_SPARE_BACKOFF_MAX_S", 60))
SPARE_HEALTHY_S = 5
BREAKER_COOLDOWN_S = float(os.environ.get("JARGONAUT_BREAKER_COOLDOWN_S", 60))
DEFAULT_BUDGET_MS = 3500
MAX_REQUEST_BYTES = 64 * 1024


def log(msg):
    # Goes to the journal; never logs dictated text.
    print(f"jargonaut-daemon: {msg}", file=sys.stderr, flush=True)


class Corrector:
    def __init__(self, system_prompt):
        self.system_prompt = system_prompt
        self.lock = threading.Lock()
        self.session = None
        self.spare = None
        self.spare_lock = threading.Lock()
        self.spare_started = 0.0
        self.spare_backoff = 1.0
        self.next_prestart = 0.0
        self.last_segment = 0.0
        self.history = []  # final texts of the current burst
        self.failures = 0
        self.breaker_until = 0.0
        self._prestart()
        threading.Thread(target=self._housekeeping, daemon=True).start()

    # -------------------------------------------------- processes

    def _prestart(self):
        """Start the spare process in the background if there is none."""
        def start():
            with self.spare_lock:
                if self.spare is not None and self.spare.alive():
                    return
                self.spare_started = time.monotonic()
                try:
                    self.spare = Claude(self.system_prompt)
                except Exception as e:  # claude missing, fork failure...
                    self.spare = None
                    log(f"cannot start claude: {e!r}")
        threading.Thread(target=start, daemon=True).start()

    def _take_spare(self):
        with self.spare_lock:
            proc, self.spare = self.spare, None
        if proc is None or not proc.alive():
            if proc is not None:
                proc.close()
            proc = Claude(self.system_prompt)  # cold start, pays the startup
        self._prestart()
        return proc

    def _drop_session(self, reason):
        if self.session is not None:
            old, self.session = self.session, None
            threading.Thread(target=old.close, daemon=True).start()
            log(f"session closed ({reason})")

    def _housekeeping(self):
        """Close the session once the burst is over, keep a spare ready."""
        while True:
            time.sleep(1)
            with self.lock:
                if self.session is not None and time.monotonic() - self.last_segment > SESSION_IDLE_S:
                    self._drop_session("idle")
                    self.history = []
            now = time.monotonic()
            with self.spare_lock:
                alive = self.spare is not None and self.spare.alive()
                if alive and now - self.spare_started >= SPARE_HEALTHY_S:
                    self.spare_backoff = 1.0
            if not alive and now >= self.next_prestart:
                self.next_prestart = now + self.spare_backoff
                self.spare_backoff = min(self.spare_backoff * 2, SPARE_BACKOFF_MAX_S)
                self._prestart()

    def close(self):
        with self.lock:
            self._drop_session("shutdown")
        with self.spare_lock:
            if self.spare is not None:
                self.spare.close()
                self.spare = None

    # -------------------------------------------------- requests

    def correct(self, raw, budget_ms):
        start = time.monotonic()
        deadline = start + budget_ms / 1000
        resp = {"final": raw, "corrected": "", "guard": None, "haiku_ms": None,
                "cost": None, "turn": None, "new_session": False}
        if not raw.strip():
            resp["guard"] = "blank input"
            return resp
        if not self.lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            resp["guard"] = "busy"
            return resp
        try:
            now = time.monotonic()
            if now < self.breaker_until:
                resp["guard"] = "circuit open"
                return resp
            idle = now - self.last_segment > SESSION_IDLE_S
            self.last_segment = now
            if idle:
                self.history = []
            previous = []
            if self.session is not None and (idle or self.session.turns >= MAX_TURNS or not self.session.alive()):
                if not idle and self.session.turns >= MAX_TURNS:
                    previous = self.history[-CONTEXT_SEGMENTS:]
                self._drop_session("idle" if idle else "turn cap or dead")
            if self.session is None:
                self.session = self._take_spare()
                resp["new_session"] = True
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                resp["guard"] = "no budget"
                return resp
            try:
                event = self.session.send(format_message(raw, previous), timeout=remaining)
            except ClaudeError as e:
                self._drop_session(str(e))
                self._failure(resp, str(e))
                return resp
            resp["turn"] = self.session.turns
            resp["haiku_ms"] = round(event.get("wall_ms", 0))
            resp["cost"] = event.get("turn_cost")
            if event.get("is_error"):
                self._drop_session("error result")
                self._failure(resp, "error result")
                return resp
            out = clean_output(event.get("result"))
            final, reason = guard(raw, out)
            if not out:
                self._failure(resp, "no <out> block")
            else:
                self.failures = 0
            resp.update(corrected=out, final=final, guard=resp["guard"] or reason)
            self.history.append(final)
            return resp
        finally:
            self.lock.release()

    def _failure(self, resp, reason):
        self.failures += 1
        resp["guard"] = reason
        if self.failures >= BREAKER_FAILURES:
            self.breaker_until = time.monotonic() + BREAKER_COOLDOWN_S
            self.failures = 0
            log(f"circuit open for {BREAKER_COOLDOWN_S:.0f} s after {BREAKER_FAILURES} failures ({reason})")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(MAX_REQUEST_BYTES)
            req = json.loads(line)
            raw = req["text"]
            if not isinstance(raw, str):
                raise ValueError("text must be a string")
            budget = float(req.get("budget_ms", DEFAULT_BUDGET_MS))
            resp = self.server.corrector.correct(raw, budget)
        except Exception as e:
            log(f"bad request: {e!r}")
            resp = {"error": repr(e)}
        try:
            self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
        except OSError:
            pass  # the hook gave up waiting


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=paths.socket_path())
    args = parser.parse_args()

    prompt_path = paths.prompt()
    try:
        system_prompt = build_prompt.build()
        build_prompt.write(prompt_path, system_prompt)
    except (OSError, ValueError, KeyError) as e:  # tomllib.TOMLDecodeError is a ValueError
        raise SystemExit(f"cannot build the prompt from {paths.vocab()}: {e!r}") from e
    log(f"prompt built from {paths.vocab()}: {len(system_prompt)} chars, written to {prompt_path}")
    path = args.socket
    if os.path.exists(path):
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(path)
            raise SystemExit(f"{path}: another daemon is running")
        except OSError:
            os.unlink(path)  # stale socket
        finally:
            probe.close()
    old_umask = os.umask(0o177)
    try:
        server = Server(path, Handler)
    finally:
        os.umask(old_umask)
    os.chmod(path, 0o600)
    server.corrector = Corrector(system_prompt)

    def stop(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log(f"listening on {path}")
    try:
        server.serve_forever()
    finally:
        server.corrector.close()
        server.server_close()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        log("stopped")


if __name__ == "__main__":
    main()
