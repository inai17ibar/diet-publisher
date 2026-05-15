import io
from datetime import datetime

from PIL import Image

from app.models.schemas import PFCData
from app.services.image_editor import create_share_image


def test_create_share_image_returns_jpeg_bytes():
    source = io.BytesIO()
    Image.new("RGB", (600, 600), color="white").save(source, format="JPEG")

    result = create_share_image(
        source.getvalue(),
        record_date=datetime(2026, 5, 14),
        day_number=329,
        pfc=PFCData(protein=120, fat=45, carbs=160, calories=1530),
    )

    image = Image.open(io.BytesIO(result))
    assert image.format == "JPEG"
    assert image.size == (600, 600)
