"""Generate macOS menu bar template icons for Ghost Typer.

Creates 32x32 (for @2x Retina) black-on-transparent PNGs.
macOS template images: black pixels become the icon, alpha = transparency.
"""

from PIL import Image, ImageDraw, ImageFont
import os

SIZE = 32  # @2x for Retina (renders at 16pt)
OUT = os.path.join(os.path.dirname(__file__), "icons")
os.makedirs(OUT, exist_ok=True)


def new_image():
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))


def draw_clipboard_base(draw, fill=(0, 0, 0, 255)):
    """Draw a clipboard shape: rounded rectangle with a clip tab at top."""
    # Main board body
    draw.rounded_rectangle([4, 6, 27, 30], radius=2, outline=fill, width=2)
    # Clip tab at top center
    draw.rounded_rectangle([10, 2, 21, 9], radius=2, outline=fill, width=2, fill=fill)
    # Small hole in clip
    draw.rounded_rectangle([13, 3, 18, 7], radius=1, fill=(0, 0, 0, 0))


def draw_clipboard_filled(draw, fill=(0, 0, 0, 255)):
    """Draw a filled clipboard shape."""
    # Main board body
    draw.rounded_rectangle([4, 6, 27, 30], radius=2, fill=fill)
    # Clip tab at top center
    draw.rounded_rectangle([10, 2, 21, 9], radius=2, fill=fill)
    # Small hole in clip
    draw.rounded_rectangle([13, 3, 18, 7], radius=1, fill=(0, 0, 0, 0))


# ── OFF: outline clipboard (empty, inactive) ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_base(d)
img.save(os.path.join(OUT, "clipboard_off.png"))
print("Created clipboard_off.png")

# ── IDLE (ON): filled clipboard with big bold checkmark ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_filled(d)
white = (255, 255, 255, 255)
# Big thick checkmark - short leg then long leg
d.line([8, 19, 13, 26], fill=white, width=3)
d.line([13, 26, 24, 12], fill=white, width=3)
img.save(os.path.join(OUT, "clipboard_on.png"))
print("Created clipboard_on.png")

# ── TYPING: filled clipboard with pen/writing indicator ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_filled(d)
# Draw three horizontal lines (like text being written) in white
white = (255, 255, 255, 255)
d.line([8, 14, 23, 14], fill=white, width=2)
d.line([8, 19, 20, 19], fill=white, width=2)
d.line([8, 24, 16, 24], fill=white, width=2)
img.save(os.path.join(OUT, "clipboard_typing.png"))
print("Created clipboard_typing.png")

# ── TYPING animation frame 2: lines growing ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_filled(d)
white = (255, 255, 255, 255)
d.line([8, 14, 23, 14], fill=white, width=2)
d.line([8, 19, 23, 19], fill=white, width=2)
d.line([8, 24, 12, 24], fill=white, width=2)
img.save(os.path.join(OUT, "clipboard_typing2.png"))
print("Created clipboard_typing2.png")

# ── TYPING animation frame 3 ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_filled(d)
white = (255, 255, 255, 255)
d.line([8, 14, 23, 14], fill=white, width=2)
d.line([8, 19, 23, 19], fill=white, width=2)
d.line([8, 24, 23, 24], fill=white, width=2)
img.save(os.path.join(OUT, "clipboard_typing3.png"))
print("Created clipboard_typing3.png")

# ── PAUSED: filled clipboard with pause bars ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_filled(d)
white = (255, 255, 255, 255)
d.rectangle([11, 14, 14, 25], fill=white)
d.rectangle([17, 14, 20, 25], fill=white)
img.save(os.path.join(OUT, "clipboard_paused.png"))
print("Created clipboard_paused.png")

# ── PLANNING: filled clipboard with dots (thinking) ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_filled(d)
white = (255, 255, 255, 255)
d.ellipse([9, 17, 13, 21], fill=white)
d.ellipse([15, 17, 19, 21], fill=white)
d.ellipse([21, 17, 25, 21], fill=white)
img.save(os.path.join(OUT, "clipboard_planning.png"))
print("Created clipboard_planning.png")

# ── VERIFYING: filled clipboard with magnifying glass ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_filled(d)
white = (255, 255, 255, 255)
# Small magnifying glass circle
d.ellipse([10, 13, 20, 23], outline=white, width=2)
# Handle
d.line([19, 22, 24, 27], fill=white, width=2)
img.save(os.path.join(OUT, "clipboard_verifying.png"))
print("Created clipboard_verifying.png")

# ── STAGED: outline clipboard with arrow down (content captured, waiting for Cmd+V) ──
img = new_image()
d = ImageDraw.Draw(img)
draw_clipboard_base(d)
black = (0, 0, 0, 255)
# Down arrow inside
d.line([15, 13, 15, 24], fill=black, width=2)
d.line([11, 20, 15, 25], fill=black, width=2)
d.line([19, 20, 15, 25], fill=black, width=2)
img.save(os.path.join(OUT, "clipboard_staged.png"))
print("Created clipboard_staged.png")

print("\nAll icons generated in", OUT)
