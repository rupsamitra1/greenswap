import unittest

from backend.identification import asin_from_url, compare_identities, identify_product, valid_gtin


class IdentificationTests(unittest.TestCase):
    def test_validates_gtin_check_digit(self):
        self.assertEqual(valid_gtin("036000291452"), "036000291452")
        self.assertIsNone(valid_gtin("036000291453"))

    def test_extracts_asin_from_supported_amazon_urls(self):
        self.assertEqual(asin_from_url("https://amazon.com/dp/B012345678?tag=x"), "B012345678")

    def test_prefers_exact_identifier_for_key(self):
        first = identify_product({"title": "Anything", "gtin": "036000291452"})
        second = identify_product({"title": "Changed title", "gtin": "036000291452"})
        self.assertEqual(first.identity_key, second.identity_key)
        self.assertEqual(first.identity_strength, "exact")

    def test_rejects_conflicting_strong_identifiers(self):
        left = identify_product({"title": "Bottle 24oz", "brand": "A", "model_number": "X1"})
        right = identify_product({"title": "Bottle 24oz", "brand": "A", "model_number": "X2"})
        self.assertEqual(compare_identities(left, right).level, "conflict")

    def test_size_variant_prevents_title_only_match(self):
        left = identify_product({"title": "Clean Soap 20oz", "brand": "CleanCo"})
        right = identify_product({"title": "Clean Soap 40oz", "brand": "CleanCo"})
        match = compare_identities(left, right)
        self.assertEqual(match.level, "weak")
        self.assertEqual(match.score, 20)

    def test_brand_and_model_is_strong(self):
        left = identify_product({"title": "Listing one", "brand": "CleanCo", "model_number": "AB-12"})
        right = identify_product({"title": "Listing two", "brand": "CleanCo", "model_number": "AB12"})
        self.assertEqual(compare_identities(left, right).score, 96)


if __name__ == "__main__":
    unittest.main()
