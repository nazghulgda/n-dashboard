# Generates the application icons from the geometry of assets/app.svg
#
#   assets/app.ico          Windows (16–256 px inside)
#   assets/png/app-N.png    Linux and macOS (16, 24, 32, 48, 64, 128, 256, 512)
#
# Run after changing the icon:   .venv/bin/python tools/make_icons.py
# (needs Pillow: pip install -r requirements-dev.txt)

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# (x, y, width, height, corner radius, colour) on the 1024 x 1024 canvas of app.svg
SHAPES = [
    (32,  32,  960, 960, 200, "#1a56db"),
    (152, 212, 200, 600, 48,  "#ffffff"),
    (412, 212, 200, 440, 48,  "#ffffff"),
    (672, 212, 200, 280, 48,  "#ffffff"),
    (152, 732, 200, 80,  40,  "#f5a623"),
]


def render(size: int) -> Image.Image:
    """Draws the icon 4x larger and scales it down, which gives smooth edges."""
    big = size * 4
    scale = big / 1024
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for x, y, w, h, r, colour in SHAPES:
        box = [x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1]
        draw.rounded_rectangle(box, radius=r * scale, fill=colour)
    return img.resize((size, size), Image.LANCZOS)


def main():
    png_dir = ASSETS / "png"
    png_dir.mkdir(parents=True, exist_ok=True)
    for size in PNG_SIZES:
        render(size).save(png_dir / f"app-{size}.png")
    render(256).save(ASSETS / "app.ico", sizes=[(s, s) for s in ICO_SIZES])
    print(f"Icons written to {ASSETS}")


if __name__ == "__main__":
    main()
