"""Generate src/mdvw/assets/icon.ico from the CommonMark/Markdown mark.

The Markdown mark (dcurtis/markdown-mark) is public domain (CC0). We draw
it programmatically so there's no upstream download at build time.

Run:  python scripts/generate_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "mdvw" / "assets" / "icon.ico"


def _draw_mark(size: int) -> Image.Image:
    """Draw the Markdown mark at `size` x `size` on a transparent canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Mark viewBox is 208x128 — fit inside our square with 10% padding.
    pad = int(size * 0.08)
    box_w = size - 2 * pad
    box_h = int(box_w * 128 / 208)
    x0 = pad
    y0 = (size - box_h) // 2
    x1 = x0 + box_w
    y1 = y0 + box_h

    # Stroke thickness scales with size.
    stroke = max(1, round(size * 0.055))
    radius = int(box_h * 0.17)

    # Rounded-rect outline (black).
    d.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=(0, 0, 0, 255), width=stroke)

    # Inner drawing area.
    inner_pad = int(box_h * 0.13)
    ix0, iy0 = x0 + inner_pad, y0 + inner_pad
    ix1, iy1 = x1 - inner_pad, y1 - inner_pad
    ih = iy1 - iy0

    # "M" (left half): two vertical bars + two diagonal legs forming ᴍ shape.
    # Draw as a polygon filled black.
    m_left = ix0 + int(ih * 0.08)
    m_right = ix0 + int(ih * 1.15)
    m_top = iy0
    m_bot = iy1
    thick = max(1, round(ih * 0.18))

    mid_x = (m_left + m_right) // 2
    # Outer silhouette of the "M": two tall bars and an inner V.
    # Bar widths:
    bar_w = int(ih * 0.22)
    v_depth = int(ih * 0.55)
    m_polygon = [
        (m_left, m_bot),
        (m_left, m_top),
        (m_left + bar_w, m_top),
        (mid_x, m_top + v_depth),
        (m_right - bar_w, m_top),
        (m_right, m_top),
        (m_right, m_bot),
        (m_right - bar_w, m_bot),
        (m_right - bar_w, m_top + int(ih * 0.33)),
        (mid_x, m_bot - int(ih * 0.05)),
        (m_left + bar_w, m_top + int(ih * 0.33)),
        (m_left + bar_w, m_bot),
    ]
    d.polygon(m_polygon, fill=(0, 0, 0, 255))

    # Down arrow (right side).
    a_left = m_right + int(ih * 0.30)
    a_right = ix1
    a_top = iy0 + int(ih * 0.10)
    a_bot = iy1
    a_cx = (a_left + a_right) // 2
    shaft_w = int((a_right - a_left) * 0.30)
    head_top = a_top + int((a_bot - a_top) * 0.55)
    # Shaft
    d.rectangle(
        (a_cx - shaft_w // 2, a_top, a_cx + shaft_w // 2, head_top),
        fill=(0, 0, 0, 255),
    )
    # Arrowhead
    d.polygon(
        [
            (a_left, head_top),
            (a_right, head_top),
            (a_cx, a_bot),
        ],
        fill=(0, 0, 0, 255),
    )

    # Suppress linter warnings for locals kept for readability.
    _ = (thick, stroke)
    return img


def main() -> int:
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    big = _draw_mark(256)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Pillow's ICO writer uses the base image and resamples to each size
    # in `sizes`. Pass the 256x256 so downscaled frames stay crisp.
    big.save(OUT, format="ICO", sizes=sizes)
    print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
