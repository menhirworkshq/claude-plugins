---
name: learn
description: Use when the user wants jargonaut to learn how their dictation mishears technical terms, asks for a calibration round or a text to read aloud, pastes a dictated transcript to compare, or says a term keeps coming out wrong in Vocalinux.
---

# Teaching jargonaut

## Overview

Each round is a conversation: you write a short text dense in the user's terms, they read it with Vocalinux and paste what came out, and you turn every misrecognition into vocabulary. The user only reads and pastes; you do the rest, including regenerating and restarting.

Start every command with `A=~/.local/share/jargonaut/app D=~/.local/share/jargonaut`: `$A` is the installed runtime the service runs from, `$D` the data directory. Run the `install` skill first if `$A` is missing.

The vocabulary is `~/.config/jargonaut/vocab.toml`.

## Step 1: choose the round type

- **Raw** (default while terms are still being discovered): shows what the recognizer really hears. Pause the corrections, and the Haiku pass if it is live:

  ```bash
  echo '{"version":1,"corrections":[]}' > ~/.config/vocalinux/custom-dictionary-corrections.json
  [ -e ~/.config/jargonaut/live ] && mv ~/.config/jargonaut/live ~/.config/jargonaut/live.paused
  ```

  Vocalinux reloads the file on every segment; nothing needs a restart.
- **Live**: checks that the corrections and Haiku work in real use. Pause nothing.

Tell the user which type it is. Whatever happens next, step 7 restores what you paused.

## Step 2: write the text

- Number: `N` = 1 + the highest `roundN` in `$D/calibration/`.
- Untested terms: terms of `vocab.toml` that appear in no `$D/calibration/round*.ref.txt`. Use 15 to 25 of them, plus terms that failed in earlier rounds.
- About 150 words, in the user's dictation language, natural sentences they could really say, 1 sentence per line.
- 2 or 3 traps: ordinary words that sound like a term or a known heard form (for example "chez moi" next to chezmoi, "une panne" next to pane). They must come out unchanged.

Show the text and ask the user to read it with Vocalinux, then paste the result. They may skip any sentence.

## Step 3: save the pair

Save the text as `$D/calibration/roundN.ref.txt`, and the transcript as `roundN.raw.txt` for a raw round or `roundN.live.txt` for a live one. A live transcript never counts as raw recognizer output.

Skipped sentences: a sentence missing from the transcript, or replaced by a spoken "j'ignore cette phrase" or a similar marker, was skipped on purpose. Strip the marker, drop that sentence from both files before saving, and never report it or ask about it.

## Step 4: compare

```bash
git diff --no-index --word-diff=plain --word-diff-regex='[^[:space:]]+' $D/calibration/roundN.ref.txt $D/calibration/roundN.raw.txt
```

For each difference, decide:

| Case | Action |
|---|---|
| A term came out wrong | New heard form for that term |
| A trap was changed | Note it: an existing heard form is too greedy, make it ambiguous |
| An ordinary word differs (accent, plural, punctuation) | Ignore: not vocabulary |
| A term came out right | Nothing; it is now tested |

## Step 5: add the heard forms

A heard form goes into 1 entry only: safe or ambiguous, never both (`generate.py` refuses it). It is **ambiguous** when it is 3 characters or shorter, spelled letters ("K S"), or a real word or phrase in the user's language ("quick", "chez moi", "sonné"). Ambiguous forms go to the Haiku pass only; the others become deterministic corrections.

```bash
python3 $A/add.py Podman "pod man" "podmane"
python3 $A/add.py --ambiguous --hint "container tool, not a French word" Podman "pot man"
```

Never treat a term as done after 1 variant: hard terms have many (tmux heard as Temux, Simux, T-Meux). Unseen variants are left to Haiku.

## Step 6: record the checks

Append the round to `$D/eval-checks.toml`, 1 list per sentence of the saved transcript, in order:

```toml
[[round]]
n = 5
sentences = [
  [{fix = 'pot man', want = '\bPodman\b'}],   # error that must be fixed
  [{keep = 'une panne de courant'}],          # trap kept verbatim
  [],                                         # nothing to check
]
```

Then check that it parses: `python3 $A/haiku/eval.py --dry-run`.

## Step 7: regenerate and restore

```bash
python3 $A/generate.py
[ -e ~/.config/jargonaut/live.paused ] && mv ~/.config/jargonaut/live.paused ~/.config/jargonaut/live
systemctl --user restart jargonaut.service
```

`generate.py` rebuilds the corrections from `vocab.toml`, which also ends the pause; the restart makes the daemon rebuild the Haiku prompt with the new forms. If `generate.py` fails (a heard form mapped to 2 terms, or both safe and ambiguous), fix `vocab.toml` and run it again.

## Step 8: report and continue

Tell the user, in a few lines: terms tested, terms right, new heard forms (safe and ambiguous), traps kept or broken. Then offer the next round.

Stop suggesting raw rounds once one yields almost no new heard forms; suggest a live round, then live mode (`touch ~/.config/jargonaut/live`) if the user is in shadow mode and the live rounds look right.

## Common mistakes

| Mistake | Fix |
|---|---|
| Raw round with the live flag present | Pause it in step 1: Haiku would correct the text |
| Forgetting to restore after a round | Step 7 always runs, even if the user stops mid-round |
| Asking about a skipped sentence | Drop it silently |
| Short or real-word heard form made safe | Ambiguous: a correction would rewrite normal text |
| Saving a live transcript as raw | `roundN.live.txt` |
