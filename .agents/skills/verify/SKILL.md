---
name: verify
description: Run the full mdvw quality gate — ruff, pytest, and the vendor-manifest hash check. Invoke with /verify.
---

Run these three checks in order and stop on the first failure.

```bash
ruff check src tests scripts
```

If that passes:

```bash
pytest -q
```

If that passes:

```bash
python scripts/fetch_vendor.py --verify
```

All three must pass before committing, tagging, or pushing. Report the first failure with the exact command output so it's easy to diagnose. When all three pass, say so in one line and stop.
