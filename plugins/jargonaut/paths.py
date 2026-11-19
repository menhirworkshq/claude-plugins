"""Where jargonaut keeps its files (XDG base directories, stdlib only).

The code lives in the plugin folder; everything personal lives outside it:

  config  $JARGONAUT_CONFIG_DIR or $XDG_CONFIG_HOME/jargonaut (~/.config/jargonaut)
          vocab.toml, prompt.toml (personal prompt parts), the `live` flag file
  data    $JARGONAUT_DATA_DIR or $XDG_DATA_HOME/jargonaut (~/.local/share/jargonaut)
          calibration/ rounds, eval-checks.toml, results.md
  state   $JARGONAUT_STATE_DIR or $XDG_STATE_HOME/jargonaut (~/.local/state/jargonaut)
          the hook logs (haiku-YYYY-MM-DD.jsonl) and the generated prompt.md
  socket  $JARGONAUT_SOCKET or $XDG_RUNTIME_DIR/jargonaut.sock

Kept light on purpose: the Vocalinux hook imports it on every segment.
"""

import os
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = PLUGIN_DIR / "examples"


def _env_path(name):
    value = os.environ.get(name)
    return Path(value) if value else None


def _xdg(var, default):
    base = os.environ.get(var)
    return Path(base) if base else Path.home() / default


def config_dir():
    return _env_path("JARGONAUT_CONFIG_DIR") or _xdg("XDG_CONFIG_HOME", ".config") / "jargonaut"


def data_dir():
    return _env_path("JARGONAUT_DATA_DIR") or _xdg("XDG_DATA_HOME", ".local/share") / "jargonaut"


def state_dir():
    return _env_path("JARGONAUT_STATE_DIR") or _xdg("XDG_STATE_HOME", ".local/state") / "jargonaut"


def vocab():
    return _env_path("JARGONAUT_VOCAB") or config_dir() / "vocab.toml"


def prompt_parts():
    return config_dir() / "prompt.toml"


def live_flag():
    return _env_path("JARGONAUT_LIVE_FLAG") or config_dir() / "live"


def calibration_dir():
    return data_dir() / "calibration"


def eval_checks():
    return data_dir() / "eval-checks.toml"


def prompt():
    return state_dir() / "prompt.md"


def socket_path():
    explicit = os.environ.get("JARGONAUT_SOCKET")
    if explicit:
        return explicit
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "jargonaut.sock")


def corrections():
    """Vocalinux's deterministic corrections file, written by generate.py."""
    return (_env_path("JARGONAUT_CORRECTIONS")
            or _xdg("XDG_CONFIG_HOME", ".config") / "vocalinux" / "custom-dictionary-corrections.json")


def vocalinux_python():
    """Python of the Vocalinux venv, used by eval.py to apply its corrections."""
    return (_env_path("JARGONAUT_VOCALINUX_PYTHON")
            or _xdg("XDG_DATA_HOME", ".local/share") / "vocalinux" / "venv" / "bin" / "python")
