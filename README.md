# Menhir Works Claude Code plugins

Claude Code plugins by Menhir Works.

## Install

```
/plugin marketplace add menhirworks/claude-plugins
/plugin install <plugin>@menhirworks
```

## Plugins

| Plugin | What it does |
|---|---|
| [tmux-pilot](https://github.com/plaffitt/tmux-pilot) | Lets Claude drive your tmux panes safely, with clear signs of who is typing |

## Layout

Each plugin lives in its own folder, `plugins/<name>/`, with its `.claude-plugin/plugin.json` and its own version, and is listed in `.claude-plugin/marketplace.json` with a `./plugins/<name>` source:

```
.claude-plugin/marketplace.json
plugins/
  <name>/
    .claude-plugin/plugin.json
    skills/
    hooks/
    README.md
```

A plugin moves to a repository of its own only once it is mature and draws outside interest; the marketplace then lists it with a `github` source, as it does for tmux-pilot.

## Commits

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). The scope is the name of the plugin a commit touches, for example `feat(tmux-pilot): ...`; a commit that touches only the marketplace itself (this README, `marketplace.json`) takes no scope. One commit touches one plugin.

Adding a plugin means adding its name to the `scopes` of `.conform.yaml` too; `task check-scopes` fails while the 2 lists differ.

## Development

The hooks need [lefthook](https://github.com/evilmartians/lefthook), [Task](https://taskfile.dev), Go (to install conform), jq, and the `claude` CLI for the plugin validation. After cloning, register the hooks:

```
lefthook install
```

| Hook | Runs |
|---|---|
| `pre-commit` | `task validate` when the marketplace or a plugin changes, `task check-scopes` when the scopes or the plugin list change |
| `commit-msg` | `task conform`: Conventional Commits, scope among the plugins, header of 72 characters at most, lower case, imperative, no final period, body wrapped at 72 columns |

`fixup!`, `squash!` and `amend!` commits pass the hook, since `git rebase --autosquash` folds them; the CI lints every commit of a pull request and rejects them until they are folded. `task --list` shows the tasks.

## License

MIT
