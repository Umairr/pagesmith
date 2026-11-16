"""Reading a look and feel off a reference screenshot.

Two passes:

1. ``palette_from_image`` quantises the image with Pillow and assigns the
   dominant colours to roles (background, surface, text, primary, accent).
   Deterministic, free and works offline.
2. ``describe_reference`` asks the lead's model to look at the screenshot and
   return the palette plus short design notes (layout, spacing, button shapes,
   type). Its colours win where they are valid; the Pillow palette fills gaps,
   and is all you get when the model call fails.
"""

from __future__ import annotations

import base64
import colorsys
import io
import json
import re

from PIL import Image

from pagesmith.brief import COLOUR_ROLES, Style, normalise_hex

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _hls(rgb):
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def _distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def load_image(data: bytes) -> Image.Image:
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("The screenshot is larger than 8 MB.")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # Pillow raises a handful of types for bad input
        raise ValueError("That file is not an image Pillow can read (use PNG, JPG or WebP).") from exc
    return image.convert("RGB")


def dominant_colours(data: bytes) -> list[tuple[int, tuple[int, int, int]]]:
    """(pixel count, rgb) for the screenshot's main colours, most common first."""
    image = load_image(data)
    image.thumbnail((720, 720))
    quantised = image.quantize(colors=32, method=Image.Quantize.FASTOCTREE)
    raw = quantised.getpalette()[: 32 * 3]
    # Quantising averages colours slightly; snap each cluster back to the most common real
    # pixel colour near it, so flat UI colours come out exact (#56cfe1, not #55cfe1).
    exact = sorted(image.getcolors(maxcolors=image.width * image.height) or [], reverse=True)[:4000]
    out = []
    for count, index in sorted(quantised.getcolors(), reverse=True):
        rgb = tuple(raw[index * 3: index * 3 + 3])
        near = next((c for n, c in exact if _distance(c, rgb) <= 14), rgb)
        out.append((count, tuple(near)))
    return out


def palette_from_image(data: bytes, colours: list | None = None) -> dict[str, str]:
    """Assign the screenshot's dominant colours to palette roles."""
    colours = colours or dominant_colours(data)
    total = sum(c for c, _ in colours)

    lights = [rgb for c, rgb in colours if _hls(rgb)[1] > 0.88]
    # Body text: the most common clearly dark colour (anti-aliasing makes the rest grey).
    darks = [rgb for c, rgb in colours if _hls(rgb)[1] < 0.4 and c / total > 0.002]
    # Brand colours: saturated, mid-light, and covering a real (if small) share of the page.
    vivid = sorted(
        ((_hls(rgb)[2] * (c / total) ** 0.5, rgb) for c, rgb in colours
         if _hls(rgb)[2] > 0.45 and 0.25 < _hls(rgb)[1] < 0.8 and c / total > 0.002),
        reverse=True,
    )
    vivid = [rgb for _, rgb in vivid]

    palette: dict[str, str] = {}
    if lights:
        palette["background"] = _hex(lights[0])
        surface = next((rgb for rgb in lights[1:] if _distance(rgb, lights[0]) > 6), None)
        if surface:
            palette["surface"] = _hex(surface)
    if darks:
        palette["text"] = _hex(darks[0])
    if vivid:
        palette["primary"] = _hex(vivid[0])
        accent = next((rgb for rgb in vivid[1:] if abs(_hls(rgb)[0] - _hls(vivid[0])[0]) > 0.08), None)
        if accent:
            palette["accent"] = _hex(accent)
    return palette


_PROMPT = """\
You are a web designer. Study this screenshot of a web page and describe its look and feel
so another designer can build a new page in the same visual style (not a copy of its content).

Reply with JSON only, no prose, in exactly this shape:
{
  "primary": "#rrggbb",      // main button / link colour
  "accent": "#rrggbb",       // second highlight colour, or null
  "background": "#rrggbb",   // page background
  "surface": "#rrggbb",      // cards, bands or panels, or null
  "text": "#rrggbb",         // body text
  "font": "...",             // the feel of the typeface, e.g. "rounded geometric sans like Poppins"
  "notes": "..."             // at most 90 words: layout, spacing, corner radius, button style,
                             // header and footer treatment, imagery and icon style
}
"""


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON in the reply")
    cleaned = re.sub(r"//[^\n]*", "", match.group(0))
    return json.loads(cleaned)


def describe_reference(data: bytes, mime: str = "image/png") -> tuple[Style, str]:
    """Return a Style for the screenshot and where it came from ("model" or "palette")."""
    from pagesmith import config

    colours = dominant_colours(data)
    palette = palette_from_image(data, colours)
    spec = config.ORCHESTRATOR_SPEC
    try:
        import litellm

        # Downscale before sending: fewer tokens, same colours.
        image = load_image(data)
        image.thumbnail((1600, 1600))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
        extra = {"api_base": spec.base_url} if spec.provider.name == "custom" else {}
        reply = litellm.completion(
            model=spec.litellm_id(),
            api_key=spec.require_key(),
            messages=[{"role": "user", "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": url}},
            ]}],
            max_tokens=1500,
            timeout=90,
            **extra,
        )
        found = _parse_json(reply.choices[0].message.content or "")
    except Exception:  # no vision support, no credit, bad JSON: fall back to the pixels
        return Style(**palette), "palette"

    # Models read roles well but round colours; snap each to the nearest real pixel colour.
    total = sum(c for c, _ in colours)
    real = [rgb for c, rgb in colours if c / total > 0.001]

    def snap(hex_: str) -> str:
        rgb = tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))
        nearest = min(real, key=lambda r: _distance(r, rgb), default=None)
        return _hex(nearest) if nearest and _distance(nearest, rgb) < 24 else hex_

    fields: dict = {}
    for role in COLOUR_ROLES:
        value = found.get(role)
        try:
            fields[role] = snap(normalise_hex(value)) if value else palette.get(role)
        except ValueError:
            fields[role] = palette.get(role)
    fields["font"] = str(found.get("font") or "")[:120]
    fields["notes"] = str(found.get("notes") or "")[:700]
    return Style(**fields), "model"


def decode_data_url(value: str) -> tuple[bytes, str]:
    """'data:image/png;base64,...' -> (bytes, mime)."""
    match = re.match(r"^data:(image/[a-z0-9.+-]+);base64,(.+)$", value.strip(), re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("Expected a base64 image data URL.")
    data = base64.b64decode(match.group(2), validate=False)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("The screenshot is larger than 8 MB.")
    return data, match.group(1).lower()


EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp"}


def merge(explicit, found: Style) -> Style:
    """Fields set in the brief win; the screenshot fills in the rest."""
    if not explicit:
        return found
    mine = {k: v for k, v in explicit.model_dump().items() if v not in (None, "")}
    return found.model_copy(update=mine)


def guess_mime(path: str) -> str:
    suffix = path.lower().rsplit(".", 1)[-1]
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(suffix, "image/png")
