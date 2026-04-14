# Welcome to mdvw

A fast, portable, fully offline Markdown viewer/editor for Windows.

---

## Text Formatting

**bold**, *italic*, ***bold italic***, ~~strikethrough~~, ++underline++, `inline code`, ==highlighted==.

Colored text: {color:orange}orange{/color}, {color:purple}purple{/color}, {color:cyan}cyan{/color}.

## Code

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"

print(greet("World"))
```

## Math

Euler's identity: $e^{i\pi} + 1 = 0$

$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$

## Diagrams

```mermaid
graph LR
    A[Open .md] --> B[Edit]
    B --> C[Preview]
    C --> D[Save]
```

## Tables

| Feature | mdvw |
|---|---|
| Offline | Yes |
| Math (KaTeX) | Yes |
| Diagrams (Mermaid) | Yes |
| Code (Shiki) | Yes |
| System tray | Yes |

## Tasks

- [x] Parse markdown
- [x] Render math
- [ ] Ship to PyPI

> Press `E` to edit, `Ctrl+S` to save.
