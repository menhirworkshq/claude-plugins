"""Tests of seed.py on invented sources: only term-like tokens come out, never secrets or lines."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SEED = Path(__file__).resolve().parents[2] / "seed.py"


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def seed(self, *args):
        env = dict(os.environ, HOME=str(self.home))
        out = subprocess.run([sys.executable, str(SEED), "--min", "1", *args], env=env,
                             capture_output=True, text=True, check=True).stdout
        return {line.split("\t")[1] for line in out.splitlines() if not line.startswith("#")}

    def test_code_terms(self):
        proj = self.home / "dev" / "kube-widget"
        (proj / ".git").mkdir(parents=True)
        (proj / "k8s").mkdir()
        (proj / "go.mod").write_text("module example.com/acme/widgetd\n")
        (proj / "Taskfile.yaml").write_text("version: '3'\n\ntasks:\n  lint:\n    cmds: []\n")
        (proj / "k8s" / "a.yaml").write_text("kind: WidgetPolicy\n")
        (proj / ".env").write_text("kind: LeakedFromEnv\n")
        (proj / "secrets.yaml").write_text("kind: LeakedFromSecrets\n")
        terms = self.seed("--code", str(self.home / "dev"))
        self.assertEqual(terms, {"kube-widget", "widgetd", "lint", "WidgetPolicy"})

    def test_history_keeps_commands_only(self):
        (self.home / ".bash_history").write_text("kubectl get pods\nsudo podman ps\nexport TOKEN=ghp_xyz\n")
        (self.home / ".zsh_history").write_text(": 1700000000:0;k9s --context prod\n")
        self.assertEqual(self.seed("--history"), {"kubectl", "podman", "export", "k9s"})

    def test_prompts_drop_secrets_and_plain_words(self):
        session = self.home / ".claude" / "projects" / "p"
        session.mkdir(parents=True)
        text = ("relance kube-image-keeper et ImageMirror avec la clé ghp_AbC123dEf456GhI789jKl0 "
                "et AKIAIOSFODNN7EXAMPLE puis aGVsbG8gd29ybGQgdGhpcyBpcyBsb25n <system-reminder>NotSaid</system-reminder>")
        records = [{"type": "user", "message": {"content": text}},
                   {"type": "assistant", "message": {"content": "AssistantTerm"}}]
        (session / "s.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
        self.assertEqual(self.seed("--prompts"), {"kube-image-keeper", "ImageMirror"})

    def test_needs_a_source(self):
        result = subprocess.run([sys.executable, str(SEED)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
