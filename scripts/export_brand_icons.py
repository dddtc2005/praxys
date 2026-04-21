"""Render the Praxys flag mark to PNG at several sizes.

The SVG source (web/public/favicon.svg) uses a 48×48 viewBox with:
  - Pole: line from (14, 42) to (16, 5), cobalt stroke, round caps
  - Flag: filled path `M 16 6 L 40 8 Q 33 14, 40 20 L 15 22 Z`

Pillow can't render SVG, but the geometry is simple enough to redraw
natively: pole via line + endpoint circles, flag via polygon with the
trailing-edge Bezier sampled to straight segments.

Run: python scripts/export_brand_icons.py

Outputs land in docs/brand/assets/:
  - praxys-icon-144.png           (paper bg, miniprogram-ready)
  - praxys-icon-144-transparent.png
  - praxys-icon-512.png           (App Store / high-res)
  - praxys-icon-512-transparent.png
  - praxys-icon-1024.png          (marketing / generic high-res)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# ────────────────────────────────────────────────────────────────────
# Brand colors (matches docs/brand/index.html — light theme values)
# ────────────────────────────────────────────────────────────────────
BG_PAPER = (248, 245, 236)           # oklch(0.975 0.008 85) → warm paper
FLAG_GREEN = (74, 158, 110)          # oklch(0.55 0.16 155)  → primary green
POLE_COBALT = (46, 113, 198)         # oklch(0.50 0.18 258)  → cobalt

# ────────────────────────────────────────────────────────────────────
# Flag geometry on a 48×48 logical grid (matches favicon.svg)
# ────────────────────────────────────────────────────────────────────
VIEWBOX = 48.0

POLE = ((14.0, 42.0), (16.0, 5.0))               # bottom → top
POLE_WIDTH_UNITS = 3.0                           # matches favicon stroke (scales below)

FLAG_PATH = [
    ("M", 16.0, 6.0),                            # top-left (on pole)
    ("L", 40.0, 8.0),                            # top-right
    ("Q", 33.0, 14.0, 40.0, 20.0),               # quadratic Bezier (control, end) — wind pinch
    ("L", 15.0, 22.0),                           # bottom-left (on pole; note x=15 to follow the lean)
    ("Z",),                                       # close back to start
]

BEZIER_STEPS = 24                                # samples along the wind-pinch curve


# ────────────────────────────────────────────────────────────────────
# Geometry helpers
# ────────────────────────────────────────────────────────────────────
def quadratic_bezier(p0, p1, p2, steps):
    """Sample a quadratic Bezier excluding the endpoints (callers add those)."""
    out = []
    for i in range(1, steps):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        out.append((x, y))
    return out


def flag_polygon_points(path):
    """Expand the path commands to a list of (x, y) vertices."""
    pts = []
    current = None
    start = None
    for cmd in path:
        if cmd[0] == "M":
            current = (cmd[1], cmd[2])
            start = current
            pts.append(current)
        elif cmd[0] == "L":
            current = (cmd[1], cmd[2])
            pts.append(current)
        elif cmd[0] == "Q":
            ctrl = (cmd[1], cmd[2])
            end = (cmd[3], cmd[4])
            pts.extend(quadratic_bezier(current, ctrl, end, BEZIER_STEPS))
            pts.append(end)
            current = end
        elif cmd[0] == "Z":
            # Polygons auto-close; no explicit point needed.
            pass
    return pts


# ────────────────────────────────────────────────────────────────────
# Renderer
# ────────────────────────────────────────────────────────────────────
def render(size: int, transparent: bool = False, padding_ratio: float = 0.10) -> Image.Image:
    """Render a square icon.

    `padding_ratio` is fraction of the canvas reserved as whitespace on each
    side. 0.10 = 10 % padding → content fills the middle 80 %.
    """
    bg = (0, 0, 0, 0) if transparent else BG_PAPER + (255,)
    img = Image.new("RGBA", (size, size), bg)

    # Render at a higher resolution then downscale — gives smooth edges without
    # needing PIL's (non-existent) line anti-aliasing.
    super_factor = 4 if size < 512 else 2
    super_size = size * super_factor
    super_img = Image.new("RGBA", (super_size, super_size), bg)
    draw = ImageDraw.Draw(super_img)

    pad = int(super_size * padding_ratio)
    content = super_size - 2 * pad
    scale = content / VIEWBOX

    def sx(x: float) -> float:
        return pad + x * scale

    def sy(y: float) -> float:
        return pad + y * scale

    pole_width = max(1, int(round(POLE_WIDTH_UNITS * scale)))

    # Pole: line + endpoint circles for round caps.
    (x1, y1), (x2, y2) = POLE
    draw.line(
        [(sx(x1), sy(y1)), (sx(x2), sy(y2))],
        fill=POLE_COBALT + (255,),
        width=pole_width,
    )
    r = pole_width / 2
    for (px, py) in [(sx(x1), sy(y1)), (sx(x2), sy(y2))]:
        draw.ellipse(
            [px - r, py - r, px + r, py + r],
            fill=POLE_COBALT + (255,),
        )

    # Flag: filled polygon.
    poly = [(sx(x), sy(y)) for (x, y) in flag_polygon_points(FLAG_PATH)]
    draw.polygon(poly, fill=FLAG_GREEN + (255,))

    # Downsample with high-quality resampling.
    return super_img.resize((size, size), Image.LANCZOS)


def main():
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "brand" / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = [
        (144, False, "praxys-icon-144.png"),
        (144, True, "praxys-icon-144-transparent.png"),
        (512, False, "praxys-icon-512.png"),
        (512, True, "praxys-icon-512-transparent.png"),
        (1024, False, "praxys-icon-1024.png"),
    ]

    for size, transparent, name in targets:
        img = render(size, transparent=transparent)
        path = out_dir / name
        img.save(path, "PNG", optimize=True)
        kb = path.stat().st_size / 1024
        print(f"  {name:40s} {size:4d}×{size:<4d}  {kb:6.1f} KB")

    print(f"\nWrote {len(targets)} PNGs to {out_dir}")


if __name__ == "__main__":
    main()
