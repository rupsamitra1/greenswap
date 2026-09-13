"""One evaluation path for the viewed product and every alternative."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

try:
    from backend.demo_catalog import find_profile
    from backend.extraction import extract_listing_facts
    from backend.identification import identify_product
    from backend.reference_data import reference_for
    from backend.scoring import Assessment, Evidence, METHOD_VERSION, score_product
except ModuleNotFoundError:
    from demo_catalog import find_profile
    from extraction import extract_listing_facts
    from identification import identify_product
    from reference_data import reference_for
    from scoring import Assessment, Evidence, METHOD_VERSION, score_product


def evidence_fingerprint(evidence: list[Evidence]) -> str:
    payload = [{"id": e.id, "claim": e.claim, "provenance": e.provenance,
                "source": e.source, "source_url": e.source_url,
                "product_match_confirmed": e.product_match_confirmed}
               for e in sorted(evidence, key=lambda item: item.id)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _facts_to_assessments(category: str, extracted):
    """Only translate facts whose consequence is explicit in the rubric.

    Material names and words such as natural/recyclable are deliberately not
    converted to safety claims. Unknown dimensions stay unknown.
    """
    assessments = []
    facts = {(fact.kind, fact.value): fact for fact in extracted.facts}
    if category == "cleaning":
        if ("product_format", "concentrate") in facts:
            fact = facts[("product_format", "concentrate")]
            assessments.append(Assessment("concentration", "documented_concentrate", fact.evidence_ids))
        if ("use_pattern", "single_use") in facts:
            fact = facts[("use_pattern", "single_use")]
            assessments.append(Assessment("packaging", "single_use", fact.evidence_ids))
        elif ("product_format", "refill") in facts:
            fact = facts[("product_format", "refill")]
            assessments.append(Assessment("packaging", "minimal_refill", fact.evidence_ids))
    elif category == "bottles":
        if ("use_pattern", "single_use") in facts:
            fact = facts[("use_pattern", "single_use")]
            assessments.append(Assessment("reuse", "single_use", fact.evidence_ids))
        elif ("use_pattern", "reusable") in facts:
            fact = facts[("use_pattern", "reusable")]
            assessments.append(Assessment("reuse", "limited_reuse", fact.evidence_ids))
        if ("packaging", "plastic_shrink_wrap") in facts:
            fact = facts[("packaging", "plastic_shrink_wrap")]
            assessments.append(Assessment("packaging", "excessive", fact.evidence_ids))
    return assessments


def evaluate_product(product: dict, profile=None) -> dict:
    profile = profile or find_profile(product)
    if profile:
        evidence = list(profile["evidence"])
        analysis = score_product(profile["category"], list(profile["assessments"]), evidence)
        extraction = None
        category = profile["category"]
    else:
        extraction = extract_listing_facts(product)
        evidence = list(extraction.evidence)
        category = extraction.category
        analysis = score_product(category, _facts_to_assessments(category, extraction), evidence)

    identity = asdict(identify_product(product))
    return {
        "identity": identity,
        "analysis": analysis.to_dict(),
        "evidence_fingerprint": evidence_fingerprint(evidence),
        "method_version": METHOD_VERSION,
        "extraction": None if extraction is None else {
            "facts": [fact.__dict__ for fact in extraction.facts],
            "reference_flags": [
                {"kind": fact.kind, "value": fact.value, **reference_for(fact.kind, fact.value)}
                for fact in extraction.facts if reference_for(fact.kind, fact.value)
            ],
            "warnings": list(extraction.warnings),
        },
        "profile": profile,
        "category": category,
    }
