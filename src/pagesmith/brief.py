"""The product brief: everything the studio knows about the product it is selling."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Palette slots, in the order they are shown, with what each colour is for.
COLOUR_ROLES = {
    "primary": "buttons, links and the main highlight",
    "accent": "secondary highlights, badges and icons",
    "background": "the page background",
    "surface": "cards, bands and panels",
    "text": "body copy and headings",
}


def normalise_hex(value: str) -> str:
    """'#ABC' / 'aabbcc' -> '#aabbcc'. Raises ValueError for anything else."""
    match = _HEX.match(value.strip())
    if not match:
        raise ValueError(f"'{value}' is not a hex colour such as #56cfe1")
    digits = match.group(1).lower()
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return f"#{digits}"


class PricingTier(BaseModel):
    name: str
    price: str
    includes: list[str] = Field(default_factory=list)


class Style(BaseModel):
    """Optional look and feel. Every field may be left out."""

    primary: str | None = None
    accent: str | None = None
    background: str | None = None
    surface: str | None = None
    text: str | None = None
    font: str = Field(default="", description="The feel of the type, e.g. 'rounded geometric sans like Poppins'.")
    notes: str = Field(default="", description="Layout and design notes, often read off a reference screenshot.")
    reference: str | None = Field(default=None, description="File name of the reference screenshot in the run folder.")

    @field_validator(*COLOUR_ROLES, mode="before")
    @classmethod
    def _colour(cls, value):
        if value in (None, ""):
            return None
        return normalise_hex(str(value))

    def palette(self) -> dict[str, str]:
        return {role: getattr(self, role) for role in COLOUR_ROLES if getattr(self, role)}

    def is_empty(self) -> bool:
        return not (self.palette() or self.font.strip() or self.notes.strip())

    def as_prompt(self) -> str:
        lines = ["Brand style (follow it closely; the audit checks the colours):"]
        palette = self.palette()
        if palette:
            lines.append("  Colours, define each as a CSS custom property in :root and use it for its role:")
            lines += [f"    --{role}: {hex_}   ({COLOUR_ROLES[role]})" for role, hex_ in palette.items()]
        if self.font.strip():
            lines.append(f"  Type: {self.font.strip()}. Web fonts are not allowed, so pick the closest system font stack.")
        if self.notes.strip():
            lines.append(f"  Design notes: {self.notes.strip()}")
        return "\n".join(lines)


class Brief(BaseModel):
    product: str
    tagline: str
    description: str
    features: list[str] = Field(min_length=3)
    pricing: list[PricingTier] = Field(default_factory=list)
    keywords: list[str] = Field(min_length=1, description="Search phrases every variant must cover.")
    audiences: list[str] = Field(min_length=1, description="Segments to build a dedicated variant for.")
    call_to_action: str = "Start free trial"
    tone: str = "confident, clear, no hype"
    style: Style | None = None

    @property
    def primary_keyword(self) -> str:
        return self.keywords[0]

    def as_prompt(self) -> str:
        """The brief rendered as plain text for a builder's task."""
        tiers = "\n".join(f"  - {t.name} ({t.price}): {', '.join(t.includes)}" for t in self.pricing) or "  (none)"
        features = "\n".join(f"  - {f}" for f in self.features)
        return (
            f"Product: {self.product}\n"
            f"Tagline: {self.tagline}\n"
            f"Description: {self.description}\n"
            f"Features:\n{features}\n"
            f"Pricing:\n{tiers}\n"
            f"Keywords to cover (primary first): {', '.join(self.keywords)}\n"
            f"Primary call to action: {self.call_to_action}\n"
            f"Tone: {self.tone}"
            + (f"\n{self.style.as_prompt()}" if self.style and not self.style.is_empty() else "")
        )


def load_brief(path: str | Path) -> Brief:
    return Brief.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
