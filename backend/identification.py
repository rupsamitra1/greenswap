"""Normalize product identity and compare records without depending on an AI model."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse


def _plain(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized) or None


def _compact(value: str | None) -> str | None:
    plain = _plain(value)
    return plain.replace(" ", "") if plain else None


def valid_gtin(value: str | None) -> str | None:
    """Return a valid GTIN-8/12/13/14 or None, including check-digit validation."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) not in {8, 12, 13, 14}:
        return None
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(digit) * (3 if index % 2 == 0 else 1)
                for index, digit in enumerate(reversed(body)))
    return digits if (10 - total % 10) % 10 == check else None


def asin_from_url(url: str | None) -> str | None:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", url or "", re.I)
    return match.group(1).upper() if match else None


def _asin(value: str | None, url: str | None) -> str | None:
    candidate = (value or asin_from_url(url) or "").strip().upper()
    return candidate if re.fullmatch(r"[A-Z0-9]{10}", candidate) else None


def _variant_tokens(title: str) -> tuple[str, ...]:
    values = re.findall(r"\b\d+(?:\.\d+)?\s*(?:fl\s*oz|oz|ml|liters?|l|packs?|counts?|ct)\b", title.lower())
    return tuple(sorted(re.sub(r"\s+", "", value) for value in values))


@dataclass(frozen=True)
class ProductIdentity:
    title: str
    normalized_title: str
    brand: str | None
    retailer: str | None
    asin: str | None
    gtin: str | None
    model_number: str | None
    sku: str | None
    variant_tokens: tuple[str, ...]
    identity_key: str
    identity_strength: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class IdentityMatch:
    score: int
    level: str
    reasons: tuple[str, ...]


def identify_product(product: dict) -> ProductIdentity:
    title = str(product.get("title") or "").strip()
    if not title:
        raise ValueError("Product title is required")
    url = str(product.get("url") or "") or None
    retailer = _plain(str(product.get("retailer") or ""))
    if not retailer and url:
        retailer = _plain(urlparse(url).hostname)
    brand = _plain(str(product.get("brand") or ""))
    asin = _asin(product.get("asin"), url)
    supplied_gtin = product.get("gtin")
    gtin = valid_gtin(str(supplied_gtin)) if supplied_gtin else None
    model_number = _compact(product.get("model_number"))
    sku = _compact(product.get("sku"))
    normalized_title = _plain(title) or ""
    warnings = []
    if supplied_gtin and not gtin:
        warnings.append("Supplied GTIN failed check-digit validation")

    if gtin:
        raw_key, strength = f"gtin:{gtin}", "exact"
    elif asin and retailer == "amazon":
        raw_key, strength = f"amazon:asin:{asin}", "exact"
    elif brand and model_number:
        raw_key, strength = f"brand-model:{brand}:{model_number}", "strong"
    elif retailer and brand and sku:
        raw_key, strength = f"retailer-sku:{retailer}:{brand}:{sku}", "strong"
    else:
        raw_key, strength = f"title:{brand or ''}:{normalized_title}", "fallback"
        warnings.append("No exact product identifier; using normalized brand and title")
    identity_key = hashlib.sha256(raw_key.encode()).hexdigest()[:32]
    return ProductIdentity(title, normalized_title, brand, retailer, asin, gtin,
                           model_number, sku, _variant_tokens(title), identity_key,
                           strength, tuple(warnings))


def compare_identities(left: ProductIdentity, right: ProductIdentity) -> IdentityMatch:
    """Compare two identities, failing closed on contradictory strong identifiers."""
    if left.gtin and right.gtin:
        return IdentityMatch(100 if left.gtin == right.gtin else 0,
                             "exact" if left.gtin == right.gtin else "conflict",
                             ("Matching GTIN" if left.gtin == right.gtin else "Conflicting GTIN",))
    if left.asin and right.asin and left.retailer == right.retailer == "amazon":
        return IdentityMatch(100 if left.asin == right.asin else 0,
                             "exact" if left.asin == right.asin else "conflict",
                             ("Matching Amazon ASIN" if left.asin == right.asin else "Conflicting Amazon ASIN",))
    if left.brand and right.brand and left.brand != right.brand:
        return IdentityMatch(0, "conflict", ("Conflicting brand",))
    if left.model_number and right.model_number:
        if left.model_number != right.model_number:
            return IdentityMatch(0, "conflict", ("Conflicting model number",))
        if left.brand == right.brand:
            return IdentityMatch(96, "strong", ("Matching brand and model number",))
    if left.sku and right.sku and left.retailer == right.retailer and left.brand == right.brand:
        if left.sku == right.sku:
            return IdentityMatch(90, "strong", ("Matching retailer, brand, and SKU",))
    if left.variant_tokens and right.variant_tokens and left.variant_tokens != right.variant_tokens:
        return IdentityMatch(20, "weak", ("Product sizes or quantities differ",))
    left_tokens, right_tokens = set(left.normalized_title.split()), set(right.normalized_title.split())
    similarity = len(left_tokens & right_tokens) / len(left_tokens | right_tokens) if left_tokens | right_tokens else 0
    score = round(similarity * 70 + (20 if left.brand and left.brand == right.brand else 0))
    level = "strong" if score >= 85 else "possible" if score >= 65 else "weak"
    return IdentityMatch(min(score, 89), level, ("Normalized title similarity",))
