import unittest

from backend.demo_catalog import CATALOG
from backend.evaluation import evaluate_product


class EvaluationTests(unittest.TestCase):
    def test_every_demo_product_uses_same_complete_versioned_rubric(self):
        for profile in CATALOG:
            result = evaluate_product({"title": profile["name"], "sku": profile["sku"]}, profile)
            self.assertEqual(result["analysis"]["coverage_percent"], 100, profile["id"])
            self.assertIsNotNone(result["analysis"]["overall_score"], profile["id"])
            self.assertEqual(result["method_version"], "prototype-2")
            self.assertEqual(len(result["evidence_fingerprint"]), 64)

    def test_unlisted_product_does_not_get_a_fake_complete_score(self):
        result = evaluate_product({"title": "Natural Eco Friendly Mystery Cleaner"})
        self.assertIsNone(result["analysis"]["overall_score"])
        self.assertEqual(result["analysis"]["status"], "insufficient_evidence")
        self.assertIn("Environmental marketing language was recorded but not treated as proof",
                      result["extraction"]["warnings"])

    def test_material_reference_flags_questions_not_a_safety_verdict(self):
        result = evaluate_product({
            "title": "PET Water Bottle", "bullets": ["Single-use PET plastic bottle"]
        })
        flags = result["extraction"]["reference_flags"]
        self.assertTrue(any("local_recycling_required" in item["flags"] for item in flags))
        self.assertIsNone(result["analysis"]["overall_score"])


if __name__ == "__main__":
    unittest.main()
