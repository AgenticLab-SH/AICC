import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def generate_cdp_whale_icon():
    # Base size for the ICO
    size = 256

    # Try to load the original Whale icon if available, or just create a new base
    # Whale icon is usually a circular or teardrop shape. We'll make a nice base.
    base = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(base)

    # Draw a circle for the base (Whale-like color)
    draw.ellipse((10, 10, 246, 246), fill="#00D2A0") # Whale's mint/green color
    draw.ellipse((40, 40, 216, 216), fill="#FFFFFF") # Inner white

    # Draw the large "C" overlay
    # Find a good font or just draw it manually if font is unavailable
    try:
        font = ImageFont.truetype("arialbd.ttf", 180)
    except:
        font = ImageFont.load_default()

    # Draw "C" in dark blue
    text = "C"
    # Get bounding box using textbbox
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    x = (size - w) / 2
    y = (size - h) / 2 - 20 # adjust visually

    draw.text((x, y), text, fill="#00008B", font=font) # Dark Blue

    # Save as ICO with multiple sizes
    out_path = Path(__file__).resolve().parents[1] / "cdp_whale.ico"
    base.save(out_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print(f"Icon generated at {out_path}")

if __name__ == "__main__":
    generate_cdp_whale_icon()
