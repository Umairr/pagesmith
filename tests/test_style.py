import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from pagesmith.audit import audit_page
from pagesmith.brief import Brief, Style, normalise_hex
from pagesmith.style import merge, palette_from_image
from test_audit import BRIEF, good_page  # noqa: F401  (fixture)

STYLED = BRIEF.model_copy(update={"style": Style(primary="#56CFE1", surface="#eef8ec", text="222")})


def test_hex_normalisation():
    assert normalise_hex("#ABC") == "#aabbcc"
    assert normalise_hex("56cfe1") == "#56cfe1"
    with pytest.raises(ValueError):
        normalise_hex("teal")


def test_style_validates_colours():
    assert STYLED.style.palette() == {"primary": "#56cfe1", "surface": "#eef8ec", "text": "#222222"}
    with pytest.raises(ValueError):
        Style(primary="not-a-colour")


def test_prompt_carries_the_palette():
    text = STYLED.as_prompt()
    assert "--primary: #56cfe1" in text and "Brand style" in text
    assert "Brand style" not in BRIEF.as_prompt()


def test_brand_colours_are_scored(good_page: Path):  # noqa: F811
    unstyled = audit_page(good_page, BRIEF)
    assert unstyled.score == 100
    assert not any(c.id == "brand_colours" for c in unstyled.checks)

    report = audit_page(good_page, STYLED)
    brand = next(c for c in report.checks if c.id == "brand_colours")
    assert brand.earned == 0 and "primary #56cfe1" in brand.detail
    assert report.categories["content"]["max"] == 30

    (good_page / "styles.css").write_text(
        ":root{--primary:#56CFE1;--surface:#eef8ec;--text:#222}body{font-family:system-ui;color:var(--text)}",
        encoding="utf-8",
    )
    assert audit_page(good_page, STYLED).score == 100


def test_palette_from_image_finds_brand_colours():
    image = Image.new("RGB", (800, 600), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle([60, 60, 740, 540], fill="#eef8ec")
    draw.rectangle([200, 100, 600, 500], fill="#ffffff")
    draw.rectangle([220, 120, 580, 160], fill="#222222")
    draw.rectangle([220, 420, 580, 470], fill="#56cfe1")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    palette = palette_from_image(buffer.getvalue())
    assert palette["background"] == "#ffffff"
    assert palette["text"] == "#222222"
    assert abs(int(palette["primary"][1:3], 16) - 0x56) <= 4


def test_brief_style_wins_over_screenshot():
    merged = merge(Style(primary="#ff0000"), Style(primary="#00ff00", text="#111111", notes="airy"))
    assert merged.primary == "#ff0000" and merged.text == "#111111" and merged.notes == "airy"


def test_brief_round_trips_with_style():
    again = Brief.model_validate(STYLED.model_dump())
    assert again.style.primary == "#56cfe1"
