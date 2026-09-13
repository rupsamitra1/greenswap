"""Rules-based product analysis. No model, no network, no quota.

This is what answers when the AI is unavailable -- out of quota, key missing,
provider down. It reads the same scraped text the model would read and applies
the same rubric, using explicit signals rather than inference.

It is deliberately conservative. A heuristic that guessed confidently would be
worse than useless here, because the whole product rests on shoppers being able
to tell what is established from what is estimated. So it reports which signals
it actually found, and stays near the middle of the range when it finds none.
"""

import re

# Signals are ordered worst-to-best within each group. Weights are small on
# purpose: several weak hints should not add up to a strong claim.
NEGATIVE = [
    (r"\b(single[- ]use|disposable|one[- ]time use|throw[- ]?away)\b", -22, "single-use"),
    (r"\b(styrofoam|polystyrene|expanded polystyrene|eps foam)\b", -16, "polystyrene"),
    (r"\b(pet|pete|polypropylene|polyethylene|hdpe|ldpe|pvc)\b", -10, "petroleum plastic"),
    (r"\bplastic\b", -8, "plastic"),
    (r"\b(bleach|ammonia|phosphate|paraben|phthalate|triclosan)\b", -10, "harsh chemistry"),
    (r"\b(individually wrapped|shrink[- ]wrapped)\b", -6, "extra packaging"),
]

POSITIVE = [
    (r"\b(reusable|refillable|refill)\b", 20, "reusable or refillable"),
    (r"\b(stainless steel|borosilicate|glass|bamboo|cast iron)\b", 16, "durable material"),
    (r"\b(plastic[- ]free|zero[- ]waste|package[- ]free)\b", 16, "plastic-free"),
    (r"\b(recycled|post[- ]consumer|reclaimed)\b", 14, "recycled content"),
    (r"\b(compostable|biodegradable)\b", 10, "compostable"),
    (r"\b(concentrate|concentrated|tablet|bar form)\b", 10, "concentrated"),
    (r"\b(plant[- ]based|plant[- ]derived)\b", 8, "plant-derived"),
    (r"\b(bpa[- ]free|phosphate[- ]free|dye[- ]free|fragrance[- ]free)\b", 5, "fewer additives"),
]

# Rubric ceilings. A product that says "single-use" cannot climb out of the
# bottom band by also saying "recycled" -- the disposal dominates.
SINGLE_USE_CEILING = 30
DURABLE_FLOOR = 55

# Nobody buys fifty cups to keep. A bulk pack of drinkware or tableware is
# disposable whether or not the listing uses the word, and without this a
# "100-Pack Plastic Cups" reads as merely "plastic" and scores mid-range --
# which is how disposable cups end up recommended as the greener swap for
# disposable cups.
BULK_COUNT = re.compile(
    r"\b(\d{2,4})\s*[- ]?(?:pack|pk|count|ct|pcs|pieces|piece)\b|"
    r"\bset of\s+(\d{2,4})\b"
)
BULK_ITEMS = re.compile(
    r"\b(cups?|plates?|bowls?|forks?|spoons?|knives|cutlery|utensils?|straws?|"
    r"napkins?|bottles?|bags?|wraps?|liners?|towels?|wipes?)\b"
)
BULK_THRESHOLD = 20


def analyze_text(text: str) -> dict:
    """Score a product from its listing text alone.

    Returns the score, the materials implied, and the signals that produced it,
    so the reason given to a shopper can name its own evidence.
    """
    lowered = f" {(text or '').lower()} "

    score = 50
    found_negative, found_positive, materials = [], [], []

    for pattern, weight, label in NEGATIVE:
        if re.search(pattern, lowered):
            score += weight
            found_negative.append(label)
            materials.append(label)

    for pattern, weight, label in POSITIVE:
        if re.search(pattern, lowered):
            score += weight
            found_positive.append(label)
            materials.append(label)

    # Infer disposability from quantity when the wording does not state it.
    bulk = BULK_COUNT.search(lowered)
    if bulk and BULK_ITEMS.search(lowered):
        count = int(next(g for g in bulk.groups() if g))
        if count >= BULK_THRESHOLD:
            score -= 22
            if "single-use" not in found_negative:
                found_negative.append("sold in disposable quantities")
                materials.append("single-use")

    single_use = ("single-use" in found_negative
                  or "sold in disposable quantities" in found_negative)
    durable = "durable material" in found_positive or "reusable or refillable" in found_positive

    if single_use:
        score = min(score, SINGLE_USE_CEILING)
    elif durable:
        score = max(score, DURABLE_FLOOR)

    score = max(0, min(100, score))

    return {
        "eco_score": score,
        "materials": materials[:6] or ["not stated"],
        "negative": found_negative,
        "positive": found_positive,
        "confident": bool(found_negative or found_positive),
    }


