# AGENTS.md

Guidance for AI coding agents working on this repository. [`CONTRIBUTING.md`](./CONTRIBUTING.md) holds the full rules; this file lists what an agent must not miss.

## Before the first commit

Check that the lefthook hooks are installed: `ls .git/hooks/commit-msg`. If the file is missing, run `lefthook install`, then commit. Worktrees share the hooks of their clone.

Never commit with `--no-verify`, and never work around a hook failure: fix the message or the files. A commit pushed to `main` without the hook is only reported by the CI, not blocked.

## Commits

- Conventional Commits, in English, scope = the plugin's name; no scope for marketplace-only changes.
- Header 72 characters at most (aim for 50), lower case, imperative, no final period; body wrapped at 72 columns, saying why.
- 1 plugin and 1 topic per commit, with the plugin's name as scope when it touches `plugins/<name>/` (`task check-commits` enforces it). Stage only the files of that topic.
- No AI co-author or AI trailer.
- Rewriting pushed history needs the maintainer's explicit approval and `git push --force-with-lease=<branch>:<expected sha>`.

## Layout

- A plugin lives in `plugins/<name>/` with `.claude-plugin/plugin.json`.
- Adding one also adds its entry to `.claude-plugin/marketplace.json` and its name to the `scopes` of `.conform.yaml`, in the same commit.
- Plugins set no `version` (`task check-versions`).
- Work in a worktree on a branch, never in the main checkout. To try a change, the user starts `task dev -- <plugin>` from the worktree (a running session cannot load a plugin directory); after each edit, they run `/reload-plugins`.
- Run `task check` before saying a change is done.
- Never commit personal data, secrets, or a user's vocabulary, transcripts, logs or recordings, nor client or employer names. Personal data stays in the XDG dirs the plugins document.
