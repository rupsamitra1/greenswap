import ast
import pathlib
import unittest


class ProductContractTests(unittest.TestCase):
    def test_backend_accepts_strong_identifiers(self):
        source = pathlib.Path("backend/main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        product = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Product")
        fields = {node.target.id for node in product.body
                  if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
        self.assertTrue({"asin", "gtin", "model_number", "sku"} <= fields)

    def test_extension_sends_the_same_identifier_names(self):
        source = pathlib.Path("extension/scrapers.js").read_text(encoding="utf-8")
        for field in ("asin:", "gtin:", "model_number:", "sku:"):
            self.assertIn(field, source)


if __name__ == "__main__":
    unittest.main()
