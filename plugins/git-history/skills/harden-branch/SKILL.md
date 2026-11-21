---
name: harden-branch
description: Use when the user wants to harden, finalize, clean up or tidy the history of a branch, to make it readable for review, or to prepare it for merging, so that each commit carries one change while the small, scattered reworks are regrouped.
---

# Hardening a branch

## Overview

While a branch lives, its commits pile up as the work went: features, fixes of those features, tweaks, review fixes, unrelated touches. Hardening rewrites that history so that each commit carries one change and the reader sees what the branch does, not how it was written. The branch's final content does not change.

It can run at any time, and several times. It is recommended right before the branch is merged or integrated, whether or not a review happened before or after.

This skill drives 2 others:

- **REQUIRED SUB-SKILL:** `split-commits`, for commits that mix unrelated changes.
- **REQUIRED SUB-SKILL:** `regroup-commits`, for commits that rework an earlier commit of the branch.

## Steps

1. **Find the base and the conventions.** The base is where the branch will be merged (`main` unless the user or the merge request says otherwise); work on `git merge-base <base> <branch>`. Read the repository's commit rules (`CONTRIBUTING.md`, `AGENTS.md`, commit-lint config, `git log --format=%s -n 30 <base>`).
2. **Make it safe.** Clean working tree, one backup branch for the whole run (`git branch backup/<branch>-before-harden <branch>`; the sub-skills then skip theirs), and the final tree recorded (`git rev-parse <branch>^{tree}`).
   Find the test command: the CI config, then `Taskfile.yaml`, `Makefile`, `package.json` scripts, the README; ask the user if none says. It must leave no untracked files behind, or later checks for a clean tree fail mid-rebase: disable build caches (`PYTHONDONTWRITEBYTECODE=1`) or ignore untracked files in the check (`git status --porcelain --untracked-files=no`).
3. **Map the series.** `git log --reverse -p <base>..<branch>`. Label each commit: one change of its own, a rework of commit X, add-then-remove with commit Y, or mixed.
4. **Split** the mixed commits with `split-commits`.
5. **Regroup** the reworks into their targets and drop the add-then-remove pairs with `regroup-commits`. Commits that touch code already on the base, or unrelated changes, stay as their own commits with their content unchanged.

   Steps 4 and 5 can be one rebase with one todo list: the split as an `exec` line after the commit it splits, the reworks as `fixup` lines after their target, the pairs as `drop`. A `fixup` right after a split `exec` folds into the last part that `exec` committed, so commit that part last.
6. **Order and name.** What a commit depends on comes before it. Each subject describes its whole change and follows the repository's convention; that includes kept commits whose subject does not say what they do.
7. **Verify:**
   - `git rev-parse <branch>^{tree}` equals the recorded tree;
   - no `fixup!`, `squash!` or `amend!` subject remains;
   - each commit builds and passes the tests: `git rebase <base> --exec '<test command>'`;
   - `git log --stat <base>..<branch>` reads as one change per commit.
8. **Report** the old and new series side by side, and what was folded, split, dropped or kept. Keep the backup branch until the user says it can go.
9. **Push** only with the user's go if the branch was already pushed, with `git push --force-with-lease=<branch>:<expected remote sha>`. On GitLab, mark the merge request ready again if pushing `fixup!` commits turned it into a draft.

## Quick reference

| Found in the series | Outcome |
|---|---|
| Fix, tweak, "wip", review fix of a change made earlier on the branch | Folded into that change's commit |
| Debug or temporary code added, then removed | Both dropped |
| One commit with unrelated changes | Split, one commit per change |
| Change to code already on the base, unrelated to the branch's purpose | Its own commit, kept as is |
| Commit already clean | Kept |

## Common mistakes

| Mistake | Fix |
|---|---|
| Keeping review fixes as separate commits | Fold them: a reviewer reads the final change, not the iterations |
| Merging unrelated commits to reduce the count | The goal is one change per commit, not few commits |
| Dropping or moving unrelated commits out of the branch | Keep them; ask the user if they think they belong elsewhere |
| Skipping the tree check | The recorded tree must match: the rewrite changes the cut, never the content |
| Force-pushing without asking | The user's go first, then `--force-with-lease` |
