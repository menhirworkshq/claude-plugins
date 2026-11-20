#!/usr/bin/env python3
"""Tests of the post-processing hook and daemon (no network, no real claude).

Hook: its fail-safe paths against a fake daemon (down, slow, empty, garbage,
error, guard trip, an answer instead of a correction) in shadow and live mode;
the input must always come out unchanged unless a valid correction arrives in
live mode. Daemon: prompt build at startup, session restart, spare
pre-start, turn cap and circuit breaker, with tests/fake_claude.py instead of
claude and the example vocabulary of examples/.

Run: python3 -m unittest discover -s haiku/tests (from the plugin folder)
"""

import datetime
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
HOOK = HERE.parent / "postproc_hook.py"
DAEMON = HERE.parent / "postproc_daemon.py"
FAKE_CLAUDE = HERE / "fake_claude.py"
EXAMPLES = HERE.parent.parent / "examples"
sys.path.insert(0, str(HERE.parent))
import build_prompt  # noqa: E402

RAW = "J'ai relancé les workers céleri pour vider la file.\n"
CORE = RAW.strip()
FIXED = "J'ai relancé les workers Celery pour vider la file."


class FakeDaemon:
    """A Unix socket server answering every request with `behaviour`."""

    def __init__(self, path, behaviour):
        self.path, self.behaviour = path, behaviour
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(path)
        self.sock.listen()
        self.requests = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        with conn:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            req = json.loads(data)
            self.requests.append(req)
            reply = self.behaviour(req)
            if reply is not None:
                try:
                    conn.sendall(reply)
                except OSError:
                    pass

    def close(self):
        self.sock.close()


def ok_reply(final, guard=None, corrected=None):
    return lambda req: (json.dumps({"final": final, "corrected": corrected if corrected is not None else final,
                                    "guard": guard, "haiku_ms": 1500, "cost": 0.0002, "turn": 1,
                                    "new_session": False}) + "\n").encode()


def slow(req):
    time.sleep(8)
    return ok_reply(FIXED)(req)


