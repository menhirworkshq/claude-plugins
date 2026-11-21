---
name: regroup-commits
description: Use when a branch has commits that rework what an earlier commit of the same branch introduced (fixes, tweaks, review fixes, "wip", "oops", add-then-remove churn, fixup! commits), when the user wants to squash, fold or regroup commits before review or merge, or when reviewers see a series of small commits about the same change.
---

# Regrouping commits

## Overview

Each commit of a branch carries one change. A commit that reworks something an earlier commit of the same branch introduced is not a change of its own: it is the unfinished part of that earlier commit, so it is folded into it. Unrelated changes are never folded together.

The branch's final content never changes: only how it is cut into commits.

## The folding rule

For each commit of the branch, look at what its diff touches and ask: was that code, text or file introduced by an earlier commit of this branch?

| The commit | Action |
|---|---|
| Fixes, tweaks, renames or completes what an earlier commit of the branch added (typo, forgotten case, output format, a "wip") | Fold into that earlier commit |
| Is a review fix of that code, even one that adds a test or a new check | Fold into the commit that introduced the code it fixes |
| Adds something, a later commit removes it (debug print, temporary code) | Drop both |
| Changes code that was already on the base branch, or adds an unrelated change | Keep as its own commit with its content unchanged; reword its subject only if it does not say what the commit does |
| Mixes several of the above | Split it first with the `split-commits` skill, then apply this table to each part |

A review fix is folded even when it changes behaviour: the reviewer asked for the commit to be right, not for a second commit. Keep it separate only if it is a change the branch did not set out to make at all; then it is unrelated, and its own commit.

Never fold 2 commits only because they touch the same file or are small: they must be the same change.

## Steps

1. Read the series: `git log --reverse -p <base>..<branch>`. Write down, for each commit, the commit it folds into, "drop", or "keep".
2. Keep a backup (`git branch backup/<branch>-before-regroup <branch>`) and record the final tree (`git rev-parse <branch>^{tree}`); skip this when `harden-branch` already did it.
3. Rewrite. Prefer marking each rework as a fixup of its target, then autosquash:

   ```bash
   # a commit to fold: reword it into a fixup of its target, or build the todo list directly
   GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>    # folds existing fixup!/squash!/amend! commits
   ```

   For a regroup that is not already expressed as `fixup!` commits, write the todo list yourself and pass it with `GIT_SEQUENCE_EDITOR="cp <todo file>"`: move each rework right after its target as `fixup`, write `drop` for add-then-remove pairs, keep unrelated commits as `pick` in their order.
4. Conflicts: a rework that cannot apply at its target's position usually touches code a later commit of the branch also changed. Resolve it so that the end of the rebase still reaches the recorded tree; if the intermediate result gets awkward, fold the rework into the later commit that introduced the code it touches instead.
5. Reword any commit whose message no longer covers its content, with `exec git commit --amend -m "<new subject>"` right after it and its fixups in the todo list. The subject describes the whole change, not its first or largest part.
6. Verify, and stop at the first failure:
   - `git rev-parse <branch>^{tree}` equals the recorded tree;
   - no `fixup!`, `squash!` or `amend!` subject is left: `git log --format=%s <base>..<branch>`;
   - each commit builds and passes the tests: `git rebase <base> --exec '<test command>'` (see `harden-branch` for finding the test command and keeping the tree clean);
   - the series reads as one change per commit.

## Pushed branches

A branch already pushed needs a force push after the regroup. Ask the user before it, unless they already approved this push, and pin the remote tip you expect:

```bash
git push --force-with-lease=<branch>:<sha you expect on the remote> origin <branch>
```

Never rewrite the base branch or a branch someone else builds on. On GitLab, pushing `fixup!` commits turns the merge request back into a draft: after the regroup and the push, mark it ready again (`glab mr update <id> --ready`) if it was ready before.

## Common mistakes

| Mistake | Fix |
|---|---|
| Keeping a review fix as its own commit because it is "more readable" | Fold it into the commit that introduced the code |
| Folding an unrelated commit because it is small or in the same file | Keep it; only reworks of the branch's own changes fold |
| Moving an unrelated commit to another branch or dropping it | Keep it in the branch, as is, unless the user asks |
| Merged commit titled after 1 of its parts | Subject covering the whole content |
| Final tree differs from the recorded one | Something was lost or added: start again from the backup |
| `git push --force` | `--force-with-lease=<branch>:<sha>`, after the user's go |
