import unittest

from backend.scoring import Assessment, Evidence, RUBRICS, score_product


class ScoringTests(unittest.TestCase):
    def test_rubrics_have_bounded_weights(self):
        for rubric in RUBRICS.values():
            self.assertEqual(sum(weight for weight, _ in rubric.values()), 100)
            self.assertTrue(all(0 <= value <= 1 for _, values in rubric.values() for value in values.values()))

    def test_unknown_is_not_average_or_perfect(self):
        result = score_product("cleaning", [], [])
        self.assertIsNone(result.overall_score)
        self.assertEqual(result.coverage_bounds, (0, 100))
        self.assertEqual(result.status, "insufficient_evidence")

    def test_partial_packaging_cannot_hide_unknown_chemistry(self):
        evidence = [Evidence("label", "Refill", "label_extracted", "Fixture label")]
        result = score_product("cleaning", [Assessment("packaging", "minimal_refill", ("label",))], evidence)
        self.assertIsNone(result.overall_score)
        self.assertEqual(result.coverage_bounds, (25, 100))
        self.assertEqual(result.coverage_percent, 25)

    def test_documented_complete_result_is_deterministic(self):
        evidence = [Evidence("fixture", "Assessed fixture only", "manufacturer_documented", "Test specification")]
        facts = [Assessment("ingredient_safety", "mixed_concern", ("fixture",)),
                 Assessment("environmental_fate", "high_concern", ("fixture",)),
                 Assessment("packaging", "minimal_refill", ("fixture",)),
                 Assessment("concentration", "documented_concentrate", ("fixture",))]
        result = score_product("cleaning", facts, evidence)
        self.assertEqual(result.overall_score, 55)
        self.assertEqual(result, score_product("cleaning", facts, evidence))
        self.assertEqual(result.confidence, "uncalibrated")

    def test_bad_evidence_and_category_are_rejected(self):
        evidence = [Evidence("e", "Claim", "retailer_documented", "Listing")]
        for facts in ([Assessment("packaging", "minimal_refill", ("missing",))],
                      [Assessment("reuse", "single_use", ("e",))],
                      [Assessment("packaging", "natural", ("e",))]):
            with self.assertRaises(ValueError):
                score_product("cleaning", facts, evidence)

    def test_certification_requires_traceable_identity(self):
        with self.assertRaises(ValueError):
            score_product("cleaning", [], [Evidence("e", "Certified", "certified", "Claim")])

    def test_reusable_material_alone_cannot_determine_whole_score(self):
        e = Evidence("e", "Reusable", "ai_inferred", "Test inference")
        result = score_product("bottles", [Assessment("reuse", "documented_durable", ("e",))], [e])
        self.assertIsNone(result.overall_score)
        self.assertEqual(result.confidence, "low")

    def test_generic_fallback_is_explicit(self):
        result = score_product("personal_care", [], [])
        self.assertEqual(result.rubric, "generic")
        self.assertEqual(result.category, "personal_care")


if __name__ == "__main__":
    unittest.main()
