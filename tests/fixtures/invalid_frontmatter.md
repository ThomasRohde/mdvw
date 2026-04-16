---
title: [This bracket is never closed
tags: - malformed
  also bad: ][
---

# Invalid Frontmatter

This file has broken YAML in the frontmatter block. The viewer should show
an error card with the parse message instead of silently swallowing it.

The body text below should still render normally.

## Section

> Some quoted text to make sure the rest of the markdown pipeline is fine.

$$
E = mc^2
$$
