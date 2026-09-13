import unittest

from backend.pricing import infer_quantity, price_basis


class PricingTests(unittest.TestCase):
    def test_infers_fluid_ounces(self):
        self.assertEqual(infer_quantity("Dish Soap, 40 fl oz"), (40.0, "fl oz"))

    def test_reports_unit_and_use_basis_separately(self):
        result = price_basis({"name": "Refills", "price": 6, "unit_quantity": 4,
                              "unit_label": "refill", "estimated_uses": 120})
        self.assertEqual(result["price_per_unit"], 1.5)
        self.assertEqual(result["price_per_use"], .05)
        self.assertIn("estimate", result["note"])


if __name__ == "__main__":
    unittest.main()
