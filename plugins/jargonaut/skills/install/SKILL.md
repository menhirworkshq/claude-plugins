---
name: install
description: Use when the user wants to set up jargonaut, the Vocalinux post-processing plugin, or says that dictation mangles technical terms and they just installed this plugin, or when the jargonaut service, its link or its vocabulary is missing.
---

# Installing jargonaut

## Overview

The user installed the plugin and only talks; you do every step. Ask a question only when the answer cannot be found on the machine. Never overwrite what the user already has: an existing vocabulary, link or unit is kept unless they agree to replace it.

Below, `J` is the stable link `~/.local/share/jargonaut/current`, and the plugin folder is `${CLAUDE_PLUGIN_ROOT}`.

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

## Step 3: point the stable link

The unit and Vocalinux only know `J`, so a plugin update only means moving the link.

- No link yet: `ln -sfn "${CLAUDE_PLUGIN_ROOT}" ~/.local/share/jargonaut/current`.
- A link exists: `readlink ~/.local/share/jargonaut/current`. If it points to a git checkout (it holds a `.git` or sits in a worktree), the user develops jargonaut: keep it and say so. Otherwise point it at `${CLAUDE_PLUGIN_ROOT}`.

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

Optionally create `~/.config/jargonaut/prompt.toml` from `${CLAUDE_PLUGIN_ROOT}/examples/prompt.example.toml`: ask how the prompt should name the user, their language and field, and fill `name` and `speaker`. Leave the other keys out until calibration rounds give real examples.

## Step 5: generate the corrections

```bash
python3 ~/.local/share/jargonaut/current/generate.py
```

It writes Vocalinux's `custom-dictionary-corrections.json`, which Vocalinux reloads live. With no heard forms yet, it holds no corrections: that is expected.

## Step 6: install and start the service

```bash
mkdir -p ~/.config/systemd/user
ln -sfn ~/.local/share/jargonaut/current/systemd/jargonaut.service ~/.config/systemd/user/jargonaut.service
systemctl --user daemon-reload
systemctl --user enable --now jargonaut.service
systemctl --user is-active jargonaut.service
```

If the unit was already enabled before the link changed, run `systemctl --user reenable jargonaut.service`: `enable` resolved the old link. Check that `$XDG_RUNTIME_DIR/jargonaut.sock` exists; on failure read `journalctl --user -u jargonaut.service -n 50` and fix the cause.

## Step 7: connect Vocalinux

Vocalinux reads its `config.json` once at start and rewrites it whole on every save, so the change is made while it is stopped. The file holds an API key: never open it yourself, `set_hook.py` changes only the script path and prints nothing else.

1. Ask the user to quit Vocalinux (tray icon > Quit).
2. Run `python3 ~/.local/share/jargonaut/current/set_hook.py` (`--hook PATH` when the hook lives elsewhere).

| Exit code | Meaning | Next |
|---|---|---|
| 0 | Script path set, or already set | Step 3 |
| 3 | Another script path is set; the script printed it | Show it to the user and ask whether to replace it; only on a yes, run again with `--force` |
| 4 | Vocalinux still runs | Ask the user to quit it, then run again |
| 1 | No config yet, or not valid JSON | Ask the user to open Vocalinux's Settings once and quit; never repair the file yourself |

3. Ask the user to start Vocalinux again, then to dictate 1 sentence, and check that a new line appears in `~/.local/state/jargonaut/haiku-$(date +%F).jsonl`.

The script also lists the names of the other `post_processing` settings (for example `enabled`). If post-processing looks disabled, tell the user to enable it in Settings > Post-processing.

## Step 8: hand over

Tell the user:

- jargonaut starts in shadow mode: it types the raw text and only logs what Haiku would have typed. `touch ~/.config/jargonaut/live` switches to live mode, `rm` switches back; offer to do it once a few calibration rounds look good.
- Dictated text is sent to Anthropic through the `claude` CLI; nothing else leaves the machine.
- Next step: the `learn` skill, which teaches jargonaut how this user's recognizer mishears their terms.
