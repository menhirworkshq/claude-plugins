# Contributing

## Set up the hooks first

Commit messages are checked by a [lefthook](https://github.com/evilmartians/lefthook) hook. Install it before your first commit, in every clone:

```
lefthook install
```

`ls .git/hooks/commit-msg` shows whether it is installed. Worktrees share the hooks of their clone, so one install covers them.

The hooks need lefthook, [Task](https://taskfile.dev), Go (to install conform into `bin/`), jq, and the `claude` CLI for the plugin validation.

| Hook | Runs |
|---|---|
| `pre-commit` | `task validate` when the marketplace or a plugin changes, `task check-scopes` when the scopes or the plugin list change |
| `commit-msg` | `task conform` on the message |
| `pre-push` | `task check`: `validate` (skipped without the `claude` CLI), `check-scopes`, `check-versions`, `check-commits` (each commit touches 1 plugin at most, and takes its name as scope) and every plugin's tests (`task test`) |

Never skip them with `--no-verify`. The CI runs the same checks on every pull request and on every push to `main`, where a bad commit is reported but not blocked: the local hook is what keeps it out.

## Commits

- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/), in English. The scope is the name of the plugin the commit touches (`feat(tmux-pilot): ...`); a commit that touches only the marketplace itself takes no scope.
- 1 commit touches 1 plugin and 1 topic. A commit that changes `plugins/<name>/` must take `<name>` as scope; only a commit that touches no plugin goes without one. `task check-commits` enforces it before each push and in the CI.
- Header: 72 characters at most (aim for 50), lower case, imperative, no final period.
- Body: optional; it says why, not what the diff shows; wrapped at 72 columns.
- No AI co-author or AI trailer.
- Review fixes: `git commit --fixup=<sha>`, folded with `git rebase -i --autosquash` before the merge. The hook lets `fixup!`, `squash!` and `amend!` commits through; the pull request check rejects them until they are folded.

## History

`main` keeps a linear history: no merge commits. Bring a branch up to date with `git rebase origin/main`, not by merging `main` into it. The maintainer may push to `main` directly; everyone else goes through a pull request.

## Plugins

Each plugin lives in `plugins/<name>/` with its `.claude-plugin/plugin.json`, and sets no `version` (`task check-versions`): see the README. Adding a plugin, in the same commit:

1. its folder and `plugin.json`;
2. its entry in `.claude-plugin/marketplace.json`, with a `./plugins/<name>` source;
3. its name in the `scopes` of `.conform.yaml` (`task check-scopes` fails while the 2 lists differ).

Run `task check` before pushing (the pre-push hook does); `task --list` shows every task. Never commit personal data, secrets, or a user's own vocabulary, logs or recordings: plugins ship code and examples only.

## Working on a plugin

Everyday sessions use the plugins installed from the marketplace. To change one, work in a worktree and test it in a session that loads the worktree's copy:

```
git worktree add ../claude-plugins-<topic> -b <type>/<topic>
cd ../claude-plugins-<topic>
task dev -- <plugin>        # claude --plugin-dir plugins/<plugin>, after validating it
```

- `task dev` with no name loads every plugin of the checkout; several names load several plugins.
- `--plugin-dir` replaces the installed plugin of the same name for that session only, silently: `claude plugin list` still shows the installed one as enabled, and only `claude --debug` logs the override. Nothing is written to the settings.
- After editing the plugin's files, run `/reload-plugins` in that session; changes to monitors need a new session.
- A session cannot load a plugin directory once started, so an agent working in a worktree prepares the change and gives the user the `task dev` command to try it.
- A plugin with a Taskfile.yaml gets its `test` task run by `task test`; add one when a plugin has code to test.
