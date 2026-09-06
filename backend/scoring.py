"""Experimental, deterministic scoring contract. Not yet wired into /analyze.

Inputs must be assessed facts with evidence references, never raw marketing copy.
Weights are prototype policy choices, not a validated life-cycle assessment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

METHOD_VERSION = "prototype-1"
Provenance = Literal["certified", "manufacturer_documented", "retailer_documented",
                     "label_extracted", "ai_inferred", "unknown"]
PROVENANCE = {"certified", "manufacturer_documented", "retailer_documented",
              "label_extracted", "ai_inferred", "unknown"}

# Dimension: (maximum contribution, explicit assessment -> fraction earned).
# Certifications support the relevant fact; they do not earn duplicate points.
RUBRICS = {
    "cleaning": {
        "ingredient_safety": (30, {"lower_concern_assessed": 1., "mixed_concern": .5, "high_concern": 0.}),
        "environmental_fate": (30, {"lower_concern_assessed": 1., "mixed_concern": .5, "high_concern": 0.}),
        "packaging": (25, {"minimal_refill": 1., "reduced_packaging": .7, "single_use": .2, "excessive": 0.}),
        "concentration": (15, {"documented_concentrate": 1., "ready_to_use": .4}),
    },
    "bottles": {
        "material_impact": (25, {"documented_lower_impact": 1., "mixed_impact": .5, "high_impact": 0.}),
        "reuse": (35, {"documented_durable": 1., "limited_reuse": .5, "single_use": 0.}),
        "packaging": (20, {"minimal": 1., "reduced_packaging": .7, "single_use": .2, "excessive": 0.}),
        "end_of_life": (20, {"confirmed_local_route": 1., "conditional_route": .5, "no_recovery_route": 0.}),
    },
    "generic": {
        "material_impact": (35, {"documented_lower_impact": 1., "mixed_impact": .5, "high_impact": 0.}),
        "packaging": (30, {"minimal": 1., "reduced_packaging": .7, "single_use": .2, "excessive": 0.}),
        "resource_efficiency": (35, {"documented_lower_use": 1., "typical_use": .5, "high_use": 0.}),
    },
}


@dataclass(frozen=True)
class Evidence:
    id: str
    claim: str
    provenance: Provenance
    source: str
    source_url: str | None = None
    # A reference alone is not proof of product identity or certification scope.
    product_match_confirmed: bool = False


@dataclass(frozen=True)
class Assessment:
    dimension: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DimensionScore:
    dimension: str
    points: float | None
    maximum: int
    assessment: str | None
    evidence_ids: tuple[str, ...]
    inferred: bool = False


@dataclass(frozen=True)
class Analysis:
    method_version: str
    category: str
    rubric: str
    status: str
    overall_score: int | None
    # Missing dimensions can contribute anything from zero to their maximum.
    # This is a coverage bound, NOT a statistical confidence interval.
    coverage_bounds: tuple[float, float]
    coverage_percent: int
    confidence: str
    dimensions: tuple[DimensionScore, ...]
    evidence: tuple[Evidence, ...]
    warnings: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


def score_product(category: str, assessments: list[Assessment], evidence: list[Evidence]) -> Analysis:
    """Calculate identical scores for originals and alternatives from assessed facts.

    No affiliate, price, brand, or model-generated score is accepted here.
    Unassessed dimensions remain unknown. A point score requires full coverage.
    Evidence confidence is deliberately qualitative until step 5 adds calibration.
    """
    rubric_name = category if category in RUBRICS else "generic"
    rubric = RUBRICS[rubric_name]
    by_id = {item.id: item for item in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("Evidence IDs must be unique")
    for item in evidence:
        if not item.id.strip() or not item.claim.strip() or not item.source.strip():
            raise ValueError("Evidence requires an ID, claim, and source")
        if item.provenance not in PROVENANCE:
            raise ValueError("Unsupported provenance")
        if item.provenance == "certified" and (not item.source_url or not item.product_match_confirmed):
            raise ValueError("Certification requires a source URL and confirmed product match")

    by_dimension = {}
    for item in assessments:
        if item.dimension not in rubric or item.dimension in by_dimension:
            raise ValueError("Unknown or duplicate dimension")
        if item.value not in rubric[item.dimension][1]:
            raise ValueError("Unsupported assessment value")
        if not item.evidence_ids or any(ref not in by_id for ref in item.evidence_ids):
            raise ValueError("Assessment must reference existing evidence")
        if any(by_id[ref].provenance == "unknown" for ref in item.evidence_ids):
            raise ValueError("Unknown evidence cannot justify an assessment")
        by_dimension[item.dimension] = item

    dimensions = []
    for name, (maximum, values) in rubric.items():
        item = by_dimension.get(name)
        dimensions.append(DimensionScore(
            name, round(maximum * values[item.value], 2) if item else None,
            maximum, item.value if item else None, item.evidence_ids if item else (),
            bool(item and any(by_id[ref].provenance == "ai_inferred" for ref in item.evidence_ids)),
        ))
    known = sum(d.points or 0 for d in dimensions)
    coverage = sum(d.maximum for d in dimensions if d.points is not None)
    complete = coverage == 100
    warnings = [f"Missing assessment: {d.dimension}" for d in dimensions if d.points is None]
    inferred = any(d.inferred for d in dimensions)
    if inferred:
        warnings.append("Includes inferred facts; score is provisional")
    if rubric_name == "generic":
        warnings.append("Generic rubric: not suitable for confident cross-category ranking")
    warnings.append("Prototype rubric; not a safety certification or measured life-cycle footprint")
    return Analysis(
        METHOD_VERSION, category, rubric_name,
        "provisional" if complete else "insufficient_evidence",
        int(known + .5) if complete else None,
        (round(known, 2), round(known + 100 - coverage, 2)), coverage,
        "low" if inferred or not complete or rubric_name == "generic" else "uncalibrated",
        tuple(dimensions), tuple(evidence), tuple(warnings),
    )