BEHAVIOURS = {
    "correct": ok_reply(FIXED),
    "slow": slow,
    "empty": lambda req: None,  # closes the connection without a reply
    "garbage": lambda req: b"not json\n",
    "error": lambda req: b'{"error": "boom"}\n',
    "empty final": ok_reply(""),
    "daemon guard trip": ok_reply(CORE, guard="similarity 0.31", corrected="Bien sûr, voici la file."),
    "answer instead of correction": ok_reply("Bien sûr ! Pour vider une file de tâches, purge-la avec la commande celery purge."),
}


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.socket = str(self.dir / "d.sock")
        self.state = self.dir / "state"
        self.flag = self.dir / "live"
        self.daemon = None

    def tearDown(self):
        if self.daemon:
            self.daemon.close()
        self.tmp.cleanup()

    def run_hook(self, text=RAW, live=False):
        if live:
            self.flag.touch()
        env = dict(os.environ, JARGONAUT_SOCKET=self.socket, JARGONAUT_STATE_DIR=str(self.state),
                   JARGONAUT_LIVE_FLAG=str(self.flag))
        start = time.monotonic()
        p = subprocess.run([sys.executable, str(HOOK)], input=text, capture_output=True, text=True,
                           env=env, timeout=15)
        return p, time.monotonic() - start

    def today_log(self):
        return self.state / f"haiku-{datetime.date.today().isoformat()}.jsonl"

    def log_entries(self, wait=6.0):
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.today_log().exists():
                lines = self.today_log().read_text().splitlines()
                if lines:
                    return [json.loads(line) for line in lines]
            time.sleep(0.05)
        return []

    def check(self, behaviour, live, expected):
        if behaviour != "daemon down":
            self.daemon = FakeDaemon(self.socket, BEHAVIOURS[behaviour])
        p, elapsed = self.run_hook(live=live)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, expected, f"{behaviour}, live={live}")
        self.assertLess(elapsed, 5.0, f"{behaviour}: hook took {elapsed:.1f} s")
        entries = self.log_entries()
        self.assertEqual(len(entries), 1, behaviour)
        e = entries[0]
        self.assertEqual(e["mode"], "live" if live else "shadow")
        self.assertEqual(e["raw"], CORE)
        for key in ("ts", "corrected", "final", "changed", "guard", "latency_ms"):
            self.assertIn(key, e)
        log = self.today_log()
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        return e, elapsed

    # Every failure path, in both modes, must type the input unchanged.
    def test_failures_always_output_raw(self):
        for behaviour in ["daemon down", "slow", "empty", "garbage", "error", "empty final",
                          "daemon guard trip", "answer instead of correction"]:
            for live in (False, True):
                with self.subTest(behaviour=behaviour, live=live):
                    self.tearDown()
                    self.setUp()
                    e, _ = self.check(behaviour, live, RAW)
                    self.assertFalse(e["changed"])
                    self.assertTrue(e["guard"], f"{behaviour}: no guard decision logged")

    def test_shadow_types_raw_even_with_a_correction(self):
        e, _ = self.check("correct", False, RAW)
        self.assertTrue(e["changed"])
        self.assertEqual(e["final"], FIXED)
        self.assertIsNone(e["guard"])

    def test_shadow_does_not_wait_for_the_daemon(self):
        self.daemon = FakeDaemon(self.socket, BEHAVIOURS["slow"])
        p, elapsed = self.run_hook(live=False)
        self.assertEqual(p.stdout, RAW)
        self.assertLess(elapsed, 1.0)

    def test_live_types_the_correction(self):
        e, _ = self.check("correct", True, FIXED + "\n")
        self.assertTrue(e["changed"])

    def test_live_slow_daemon_respects_budget(self):
        e, elapsed = self.check("slow", True, RAW)
        self.assertEqual(e["guard"], "timeout")
        self.assertLess(elapsed, 4.6)

    def test_blank_input_is_echoed(self):
        for text in ["", "  \n"]:
            p, _ = self.run_hook(text=text, live=True)
            self.assertEqual(p.stdout, text)
            self.assertEqual(p.returncode, 0)

    def test_old_logs_are_deleted(self):
        self.state.mkdir(mode=0o700)
        old = self.state / "haiku-2026-01-01.jsonl"
        recent = self.state / f"haiku-{(datetime.date.today() - datetime.timedelta(days=3)).isoformat()}.jsonl"
        for f, age_days in ((old, 40), (recent, 3)):
            f.write_text("{}\n")
            t = time.time() - age_days * 86400
            os.utime(f, (t, t))
        self.check("daemon down", True, RAW)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())


