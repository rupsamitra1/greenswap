import copy
import unittest

from backend.ranking import rank_candidates


def item(id, eco, price, affiliate=False, confidence=90, category="cleaning"):
    return {"id": id, "category": category, "price": price, "affiliate": affiliate,
            "analysis": {"overall_score": eco, "confidence_score": confidence}}


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.original = {"category": "cleaning", "price": 5,
                         "analysis": {"overall_score": 50}}

    def test_affiliate_can_reorder_only_inside_four_point_band(self):
        ranked = rank_candidates(self.original, [item("best", 85, 4), item("partner", 82, 4, True)])
        self.assertEqual([x["id"] for x in ranked["candidates"]], ["partner", "best"])
        self.assertTrue(ranked["affiliate_influenced"])
        self.assertEqual(ranked["candidates"][0]["analysis"]["overall_score"], 82)

    def test_affiliate_cannot_jump_a_meaningful_eco_gap(self):
        ranked = rank_candidates(self.original, [item("best", 90, 4), item("partner", 85, 4, True)])
        self.assertEqual([x["id"] for x in ranked["candidates"]], ["best", "partner"])
        self.assertEqual(ranked["candidates"][1]["affiliate_boost"], 0)

    def test_commission_never_appears_in_policy_or_score(self):
        candidate = item("partner", 84, 4, True)
        candidate["commission_rate"] = 99
        result = rank_candidates(self.original, [candidate])
        self.assertFalse(result["policy"]["commission_rate_used"])
        self.assertEqual(result["candidates"][0]["analysis"]["overall_score"], 84)

    def test_price_confidence_and_improvement_are_hard_filters(self):
        result = rank_candidates(self.original, [
            item("pricier", 90, 6), item("weak", 90, 4, confidence=40), item("tiny", 59, 4)
        ])
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["keep_current"])
        reasons = {row["id"]: row["reasons"] for row in result["rejected"]}
        self.assertIn("costs more than the viewed product", reasons["pricier"])


if __name__ == "__main__":
    unittest.main()