def explain(result: dict) -> str:
    """A sentence that says what was found, and admits when nothing was."""
    if not result["confident"]:
        return (
            "The listing does not describe its materials or packaging, so this "
            "is a cautious middle estimate rather than a judgement."
        )

    parts = []
    if result["negative"]:
        parts.append("described as " + ", ".join(result["negative"][:3]))
    if result["positive"]:
        parts.append("but also " + ", ".join(result["positive"][:3]) if parts
                     else "described as " + ", ".join(result["positive"][:3]))

    return (
        "Scored from the listing text: " + "; ".join(parts) +
        ". No AI analysis was used, so this reads wording rather than verifying it."
    )


# Recognised product types. An alternative must be the same kind of thing:
# reusable straws are a fine product and a useless answer to "I am buying cups".
PRODUCT_TYPES = {
    "cup": ("cup", "cups", "tumbler", "tumblers", "mug", "mugs", "glass", "glasses"),
    "bottle": ("bottle", "bottles", "flask", "canteen"),
    "straw": ("straw", "straws"),
    "plate": ("plate", "plates", "bowl", "bowls"),
    "cutlery": ("fork", "forks", "spoon", "spoons", "knife", "knives", "cutlery", "utensil", "utensils"),
    "soap": ("soap", "detergent", "cleanser", "wash"),
    "towel": ("towel", "towels", "napkin", "napkins", "wipe", "wipes"),
    "bag": ("bag", "bags", "wrap", "wraps", "liner", "liners"),
}


def product_type(text: str) -> str | None:
    """The kind of thing a listing is, when we can tell."""
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    best = None
    for kind, terms in PRODUCT_TYPES.items():
        if words & set(terms):
            # A straw mentioned alongside cups should not beat the cups.
            if best is None or kind == "cup":
                best = kind
    return best


def same_product_type(viewed: str, candidate: str) -> bool:
    """True unless we positively know these are different kinds of product."""
    a, b = product_type(viewed), product_type(candidate)
    if a is None or b is None:
        return True  # unknown is not a reason to reject
    return a == b


def score_listing(listing: dict) -> dict:
    """Score one search result. Only its name is available, so be careful."""
    result = analyze_text(listing.get("name", ""))
    return {
        "id": "rule-" + str(listing.get("url", "")).rstrip("/").rsplit("/", 1)[-1],
        "name": listing["name"],
        "price": listing.get("price"),
        "url": listing.get("url"),
        "eco_score": result["eco_score"],
        "materials": result["materials"],
        "reason": explain(result),
        "trust": "heuristic",
        "certification": None,
        "source": listing.get("source", "live"),
        "confident": result["confident"],
    }


def rank_listings(listings: list[dict], min_score: int,
                  max_price: float | None, limit: int = 3) -> list[dict]:
    """Pick greener listings without a model.

    Only listings whose text actually says something greener are eligible --
    with no model to reason about an ambiguous title, a name that reveals
    nothing is not evidence of anything.
    """
    scored = []
    for listing in listings or []:
        if listing.get("price") is None:
            continue
        if max_price is not None and listing["price"] > max_price:
            continue
        candidate = score_listing(listing)
        if not candidate["confident"]:
            continue  # a title revealing nothing is not evidence of anything
        if candidate["eco_score"] < min_score:
            continue
        scored.append(candidate)

    scored.sort(key=lambda c: (-c["eco_score"], c.get("price") or 0))
    return scored[:limit]
