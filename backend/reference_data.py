"""Small, explicit reference layer for demo material/ingredient flags.

These records identify questions and disposal constraints; they do not turn a
material name into a universal good/bad score. Product form, durability,
location, and evidence are still required by the rubric.
"""

MATERIAL_REFERENCES = {
    "polyethylene terephthalate (PET)": {
        "flags": ["fossil_plastic", "local_recycling_required", "single_use_risk"],
        "scope": "Packaging form and end-of-life screening",
        "source": "US EPA: How Do I Recycle Common Recyclables?",
        "source_url": "https://www.epa.gov/recycle/how-do-i-recycle-common-recyclables",
        "caution": "Resin type alone does not prove local recyclability or recycled content.",
    },
    "stainless steel": {
        "flags": ["production_impact", "durability_opportunity", "metal_recovery_possible"],
        "scope": "Durable bottle screening",
        "source": "US EPA: Sustainable Materials Management",
        "source_url": "https://www.epa.gov/smm",
        "caution": "Reuse count and manufacturing data are needed for a break-even claim.",
    },
    "borosilicate glass": {
        "flags": ["production_impact", "durability_opportunity", "special_recovery_constraints"],
        "scope": "Durable bottle screening",
        "source": "US EPA: Sustainable Materials Management",
        "source_url": "https://www.epa.gov/smm",
        "caution": "Heat-resistant glass may not be accepted with container glass locally.",
    },
}

INGREDIENT_REFERENCES = {
    "added fragrance": {
        "flags": ["composition_undisclosed"],
        "scope": "Disclosure check only",
        "source": "Retailer or manufacturer ingredient label",
        "source_url": None,
        "caution": "The word fragrance alone cannot establish hazard or environmental fate.",
    },
    "synthetic surfactants": {
        "flags": ["specific_identity_needed", "fate_data_needed"],
        "scope": "Evidence gap check only",
        "source": "Manufacturer ingredient disclosure",
        "source_url": None,
        "caution": "Synthetic does not automatically mean unsafe; chemical identity and test data are required.",
    },
}


def reference_for(kind: str, value: str):
    table = MATERIAL_REFERENCES if kind == "material" else INGREDIENT_REFERENCES
    return table.get(value)
