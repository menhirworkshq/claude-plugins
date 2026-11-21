---
name: split-commits
description: Use when a commit or a set of uncommitted changes mixes several unrelated changes (a catch-all "and stuff" or "misc" commit, a feature plus an unrelated config file, a refactor plus a fix), when the user wants to split a commit, or before committing a working tree that holds more than one topic.
---

# Splitting commits

## Overview

Each commit carries one change. A commit or a working tree that holds several unrelated changes is cut into one commit per change, without losing or adding anything.

## What is one change

Group the hunks by the reason they exist, not by file:

| Hunks | Same commit? |
|---|---|
| A feature, its tests, and its own documentation (README section, usage) | Yes |
| A feature and an unrelated config, tooling or formatting change | No |
| A refactor and a behaviour change built on it | No: the refactor first, then the change |
| A bug fix and a feature in the same file | No |
| A rename and the code that follows it | Yes, when the rename only serves that code |

A file can hold hunks of several changes: split by hunk (`git add -p`), not by file.

## Splitting uncommitted changes

1. List the changes: `git status`, `git diff`, and decide the commits and their order (what others depend on comes first).
2. For each commit, stage only its paths or hunks (`git add <paths>` or `git add -p`), check with `git diff --cached --stat`, commit.
3. Never sweep in unrelated work in progress of the user: leave what does not belong to any planned commit unstaged.

## Splitting an existing commit

1. Keep a backup and record the final tree (skip this when `harden-branch` already did it):

   ```bash
   git branch backup/<branch>-before-split <branch>
   git rev-parse <branch>^{tree}
   ```

2. Stop on the commit to split: `GIT_SEQUENCE_EDITOR="sed -i 's/^pick <sha>/edit <sha>/'" git rebase -i <sha>^`.
3. Undo it, keeping its changes in the working tree: `git reset HEAD^`.
4. Commit each part as above. Keep the original author and date on each part: `git commit -C <sha>` reuses them with the original message, then reword with `git commit --amend -m "<subject>"` (the date stays).
5. `git rebase --continue`.
6. Verify: `git rev-parse <branch>^{tree}` equals the recorded tree, and each new commit builds and passes the tests (`git rebase <base> --exec '<test command>'`).

Non-interactive alternative, inside a rebase todo list: right after the `pick` of the commit to split, add 1 `exec` line that undoes it, commits each part with its own subject, and fails if anything is left over (a lost hunk):

```
pick da92045 add cli and stuff
exec git reset -q HEAD^ && git add .editorconfig && git commit -q -C da92045 && git commit -q --amend -m "chore: add an editorconfig" && git add cli.py README.md && git commit -q -C da92045 && git commit -q --amend -m "feat: convert lengths from the command line" && git diff --quiet && git diff --cached --quiet
```

A `fixup` line placed after that `exec` applies to the last part it committed: commit last the part that later reworks fold into, or move those reworks with `regroup-commits` afterwards.

## Subjects

Each part gets its own subject describing its change, following the repository's convention (`git log --format=%s -n 30`). A part that is tooling or configuration gets `chore`, `ci` or `build`, not the `feat` of the commit it came from.

## Common mistakes

| Mistake | Fix |
|---|---|
| Splitting by file when a file holds 2 changes | Split by hunk with `git add -p` |
| A part that does not build on its own | Reorder: what it depends on comes first |
| Parts all titled like the original commit | One subject per change |
| New author dates on the split parts | `git commit -C <sha>` keeps them |
| Final tree differs from the recorded one | A hunk was lost or doubled: start again from the backup |
