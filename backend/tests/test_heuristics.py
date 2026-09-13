import unittest

from backend.heuristics import analyze_text


class HeuristicTests(unittest.TestCase):
    def test_amazon_pack_of_quantity_is_treated_as_disposable(self):
        result = analyze_text(
            "Water bottles, 16.9 Fl Oz (Pack of 24); packaging made from rPET"
        )
        self.assertLessEqual(result["eco_score"], 30)
        self.assertIn("sold in disposable quantities", result["negative"])
        self.assertIn("recycled content", result["positive"])


if __name__ == "__main__":
    unittest.main()
