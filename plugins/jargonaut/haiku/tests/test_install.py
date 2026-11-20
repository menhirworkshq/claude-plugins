"""Tests of install.py in temporary directories (no systemd, no network)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parents[2]
INSTALL = PLUGIN / "install.py"


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ,
                        JARGONAUT_DATA_DIR=str(self.tmp / "data"),
                        JARGONAUT_BIN_DIR=str(self.tmp / "bin"),
                        XDG_CONFIG_HOME=str(self.tmp / "config"),
                        PYTHONDONTWRITEBYTECODE="1")
        self.app = self.tmp / "data" / "app"

    def run_install(self, *args, script=INSTALL):
        return subprocess.run([sys.executable, str(script), *args], env=self.env,
                              capture_output=True, text=True)

    def test_copy_writes_runtime_launchers_and_unit(self):
        self.assertEqual(self.run_install("--check").returncode, 1)
        result = self.run_install("--no-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.app.is_symlink())
        self.assertTrue((self.app / "haiku" / "postproc_hook.py").is_file())
        self.assertFalse((self.app / "skills").exists())
        self.assertIn("fingerprint", json.loads((self.app / "VERSION").read_text()))
        unit = (self.tmp / "config" / "systemd" / "user" / "jargonaut.service").read_text()
        self.assertIn("ExecStart=%h/.local/bin/jargonaut-daemon", unit)
        hook = self.tmp / "bin" / "jargonaut-hook"
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertIn(str(self.app / "haiku" / "postproc_hook.py"), hook.read_text())
        self.assertEqual(self.run_install("--check").returncode, 0)
        self.assertEqual(self.run_install("--session-check").stdout, "")
        # Run from the installed copy, it compares the copy with itself.
        self.assertEqual(self.run_install("--check", script=self.app / "install.py").returncode, 0)
        self.assertEqual(self.run_install("--session-check", script=self.app / "install.py").stdout, "")

    def test_session_check_reports_a_stale_copy(self):
        self.run_install("--no-service")
        info = json.loads((self.app / "VERSION").read_text())
        info["fingerprint"] = "000000000000"
        (self.app / "VERSION").write_text(json.dumps(info))
        self.assertEqual(self.run_install("--check").returncode, 1)
        notice = json.loads(self.run_install("--session-check").stdout)
        self.assertIn("/jargonaut:install", notice["systemMessage"])
        self.assertEqual(notice["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_link_points_at_the_checkout_and_stays_quiet(self):
        self.run_install("--no-service")
        result = self.run_install("--link", "--no-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.app.is_symlink())
        self.assertEqual(self.app.resolve(), PLUGIN)
        self.assertEqual(self.run_install("--check").returncode, 0)
        self.assertEqual(self.run_install("--session-check").stdout, "")
        self.assertFalse((self.tmp / "data" / "app.old").exists())
        self.assertFalse((self.tmp / "data" / "app.new").exists())

    def test_session_check_is_quiet_when_not_installed(self):
        result = self.run_install("--session-check")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_refuses_to_run_from_the_installed_copy(self):
        self.run_install("--no-service")
        result = self.run_install("--no-service", script=self.app / "install.py")
        self.assertNotEqual(result.returncode, 0)

    def test_hook_launcher_passes_text_through_without_runtime(self):
        self.run_install("--no-service")
        subprocess.run(["rm", "-rf", str(self.app)], check=True)
        out = subprocess.run([str(self.tmp / "bin" / "jargonaut-hook")], input="bonjour\n",
                             capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (0, "bonjour\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
