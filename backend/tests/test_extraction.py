import unittest

from backend.extraction import extract_listing_facts


class ExtractionTests(unittest.TestCase):
    def test_extracts_source_linked_cleaning_facts(self):
        result = extract_listing_facts({
            "title": "Ultra Clean Dish Soap, 40oz",
            "bullets": ["Contains synthetic surfactants and added fragrance", "40oz single-use plastic bottle"],
            "url": "https://shop.test/soap",
        })
        facts = {(fact.kind, fact.value) for fact in result.facts}
        self.assertEqual(result.category, "cleaning")
        self.assertIn(("ingredient_mention", "synthetic surfactants"), facts)
        self.assertIn(("ingredient_mention", "added fragrance"), facts)
        self.assertIn(("use_pattern", "single_use"), facts)
        self.assertTrue(all(fact.evidence_ids for fact in result.facts))
        self.assertTrue(all(item.source_url == "https://shop.test/soap" for item in result.evidence))

    def test_normalizes_pet_and_packaging(self):
        result = extract_listing_facts({
            "title": "Disposable Water Bottles, 24 Pack",
            "bullets": ["Lightweight PET plastic", "Shrink-wrapped in plastic film", "Single-use bottles"],
        })
        facts = {(fact.kind, fact.value) for fact in result.facts}
        self.assertEqual(result.category, "bottles")
        self.assertIn(("material", "polyethylene terephthalate (PET)"), facts)
        self.assertIn(("packaging", "plastic_shrink_wrap"), facts)

    def test_marketing_language_is_not_material_evidence(self):
        result = extract_listing_facts({"title": "Natural Eco-Friendly Cleaner", "bullets": []})
        facts = {(fact.kind, fact.value) for fact in result.facts}
        self.assertIn(("marketing_claim", "unverified_environmental_claim"), facts)
        self.assertNotIn(("material", "plant material"), facts)
        self.assertTrue(any("not treated as proof" in warning for warning in result.warnings))

    def test_plain_water_reference_is_not_a_bottle_category(self):
        result = extract_listing_facts({"title": "Water-resistant phone case", "bullets": []})
        self.assertEqual(result.category, "other")


if __name__ == "__main__":
    unittest.main()
