---
name: cut-release
description: Cut a release atomically — bump version, date the CHANGELOG section, commit, tag. Invoke with /cut-release X.Y.Z.
disable-model-invocation: true
---

Version to release: `$ARGUMENTS`.

Preflight:

1. `git status --porcelain` — must be empty. If not, stop and tell the user.
2. `python -c "import mdvw; print(mdvw.__version__)"` — must end in `.devN`. If not, stop and tell the user to run `--post-release` first or amend manually.
3. Confirm `## [Unreleased]` in `CHANGELOG.md` has real notes (not just the placeholder comment). If it looks empty, ask the user to confirm before proceeding.

Then run the `/verify` skill — don't cut a release on a failing tree.

If all green, run:

```bash
python scripts/release.py $ARGUMENTS
```

Report the resulting commit SHA and tag. Then print the push command verbatim for the user to run:

```
git push origin main v$ARGUMENTS
```

**Do not push automatically.** The tag push triggers `release.yml` which publishes to PyPI — that's a decision for the user.

After they've pushed (and the release has landed), suggest:

```
python scripts/release.py --post-release <next>.dev0
```

to reopen the dev cycle.
