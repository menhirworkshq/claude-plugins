# Menhir Works plugins

Claude Code plugins by Menhir Works.

## Install

```
/plugin marketplace add plaffitt/menhirworks-plugins
/plugin install tmux-pilot@menhirworks
```

## Plugins

| Plugin | What it does |
|---|---|
| [tmux-pilot](https://github.com/plaffitt/tmux-pilot) | Lets Claude drive your tmux panes safely, with clear signs of who is typing |

## Adding a plugin

A plugin with its own repository is listed in `.claude-plugin/marketplace.json` with a `github` source. A small plugin without a repository of its own lives in `plugins/<name>/`, with its `.claude-plugin/plugin.json`, and is listed with a `./plugins/<name>` source. Run `claude plugin validate .` before each commit.

## License

MIT
