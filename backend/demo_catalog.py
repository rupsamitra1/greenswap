"""Auditable demo fixtures used when no live product database is configured.

The brands and claims below are fictional. They demonstrate how evidence flows
through GreenSwap; they are not real certification or life-cycle claims.
"""
from __future__ import annotations

try:
    from backend.scoring import Assessment, Evidence
except ModuleNotFoundError:
    from scoring import Assessment, Evidence


def ev(id: str, claim: str, source: str = "Demo product specification") -> Evidence:
    return Evidence(id, claim, "manufacturer_documented", source)


def profile(*, id, name, brand, category, price, sku, model_number, reason,
            emoji, unit_quantity, unit_label, estimated_uses, affiliate,
            purchase_url, evidence, assessments, certification=None,
            catalog_role="alternative"):
    return {
        "id": id, "name": name, "brand": brand, "category": category,
        "price": price, "sku": sku, "model_number": model_number,
        "reason": reason, "emoji": emoji, "unit_quantity": unit_quantity,
        "unit_label": unit_label, "estimated_uses": estimated_uses,
        "affiliate": affiliate, "purchase_url": purchase_url,
        "certification": certification, "catalog_role": catalog_role,
        "evidence": evidence, "assessments": assessments,
    }


CATALOG = [
    profile(
        id="view-soap", name="Ultra Clean Dish Soap, 40oz", brand="SudStar",
        category="cleaning", price=4.49, sku="SS-DISH-40-LMN",
        model_number="SUDSTAR-UC40", emoji="🧽", unit_quantity=40,
        unit_label="fl oz", estimated_uses=80, affiliate=False,
        purchase_url="/store/product-soap.html", catalog_role="viewed",
        reason="Concentrated, but documented synthetic surfactants, fragrance, and a single-use bottle create tradeoffs.",
        evidence=[
            ev("ss-ingredients", "Demo formula review found a mix of lower- and higher-concern ingredients"),
            ev("ss-fate", "Demo fate review found partial biodegradation data and unresolved aquatic-impact questions"),
            ev("ss-pack", "40 fl oz formula is sold in a single-use plastic bottle"),
            ev("ss-conc", "Product is sold as a concentrated formula"),
        ],
        assessments=[
            Assessment("ingredient_safety", "mixed_concern", ("ss-ingredients",)),
            Assessment("environmental_fate", "mixed_concern", ("ss-fate",)),
            Assessment("packaging", "single_use", ("ss-pack",)),
            Assessment("concentration", "documented_concentrate", ("ss-conc",)),
        ],
    ),
    profile(
        id="view-bottles", name="Disposable Plastic Water Bottles, 24 Pack",
        brand="HydroBasic", category="bottles", price=12.99,
        sku="HB-WATER-24", model_number="HYDROBASIC-24PK", emoji="🧴",
        unit_quantity=24, unit_label="bottle", estimated_uses=24,
        affiliate=False, purchase_url="/store/product-bottles.html", catalog_role="viewed",
        reason="PET may have a conditional recycling route, but this 24-pack is single-use and shrink-wrapped.",
        evidence=[
            ev("hb-material", "Bottles are made from lightweight PET plastic"),
            ev("hb-reuse", "The 24 bottles are designed for single use"),
            ev("hb-pack", "The case is bundled in plastic shrink film"),
            ev("hb-eol", "PET recovery depends on local acceptance and clean collection"),
        ],
        assessments=[
            Assessment("material_impact", "high_impact", ("hb-material",)),
            Assessment("reuse", "single_use", ("hb-reuse",)),
            Assessment("packaging", "excessive", ("hb-pack",)),
            Assessment("end_of_life", "conditional_route", ("hb-eol",)),
        ],
    ),
    profile(
        id="view-refill", name="Concentrated Dish Soap Refill, 4 Pack",
        brand="BetterDrop", category="cleaning", price=6.25,
        sku="BD-REFILL-4", model_number="BETTERDROP-R4", emoji="♻️",
        unit_quantity=4, unit_label="refill", estimated_uses=120,
        affiliate=False, purchase_url="/store/product-refill.html", catalog_role="viewed",
        reason="Documented lower-concern chemistry, concentrated refills, and minimal packaging make keeping this product the best result.",
        evidence=[
            ev("bd-ing", "Full ingredient review found only lower-concern ingredients"),
            ev("bd-fate", "Surfactants meet the demo readily-biodegradable screening rule"),
            ev("bd-pack", "Four paper-wrapped refill tablets use no new bottle"),
            ev("bd-conc", "Each concentrated tablet makes one bottle of soap"),
        ],
        assessments=[
            Assessment("ingredient_safety", "lower_concern_assessed", ("bd-ing",)),
            Assessment("environmental_fate", "lower_concern_assessed", ("bd-fate",)),
            Assessment("packaging", "minimal_refill", ("bd-pack",)),
            Assessment("concentration", "documented_concentrate", ("bd-conc",)),
        ],
    ),
    profile(
        id="alt-leafclean", name="Plant-Based Dish Soap, 40oz", brand="LeafClean",
        category="cleaning", price=3.99, sku="LC-DISH-40", model_number="LEAFCLEAN-40",
        reason="Lower-concern ingredients and fate documentation, with a reduced-plastic bottle.",
        emoji="🌿", unit_quantity=40, unit_label="fl oz", estimated_uses=80,
        affiliate=True, purchase_url="https://example.com/greenswap/leafclean",
        certification="Demo verified profile",
        evidence=[ev("lc-ing", "Full formula assessed as lower concern"), ev("lc-fate", "Formula passes demo biodegradation screen"), ev("lc-pack", "Bottle uses 60% less plastic than the category baseline"), ev("lc-ready", "Ready-to-use liquid formula")],
        assessments=[Assessment("ingredient_safety", "lower_concern_assessed", ("lc-ing",)), Assessment("environmental_fate", "lower_concern_assessed", ("lc-fate",)), Assessment("packaging", "reduced_packaging", ("lc-pack",)), Assessment("concentration", "ready_to_use", ("lc-ready",))],
    ),
    profile(
        id="alt-barblock", name="Solid Dish Soap Block, Plastic-Free", brand="Sudsy Bar",
        category="cleaning", price=3.25, sku="SB-BLOCK-8", model_number="SUDSY-8",
        reason="A documented low-concern solid formula avoids both a plastic bottle and shipped water.",
        emoji="🧼", unit_quantity=8, unit_label="oz", estimated_uses=70,
        affiliate=False, purchase_url="https://example.com/greenswap/sudsy-bar",
        evidence=[ev("sb-ing", "Ingredient disclosure supports a low-concern screen"), ev("sb-fate", "Formula ingredients pass the demo environmental-fate screen"), ev("sb-pack", "Paper sleeve is the only packaging"), ev("sb-ready", "Solid is used directly rather than diluted as a concentrate")],
        assessments=[Assessment("ingredient_safety", "documented_low_concern", ("sb-ing",)), Assessment("environmental_fate", "documented_low_concern", ("sb-fate",)), Assessment("packaging", "minimal_refill", ("sb-pack",)), Assessment("concentration", "ready_to_use", ("sb-ready",))],
    ),
    profile(
        id="alt-refill", name="Refillable Dish Soap Starter Kit", brand="ReFill Co.",
        category="cleaning", price=5.25, sku="RF-START-1", model_number="REFILL-START",
        reason="A concentrated lower-concern refill system minimizes repeat packaging.",
        emoji="♻️", unit_quantity=1, unit_label="kit", estimated_uses=100,
        affiliate=True, purchase_url="https://example.com/greenswap/refill",
        evidence=[ev("rf-ing", "Complete formula passes the demo lower-concern screen"), ev("rf-fate", "Formula passes the demo biodegradation screen"), ev("rf-pack", "Reusable dispenser ships with a minimal refill pouch"), ev("rf-conc", "Concentrate is diluted at home")],
        assessments=[Assessment("ingredient_safety", "lower_concern_assessed", ("rf-ing",)), Assessment("environmental_fate", "documented_low_concern", ("rf-fate",)), Assessment("packaging", "minimal_refill", ("rf-pack",)), Assessment("concentration", "documented_concentrate", ("rf-conc",))],
    ),
    profile(
        id="alt-eversip", name="Stainless Steel Bottle, 24oz", brand="EverSip",
        category="bottles", price=9.99, sku="ES-STEEL-24", model_number="EVERSIP-24",
        reason="A durable reusable bottle can displace many single-use bottles; recovery remains locally dependent.",
        emoji="🥤", unit_quantity=24, unit_label="fl oz", estimated_uses=500,
        affiliate=True, purchase_url="https://example.com/greenswap/eversip",
        certification="Demo verified profile",
        evidence=[ev("es-mat", "Body is documented food-grade stainless steel"), ev("es-reuse", "Designed and warranty-tested for repeated use"), ev("es-pack", "Ships in a single recycled-cardboard carton"), ev("es-eol", "Metal recycling availability varies locally")],
        assessments=[Assessment("material_impact", "documented_lower_impact", ("es-mat",)), Assessment("reuse", "documented_durable", ("es-reuse",)), Assessment("packaging", "minimal", ("es-pack",)), Assessment("end_of_life", "conditional_route", ("es-eol",))],
    ),
    profile(
        id="alt-pureflow", name="Glass Bottle with Protective Sleeve", brand="PureFlow",
        category="bottles", price=7.49, sku="PF-GLASS-20", model_number="PUREFLOW-20",
        reason="Durable borosilicate glass and minimal packaging reduce single-use waste, though glass has production and recovery tradeoffs.",
        emoji="🫙", unit_quantity=20, unit_label="fl oz", estimated_uses=350,
        affiliate=False, purchase_url="https://example.com/greenswap/pureflow",
        evidence=[ev("pf-mat", "Borosilicate glass body with silicone sleeve"), ev("pf-reuse", "Designed for repeated washing and reuse"), ev("pf-pack", "Ships in one cardboard carton"), ev("pf-eol", "Borosilicate glass is not accepted by every curbside program")],
        assessments=[Assessment("material_impact", "mixed_impact", ("pf-mat",)), Assessment("reuse", "documented_durable", ("pf-reuse",)), Assessment("packaging", "minimal", ("pf-pack",)), Assessment("end_of_life", "conditional_route", ("pf-eol",))],
    ),
]


def find_profile(product: dict):
    for item in CATALOG:
        if product.get("sku") and product.get("sku") == item["sku"]:
            return item
        if product.get("model_number") and product.get("model_number") == item["model_number"]:
            return item
    return None


def alternatives(category: str):
    return [item for item in CATALOG if item["catalog_role"] == "alternative" and item["category"] == category]