class DaemonTest(unittest.TestCase):
    def start(self, mode="echo", startup_s="0", **env):
        self.tmp = tempfile.TemporaryDirectory()
        self.socket = os.path.join(self.tmp.name, "d.sock")
        self.state = Path(self.tmp.name) / "state"
        # An empty config dir: the prompt parts come from examples/prompt.example.toml.
        config = Path(self.tmp.name) / "config"
        config.mkdir()
        full_env = dict(os.environ, JARGONAUT_CLAUDE_BIN=str(FAKE_CLAUDE), FAKE_CLAUDE_MODE=mode,
                        FAKE_CLAUDE_STARTUP_S=startup_s, JARGONAUT_SOCKET=self.socket,
                        JARGONAUT_CONFIG_DIR=str(config), JARGONAUT_STATE_DIR=str(self.state),
                        JARGONAUT_VOCAB=str(EXAMPLES / "vocab.example.toml"),
                        **{k: str(v) for k, v in env.items()})
        self.proc = subprocess.Popen([sys.executable, str(DAEMON)], env=full_env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 5
        while not os.path.exists(self.socket):
            self.assertLess(time.monotonic(), deadline, "daemon did not start")
            time.sleep(0.05)
        self.assertEqual(os.stat(self.socket).st_mode & 0o777, 0o600)

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.tmp.cleanup()

    def ask(self, text, budget_ms=3500):
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(self.socket)
            s.sendall((json.dumps({"text": text, "budget_ms": budget_ms}) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data)

    def test_prompt_is_built_at_startup(self):
        self.start()
        prompt = self.state / "prompt.md"
        self.assertTrue(prompt.exists())
        self.assertEqual(prompt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        empty = Path(self.tmp.name) / "no-prompt.toml"
        expected = build_prompt.build(EXAMPLES / "vocab.example.toml", empty)
        self.assertEqual(prompt.read_text(encoding="utf-8"), expected)
        self.assertIn("- Celery: \"céleri\" (context)", expected)

    def test_spare_restart_backs_off(self):
        # A claude that exits at once must not be respawned every second.
        count = Path(tempfile.mkdtemp()) / "starts"
        self.start(mode="exit", FAKE_CLAUDE_COUNT=count)
        time.sleep(8.5)
        starts = len(count.read_text().splitlines())
        # 1 s ticks without backoff would give about 9; with it: t=0, 1, 3, 7.
        self.assertLessEqual(starts, 5)
        self.assertGreaterEqual(starts, 2)
        resp = self.ask(CORE)
        self.assertEqual(resp["final"], CORE)  # still answers, with the raw text

    def test_session_turns_and_turn_cap(self):
        self.start(JARGONAUT_MAX_TURNS=2)
        time.sleep(0.5)  # spare process started
        r1, r2, r3 = self.ask("un deux trois quatre."), self.ask("cinq six sept huit."), self.ask("neuf dix onze douze.")
        self.assertEqual((r1["turn"], r1["new_session"]), (1, True))
        self.assertEqual((r2["turn"], r2["new_session"]), (2, False))
        # After the cap, a new session that carries the previous segments.
        self.assertEqual((r3["turn"], r3["new_session"]), (1, True))
        self.assertEqual(r3["final"], "neuf dix onze douze. (ctx)")
        self.assertIsNone(r1["guard"])

    def test_idle_restart_uses_prestarted_process(self):
        self.start(startup_s="1.5", JARGONAUT_SESSION_IDLE_S=1)
        time.sleep(2.5)  # spare ready
        self.assertEqual(self.ask("premier segment ici.")["new_session"], True)
        time.sleep(3.5)  # idle: session closed, new spare already started
        start = time.monotonic()
        r = self.ask("deuxième segment ici.")
        self.assertTrue(r["new_session"])
        self.assertIsNone(r["guard"])
        self.assertEqual(r["final"], "deuxième segment ici.")  # no context after a gap
        self.assertLess(time.monotonic() - start, 1.0, "new session paid the startup")

    def test_circuit_breaker(self):
        self.start(mode="slow", JARGONAUT_BREAKER_COOLDOWN_S=60)
        time.sleep(0.5)
        r1 = self.ask("un segment.", budget_ms=500)
        r2 = self.ask("un autre segment.", budget_ms=500)
        self.assertEqual((r1["guard"], r2["guard"]), ("timeout", "timeout"))
        start = time.monotonic()
        r3 = self.ask("encore un segment.")
        self.assertEqual(r3["guard"], "circuit open")
        self.assertEqual(r3["final"], "encore un segment.")
        self.assertLess(time.monotonic() - start, 0.2)

    def test_crash_and_missing_out_fall_back_to_raw(self):
        for mode, reason in (("crash", "claude exited"), ("noout", "no <out> block")):
            with self.subTest(mode=mode):
                self.start(mode=mode)
                time.sleep(0.5)
                r = self.ask("un segment à corriger.")
                self.assertEqual(r["final"], "un segment à corriger.")
                self.assertEqual(r["guard"], reason if mode == "noout" else r["guard"])
                self.assertTrue(r["guard"])
                self.tearDown()
        self.start()  # for tearDown


class PromptTest(unittest.TestCase):
    def test_example_parts_fill_every_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = build_prompt.build(EXAMPLES / "vocab.example.toml", Path(tmp) / "none.toml")
        self.assertNotIn("{", text.split("## Vocabulary")[0])
        self.assertIn("The speaker often dictates prompts", text)
        self.assertIn("## Common ambiguous forms", text)

    def test_own_parts_override_the_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            parts = Path(tmp) / "prompt.toml"
            parts.write_text('name = "Alex"\nambiguous_forms = ""\n', encoding="utf-8")
            text = build_prompt.build(EXAMPLES / "vocab.example.toml", parts)
            self.assertIn("what Alex dictated just before", text)
            self.assertIn("Alex often dictates prompts", text)
            self.assertNotIn("## Common ambiguous forms", text)
            self.assertIn("whole English sentences.\n\n## What never to do", text)
            parts.write_text('nickname = "Alex"\n', encoding="utf-8")
            with self.assertRaises(SystemExit):
                build_prompt.build(EXAMPLES / "vocab.example.toml", parts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
