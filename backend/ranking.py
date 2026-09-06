"""Eligibility and ranking policy, kept separate from environmental scoring."""
from __future__ import annotations

ECO_IMPROVEMENT = 10
EQUIVALENCE_BAND = 4
AFFILIATE_BOOST = 3
MIN_CONFIDENCE = 55


def rank_candidates(original: dict, candidates: list[dict], price_ceiling=True) -> dict:
    original_score = original["analysis"].get("overall_score")
    original_price = original.get("price")
    category = original.get("category")
    rejected = []
    eligible = []
    for candidate in candidates:
        score = candidate["analysis"].get("overall_score")
        reasons = []
        if candidate.get("category") != category:
            reasons.append("different category")
        if candidate.get("available", True) is False:
            reasons.append("not currently available")
        if score is None:
            reasons.append("incomplete environmental evidence")
        if candidate["analysis"].get("confidence_score", 0) < MIN_CONFIDENCE:
            reasons.append("evidence confidence too low")
        if original_score is None:
            reasons.append("viewed product lacks a comparable score")
        elif score is not None and score < original_score + ECO_IMPROVEMENT:
            reasons.append(f"less than {ECO_IMPROVEMENT} points better")
        if price_ceiling and original_price and candidate.get("price", 0) > original_price:
            reasons.append("costs more than the viewed product")
        if reasons:
            rejected.append({"id": candidate["id"], "reasons": reasons})
        else:
            eligible.append(candidate)

    best_eco = max((c["analysis"]["overall_score"] for c in eligible), default=None)
    for candidate in eligible:
        eco = candidate["analysis"]["overall_score"]
        in_band = best_eco is not None and best_eco - eco <= EQUIVALENCE_BAND
        boost = AFFILIATE_BOOST if candidate.get("affiliate") and in_band else 0
        candidate["affiliate_boost"] = boost
        candidate["recommendation_score"] = eco + boost
        candidate["affiliate_eligible_band"] = in_band

    environmental_order = sorted(eligible, key=lambda c: (-c["analysis"]["overall_score"], c.get("price") or 0))
    ranked = sorted(eligible, key=lambda c: (-c["recommendation_score"], -c["affiliate_boost"], -(c["analysis"]["overall_score"]), c.get("price") or 0))
    influenced = [c["id"] for c in environmental_order] != [c["id"] for c in ranked]
    for index, candidate in enumerate(ranked):
        candidate["affiliate_influenced_order"] = influenced and candidate.get("affiliate_boost", 0) > 0
        candidate["ranking_explanation"] = (
            "Partner preference influenced ordering within the 4-point environmental equivalence band."
            if candidate["affiliate_influenced_order"] else
            "Ranked by environmental improvement, then price; no partner preference affected this position."
        )
        candidate["rank"] = index + 1
    return {
        "candidates": ranked,
        "rejected": rejected,
        "keep_current": not ranked and original_score is not None,
        "affiliate_influenced": influenced,
        "policy": {
            "minimum_eco_improvement": ECO_IMPROVEMENT,
            "affiliate_equivalence_band": EQUIVALENCE_BAND,
            "maximum_affiliate_boost": AFFILIATE_BOOST,
            "commission_rate_used": False,
            "price_ceiling_enforced": bool(price_ceiling and original_price),
        },
    }
