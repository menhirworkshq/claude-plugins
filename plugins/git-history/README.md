# git-history

Skills that give a branch a clean history, where each commit carries one change, while the small reworks made along the way are regrouped into the change they belong to.

## Install

```
/plugin marketplace add menhirworkshq/claude-plugins
/plugin install git-history@menhirworks
```

## Skills

| Skill | What it does |
|---|---|
| `split-commits` | Cuts a commit, or uncommitted changes, that mix unrelated changes into one commit per change |
| `regroup-commits` | Folds each rework (fix, tweak, review fix, "wip") into the commit of the branch that introduced the code, drops add-then-remove churn, and keeps unrelated changes apart |
| `harden-branch` | Runs both on a whole branch: maps the series, splits, regroups, orders and names the commits, then checks that the final content is unchanged and that every commit passes the tests |

`harden-branch` can run at any time, and several times; it is recommended right before a branch is merged or integrated, before or after its review.

The rewrite never changes what the branch contains: the final tree is checked against the one recorded before, a backup branch is kept, and a branch already pushed is only force-pushed with your go, with `--force-with-lease`.

## License

MIT
