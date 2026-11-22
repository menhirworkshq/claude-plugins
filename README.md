# Menhir Works Claude Code plugins

Claude Code plugins by Menhir Works.

## Install

```
/plugin marketplace add menhirworkshq/claude-plugins
/plugin install <plugin>@menhirworks
```

## Plugins

| Plugin | What it does |
|---|---|
| [git-history](plugins/git-history) | Gives a branch a clean history, one change per commit: split mixed commits, regroup reworks, harden a branch before merging |
| [jargonaut](plugins/jargonaut) | Post-processing for [Vocalinux](https://github.com/VocaHQ/vocalinux) dictation that fixes technical jargon, with your vocabulary and Claude Haiku |
| [tmux-pilot](https://github.com/menhirworkshq/tmux-pilot) | Lets Claude drive your tmux panes safely, with clear signs of who is typing |

## Layout

Each plugin lives in its own folder, `plugins/<name>/`, with its `.claude-plugin/plugin.json`, and is listed in `.claude-plugin/marketplace.json` with a `./plugins/<name>` source:

```
.claude-plugin/marketplace.json
plugins/
  <name>/
    .claude-plugin/plugin.json
    skills/
    hooks/
    README.md
```

Plugins of this repository set no `version`, in `plugin.json` or in `marketplace.json`: an installed plugin then follows the commits of the marketplace (its version is the commit SHA), instead of staying on a cached copy until someone bumps a number. `task check-versions` enforces it. A plugin that moves to a repository of its own may start versioning there.

A plugin moves to a repository of its own only once it is mature and draws outside interest; the marketplace then lists it with a `github` source, as it does for tmux-pilot.

## Commits

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). The scope is the name of the plugin a commit touches, for example `feat(tmux-pilot): ...`; a commit that touches only the marketplace itself (this README, `marketplace.json`) takes no scope. One commit touches one plugin.

Adding a plugin means adding its name to the `scopes` of `.conform.yaml` too; `task check-scopes` fails while the 2 lists differ.

## Development

Run `lefthook install` after cloning, before your first commit: the hooks check every commit message. [`CONTRIBUTING.md`](./CONTRIBUTING.md) lists the tools they need, the rules and how to try a change to a plugin.

## License

MIT
