import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from app.models.schemas import PFCData


def create_share_image(
    image_data: bytes,
    record_date: datetime,
    day_number: int | None,
    pfc: PFCData,
) -> bytes:
    """Overlay diet-record metadata on top of the uploaded meal photo."""
    with Image.open(io.BytesIO(image_data)) as source:
        image = source.convert("RGB")

    width, height = image.size
    padding = max(20, width // 24)
    panel_height = max(150, height // 4)
    panel_top = height - panel_height

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(
        [(0, panel_top), (width, height)],
        fill=(0, 0, 0, 170),
    )
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)

    title_font = _load_font(max(28, width // 18))
    body_font = _load_font(max(22, width // 24))
    small_font = _load_font(max(18, width // 30))

    date_label = record_date.strftime("%Y.%m.%d")
    day_label = f"Day {day_number}" if day_number else "Diet record"
    nutrition_label = f"{int(pfc.calories)} kcal"
    macro_label = f"P {pfc.protein:g}  F {pfc.fat:g}  C {pfc.carbs:g}"

    draw.text((padding, panel_top + padding), date_label, font=small_font, fill="white")
    draw.text((padding, panel_top + padding + small_font.size + 10), day_label, font=title_font, fill="white")
    draw.text((padding, panel_top + padding + small_font.size + title_font.size + 24), nutrition_label, font=body_font, fill="white")
    draw.text(
        (padding, panel_top + padding + small_font.size + title_font.size + body_font.size + 38),
        macro_label,
        font=body_font,
        fill="white",
    )

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
