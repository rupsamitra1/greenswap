import unittest

from fastapi.testclient import TestClient

from backend.main import app


class AnalyzeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def analyze(self, title, brand, price, sku, model):
        response = self.client.post("/analyze", json={
            "title": title, "brand": brand, "price": price,
            "retailer": "mockstore", "sku": sku, "model_number": model,
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_soap_demonstrates_disclosed_affiliate_equivalence_rule(self):
        data = self.analyze("Ultra Clean Dish Soap, 40oz", "SudStar", 4.49,
                            "SS-DISH-40-LMN", "SUDSTAR-UC40")
        self.assertEqual(data["original"]["eco_score"], 50)
        self.assertEqual(data["alternatives"][0]["id"], "alt-leafclean")
        self.assertEqual(data["alternatives"][0]["affiliate_boost"], 3)
        self.assertEqual(data["alternatives"][1]["eco_score"], 85)
        self.assertTrue(data["ranking"]["affiliate_influenced"])

    def test_bottles_returns_reusable_options_with_same_pipeline(self):
        data = self.analyze("Disposable Plastic Water Bottles, 24 Pack", "HydroBasic", 12.99,
                            "HB-WATER-24", "HYDROBASIC-24PK")
        self.assertEqual(data["original"]["eco_score"], 10)
        self.assertEqual({x["id"] for x in data["alternatives"]},
                         {"alt-eversip", "alt-pureflow"})
        self.assertTrue(all(x["analysis"]["method_version"] == data["method_version"]
                            for x in data["alternatives"]))

    def test_already_sustainable_product_gets_keep_current_result(self):
        data = self.analyze("Concentrated Dish Soap Refill, 4 Pack", "BetterDrop", 6.25,
                            "BD-REFILL-4", "BETTERDROP-R4")
        self.assertEqual(data["original"]["eco_score"], 100)
        self.assertEqual(data["alternatives"], [])
        self.assertTrue(data["keep_current"])

    def test_unknown_listing_shows_insufficient_evidence(self):
        response = self.client.post("/analyze", json={"title": "Mystery Household Product", "price": 10})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["analysis"]["overall_score"])
        self.assertEqual(data["analysis"]["status"], "insufficient_evidence")
        self.assertFalse(data["keep_current"])

    def test_all_demo_storefront_pages_are_served(self):
        for path in ("/store/", "/store/product-soap.html",
                     "/store/product-bottles.html", "/store/product-refill.html"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("ShopMart", response.text)


if __name__ == "__main__":
    unittest.main()
