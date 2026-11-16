"""The product brief: everything the studio knows about the product it is selling."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class PricingTier(BaseModel):
    name: str
    price: str
    includes: list[str] = Field(default_factory=list)


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
        )


def load_brief(path: str | Path) -> Brief:
    return Brief.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
