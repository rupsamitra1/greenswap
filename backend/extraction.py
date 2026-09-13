"""Extract conservative, source-linked facts from retailer listing text."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

try:
    from backend.scoring import Evidence
except ModuleNotFoundError:
    from scoring import Evidence

MATERIAL_PATTERNS = {
    "polyethylene terephthalate (PET)": (r"\bpet plastic\b", r"\bpet\b"),
    "stainless steel": (r"\bstainless steel\b",),
    "borosilicate glass": (r"\bborosilicate glass\b",),
    "glass": (r"\bglass\b",),
    "plastic": (r"\bplastic\b",),
}
INGREDIENT_PATTERNS = {
    "added fragrance": (r"\badded fragrance\b", r"\bfragrance\b"),
    "synthetic surfactants": (r"\bsynthetic surfactants?\b",),
}


@dataclass(frozen=True)
class NormalizedFact:
    kind: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionResult:
    category: str
    facts: tuple[NormalizedFact, ...]
    evidence: tuple[Evidence, ...]
    warnings: tuple[str, ...]


def _evidence_id(index: int, claim: str) -> str:
    digest = hashlib.sha256(claim.encode()).hexdigest()[:8]
    return f"listing-{index}-{digest}"


def _category(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(dish soap|detergent|cleaner|laundry|cleaning)\b", lowered):
        return "cleaning"
    if re.search(r"\b(water bottles?|tumblers?|drink bottles?|cups?|mugs?)\b", lowered):
        return "bottles"
    if re.search(r"\b(shampoo|toothpaste|lotion|deodorant|razor)\b", lowered):
        return "personal_care"
    if re.search(r"\b(food wrap|foil|food bags?|utensils?|plates?)\b", lowered):
        return "kitchen"
    return "other"


def extract_listing_facts(product: dict) -> ExtractionResult:
    """Return facts explicitly stated in the title/bullets; make no safety judgment."""
    title = str(product.get("title") or "").strip()
    bullets = [str(item).strip() for item in (product.get("bullets") or []) if str(item).strip()]
    if not title:
        raise ValueError("Product title is required")
    statements = [title, *bullets]
    url = str(product.get("url") or "") or None
    evidence = tuple(Evidence(_evidence_id(i, claim), claim, "retailer_documented",
                              "Retailer listing", url)
                     for i, claim in enumerate(statements))
    facts: dict[tuple[str, str], list[str]] = {}

    def add(kind: str, value: str, evidence_id: str):
        facts.setdefault((kind, value), []).append(evidence_id)

    for statement, item in zip(statements, evidence):
        lowered = statement.lower()
        for material, patterns in MATERIAL_PATTERNS.items():
            if any(re.search(pattern, lowered) for pattern in patterns):
                add("material", material, item.id)
        for ingredient, patterns in INGREDIENT_PATTERNS.items():
            if any(re.search(pattern, lowered) for pattern in patterns):
                add("ingredient_mention", ingredient, item.id)
        if re.search(r"\bsingle[- ]use\b", lowered):
            add("use_pattern", "single_use", item.id)
        if re.search(r"\breusable\b", lowered):
            add("use_pattern", "reusable", item.id)
        if re.search(r"\brefill(?:able| pouch| pack|s)?\b", lowered):
            add("product_format", "refill", item.id)
        if re.search(r"\bconcentrat(?:e|ed)\b", lowered):
            add("product_format", "concentrate", item.id)
        if re.search(r"\bshrink[- ]wrap(?:ped)?\b", lowered):
            add("packaging", "plastic_shrink_wrap", item.id)
        if re.search(r"\bplastic[- ]free\b", lowered):
            add("packaging_claim", "plastic_free", item.id)
        if re.search(r"\bplant[- ]based\b|\bnatural\b|\beco[- ]friendly\b", lowered):
            add("marketing_claim", "unverified_environmental_claim", item.id)

    normalized = tuple(NormalizedFact(kind, value, tuple(dict.fromkeys(refs)))
                       for (kind, value), refs in sorted(facts.items()))
    warnings = []
    if not normalized:
        warnings.append("Listing contains no supported material, ingredient, packaging, or reuse facts")
    if any(fact.kind == "marketing_claim" for fact in normalized):
        warnings.append("Environmental marketing language was recorded but not treated as proof")
    values = {(fact.kind, fact.value) for fact in normalized}
    if {("use_pattern", "single_use"), ("use_pattern", "reusable")} <= values:
        warnings.append("Listing contains conflicting use-pattern claims")
    return ExtractionResult(_category(" ".join(statements)), normalized, evidence, tuple(warnings))
