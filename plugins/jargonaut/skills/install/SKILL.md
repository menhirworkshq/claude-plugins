---
name: install
description: Use when the user wants to set up jargonaut, the Vocalinux post-processing plugin, or says that dictation mangles technical terms and they just installed this plugin, when the jargonaut service, its runtime or its vocabulary is missing, or when a session start message says the installed jargonaut is out of date.
---

# Installing jargonaut

## Overview

The user installed the plugin and only talks; you do every step. Ask a question only when the answer cannot be found on the machine. Never overwrite what the user already has: an existing vocabulary or post-processing script is kept unless they agree to replace it.

Below, `A` is the installed runtime, `~/.local/share/jargonaut/app`: a copy of this plugin, or a link to a git checkout when the user develops jargonaut. Vocalinux and the service only reach it through the launchers `~/.local/bin/jargonaut-hook` and `jargonaut-daemon`.

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

## Step 3: seed the vocabulary

If `~/.config/jargonaut/vocab.toml` exists, keep it and skip to step 4.

Otherwise collect candidate terms with `seed.py`. Never read these sources yourself (no `cat`, `grep` or `Read` of histories or transcripts): they can hold pasted credentials, and `seed.py` prints only term-like tokens with their counts, never a line, and drops tokens that look like secrets. Each source is opt-in: ask the user about each one before passing it, and say what it reads.

1. Code: ask where the user keeps code (for example `~/dev`), then `--code DIR`. It reads repository names, Go module names (`go.mod`), `package.json` names, Taskfile and Makefile targets and Kubernetes kinds, and never opens files named like secrets (`.env`, `*secret*`, `*.key`...).
2. Shell history: ask before passing `--history`. It keeps only the command (first word) of each line of `~/.bash_history` and `~/.zsh_history`.
3. Past Claude Code prompts: ask before passing `--prompts`. It keeps only term-like tokens (CamelCase, kebab-case, dotted names, words with digits, acronyms) of the user messages in `~/.claude/projects/*/*.jsonl`.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/seed.py" --code ~/dev --history --prompts   # only the sources the user accepted
```

`seed.py` keeps terms seen at least 3 times (`--min`). Drop plain dictionary words of the user's language, and show the user the list grouped by source, with counts. Remove what they reject, then write one entry per term:

```toml
[[term]]
term = "Podman"
```

Heard forms come later, from the `learn` skill: past prompts were often dictated with another recognizer, so their errors do not predict this one's.

Optionally create `~/.config/jargonaut/prompt.toml` from `${CLAUDE_PLUGIN_ROOT}/examples/prompt.example.toml`: ask how the prompt should name the user, their language and field, and fill `name` and `speaker`. Leave the other keys out until calibration rounds give real examples.

## Step 4: install the runtime and the service

```bash
A=~/.local/share/jargonaut/app
if [ -L "$A" ] && git -C "$(readlink -f "$A")" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "development checkout: $(readlink -f "$A")"
else
  python3 "${CLAUDE_PLUGIN_ROOT}/install.py"
fi
systemctl --user is-active jargonaut.service
```

- `install.py` copies this plugin to `$A`, writes the 2 launchers and the user unit, reloads systemd, and starts or restarts the service. It is idempotent; `--check` exits 1 when `$A` differs from this plugin.
- When `$A` links to a git checkout, the user develops jargonaut: never replace it with a copy. Say so; if the launchers or the unit are missing, rerun `install.py --link` from that checkout.
- Check that `$XDG_RUNTIME_DIR/jargonaut.sock` exists. On failure, read `journalctl --user -u jargonaut.service -n 50` and fix the cause.

## Step 5: generate the corrections

```bash
python3 ~/.local/share/jargonaut/app/generate.py
```

It writes Vocalinux's `custom-dictionary-corrections.json`, which Vocalinux reloads live. With no heard forms yet, it holds no corrections: that is expected.

## Step 6: connect Vocalinux

Vocalinux reads its `config.json` once at start and rewrites it whole on every save, so the change is made while it is stopped. The file holds an API key: never open it yourself, `set_hook.py` changes only the script path and prints nothing else.

1. Ask the user to quit Vocalinux (tray icon > Quit).
2. Run `python3 ~/.local/share/jargonaut/app/set_hook.py`: it sets the script path to `~/.local/bin/jargonaut-hook` (`--hook PATH` for another one).

| Exit code | Meaning | Next |
|---|---|---|
| 0 | Script path set, or already set | Sub-step 3 below |
| 3 | Another script path is set; the script printed it | Show it to the user and ask whether to replace it; only on a yes, run again with `--force` |
| 4 | Vocalinux still runs | Ask the user to quit it, then run again |
| 1 | No config yet, or not valid JSON | Ask the user to open Vocalinux's Settings once and quit; never repair the file yourself |

3. Ask the user to start Vocalinux again, then to dictate 1 sentence, and check that a new line appears in `~/.local/state/jargonaut/haiku-$(date +%F).jsonl`.

The script also lists the names of the other `post_processing` settings (for example `enabled`). If post-processing looks disabled, tell the user to enable it in Settings > Post-processing.

## Step 7: hand over

Tell the user:

- jargonaut starts in shadow mode: it types the raw text and only logs what Haiku would have typed. `touch ~/.config/jargonaut/live` switches to live mode, `rm` switches back; offer to do it once a few calibration rounds look good.
- Dictated text is sent to Anthropic through the `claude` CLI; nothing else leaves the machine.
- After an update of the plugin, a message at session start asks to run `/jargonaut:install` again: it reruns step 4 only, the vocabulary and the Vocalinux setting are kept.
- Next step: the `learn` skill, which teaches jargonaut how this user's recognizer mishears their terms.
