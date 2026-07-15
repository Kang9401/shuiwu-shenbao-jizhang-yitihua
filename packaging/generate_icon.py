from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "packaging" / "assets"
PUBLIC_DIR = ROOT / "frontend" / "public"


def build_icon(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = int(size * 0.07)
    radius = int(size * 0.16)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill="#165DAB",
    )
    paper = (
        int(size * 0.25),
        int(size * 0.16),
        int(size * 0.72),
        int(size * 0.79),
    )
    draw.rounded_rectangle(paper, radius=int(size * 0.035), fill="#FFFFFF")
    fold = [
        (int(size * 0.57), int(size * 0.16)),
        (int(size * 0.72), int(size * 0.31)),
        (int(size * 0.57), int(size * 0.31)),
    ]
    draw.polygon(fold, fill="#DCEAF8")
    line_color = "#8FB4D9"
    line_width = int(size * 0.025)
    for y, length in ((0.40, 0.28), (0.49, 0.36), (0.58, 0.24)):
        draw.rounded_rectangle(
            (int(size * 0.33), int(size * y), int(size * (0.33 + length)), int(size * y) + line_width),
            radius=line_width // 2,
            fill=line_color,
        )
    badge = (int(size * 0.49), int(size * 0.54), int(size * 0.87), int(size * 0.92))
    draw.ellipse(badge, fill="#16865C", outline="#FFFFFF", width=int(size * 0.025))
    check = [
        (int(size * 0.58), int(size * 0.73)),
        (int(size * 0.66), int(size * 0.80)),
        (int(size * 0.79), int(size * 0.64)),
    ]
    draw.line(check, fill="#FFFFFF", width=int(size * 0.045), joint="curve")
    return image


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    icon = build_icon()
    icon.save(ASSET_DIR / "app-icon.png")
    icon.save(PUBLIC_DIR / "app-icon.png")
    icon.save(
        ASSET_DIR / "app.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()

