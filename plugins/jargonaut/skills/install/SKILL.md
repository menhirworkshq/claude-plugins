---
name: install
description: Use when the user wants to set up jargonaut, the Vocalinux post-processing plugin, or says that dictation mangles technical terms and they just installed this plugin, or when the jargonaut service, its launchers or its vocabulary is missing, or after the plugin was updated.
---

# Installing jargonaut

## Overview

The user installed the plugin and only talks; you do every step. Ask a question only when the answer cannot be found on the machine. Never overwrite what the user already has: an existing vocabulary or post-processing script is kept unless they agree to replace it.

Below, `$JH` is the plugin folder the user runs jargonaut from, chosen in step 3.

## Ground rules

- Never open a file that may hold a secret: `~/.config/vocalinux/config.json` holds an API key (only `set_hook.py` touches it), and `.env`, `*.key`, `*secret*`, `*token*`, `*credential*` files are off limits.
- Seeding reads the user's own sources only to extract term candidates: never print or quote their lines (shell history and past prompts can hold pasted credentials).
- Say what you are about to change before each write outside the 3 jargonaut directories.

## Step 1: check the prerequisites

| Check | Command | If it fails |
|---|---|---|
| Vocalinux installed | `vocalinux --version` | Stop: jargonaut post-processes Vocalinux only |
| claude CLI logged in | `claude --version` | Stop and tell the user to install and log in |
| Python 3.11 or newer (for `tomllib`) | `python3 --version` | Stop |
| systemd user session | `systemctl --user is-system-running` | Stop: the daemon needs a user unit |

Ask which recognition engine Vocalinux uses (the setting lives in the secret-bearing config file): jargonaut was built for Parakeet, whose only vocabulary input is the corrections JSON.

## Step 2: create the directories

```bash
mkdir -p ~/.config/jargonaut ~/.local/share/jargonaut/calibration
mkdir -p -m 700 ~/.local/state/jargonaut
```

## Step 3: choose the plugin folder

Vocalinux and the unit only know the launchers in `~/.local/bin` (`jargonaut-hook`, `jargonaut-daemon`), which point at 1 plugin folder. Use this plugin's folder, unless the launchers already point into a git checkout: then the user develops jargonaut, keep that checkout and say so.

```bash
JH=$(sed -n 's#^exec [^ ]* \(/.*\)/haiku/postproc_hook\.py.*#\1#p' ~/.local/bin/jargonaut-hook 2>/dev/null)
git -C "${JH:-/nonexistent}" rev-parse --is-inside-work-tree >/dev/null 2>&1 || JH="${CLAUDE_PLUGIN_ROOT}"
echo "$JH"
```

Set `JH` the same way at the start of every later command.

## Step 4: seed the vocabulary

If `~/.config/jargonaut/vocab.toml` exists, keep it and skip to step 5.

Otherwise collect candidate terms, counting how often each appears:

1. Ask where the user keeps code (for example `~/dev`). There: repository names, Go module and package names (`go.mod`), `package.json` names, Taskfile and Makefile targets, Kubernetes kinds (`kind:` in YAML), CLI tool names.
2. Command names: the first word of each line of `~/.bash_history` or `~/.zsh_history`, nothing else from those lines.
3. Past Claude Code prompts: the user messages of `~/.claude/projects/*/*.jsonl` (`type` "user", text content only), keeping only tokens that look like terms: CamelCase, kebab-case, dotted names, words with digits, all-caps acronyms.

Keep terms seen at least 3 times, drop plain dictionary words of the user's language, and show the user the list grouped by source, with counts. Remove what they reject, then write one entry per term:

```toml
[[term]]
term = "Podman"
```

Heard forms come later, from the `learn` skill: past prompts were often dictated with another recognizer, so their errors do not predict this one's.

Optionally create `~/.config/jargonaut/prompt.toml` from `$JH/examples/prompt.example.toml`: ask how the prompt should name the user, their language and field, and fill `name` and `speaker`. Leave the other keys out until calibration rounds give real examples.

## Step 5: generate the corrections

```bash
python3 "$JH/generate.py"
```

It writes Vocalinux's `custom-dictionary-corrections.json`, which Vocalinux reloads live. With no heard forms yet, it holds no corrections: that is expected.

## Step 6: install and start the service

```bash
python3 "$JH/launchers.py"
systemctl --user daemon-reload
systemctl --user enable --now jargonaut.service
systemctl --user restart jargonaut.service
systemctl --user is-active jargonaut.service
```

`launchers.py` writes the 2 launchers and the unit for `$JH`; it is idempotent, and `--check` reports drift. The restart makes an already running daemon pick up the new folder. Check that `$XDG_RUNTIME_DIR/jargonaut.sock` exists; on failure read `journalctl --user -u jargonaut.service -n 50` and fix the cause.

## Step 7: connect Vocalinux

Vocalinux reads its `config.json` once at start and rewrites it whole on every save, so the change is made while it is stopped. The file holds an API key: never open it yourself, `set_hook.py` changes only the script path and prints nothing else.

1. Ask the user to quit Vocalinux (tray icon > Quit).
2. Run `python3 "$JH/set_hook.py"`: it sets the script path to `~/.local/bin/jargonaut-hook` (`--hook PATH` for another one).

| Exit code | Meaning | Next |
|---|---|---|
| 0 | Script path set, or already set | Sub-step 3 below |
| 3 | Another script path is set; the script printed it | Show it to the user and ask whether to replace it; only on a yes, run again with `--force` |
| 4 | Vocalinux still runs | Ask the user to quit it, then run again |
| 1 | No config yet, or not valid JSON | Ask the user to open Vocalinux's Settings once and quit; never repair the file yourself |

3. Ask the user to start Vocalinux again, then to dictate 1 sentence, and check that a new line appears in `~/.local/state/jargonaut/haiku-$(date +%F).jsonl`.

The script also lists the names of the other `post_processing` settings (for example `enabled`). If post-processing looks disabled, tell the user to enable it in Settings > Post-processing.

## Step 8: hand over

Tell the user:

- jargonaut starts in shadow mode: it types the raw text and only logs what Haiku would have typed. `touch ~/.config/jargonaut/live` switches to live mode, `rm` switches back; offer to do it once a few calibration rounds look good.
- Dictated text is sent to Anthropic through the `claude` CLI; nothing else leaves the machine.
- After each update of the plugin, run this skill again: the launchers must point at the new plugin folder (steps 3 and 6 only; the rest is kept).
- Next step: the `learn` skill, which teaches jargonaut how this user's recognizer mishears their terms.
