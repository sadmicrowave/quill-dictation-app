"""Unit tests for Vocabulary — no workbook or network needed."""
import unittest
from quill.parser.vocab import Vocabulary

FIXTURE = {
    "Brand":     ["Nike", "Adidas", "The North Face", "Levi's"],
    "Size":      ["XS", "S", "M", "L", "XL"],
    "Color":     ["Black", "White", "Red", "Navy Blue"],
    "Condition": ["New", "Good", "Fair", "Poor"],
}

class TestLoad(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary()
        self.v.load(FIXTURE)
    def test_len(self):
        self.assertEqual(len(self.v), sum(len(x) for x in FIXTURE.values()))
    def test_columns(self):
        self.assertEqual(set(self.v.columns()), set(FIXTURE.keys()))
    def test_values_for_known(self):
        self.assertIn("Nike", self.v.values_for("Brand"))
    def test_values_for_unknown(self):
        self.assertEqual(self.v.values_for("Nope"), [])

class TestMatch(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary()
        self.v.load(FIXTURE)
    def test_exact_case_insensitive(self):
        e = self.v.match("nike")
        self.assertIsNotNone(e)
        self.assertEqual(e.canonical, "Nike")
    def test_multiword(self):
        e = self.v.match("the north face")
        self.assertIsNotNone(e)
        self.assertEqual(e.canonical, "The North Face")
    def test_column_assigned(self):
        e = self.v.match("black")
        self.assertIsNotNone(e)
        self.assertEqual(e.column, "Color")
    def test_garbage_returns_none(self):
        self.assertIsNone(self.v.match("xyzzy123"))

class TestAdd(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary()
        self.v.load(FIXTURE)
    def test_add_existing_column(self):
        before = len(self.v)
        self.v.add("Brand", "Patagonia")
        self.assertEqual(len(self.v), before + 1)
        self.assertIn("Patagonia", self.v.values_for("Brand"))
    def test_add_new_column(self):
        self.v.add("Material", "Cotton")
        self.assertIn("Material", self.v.columns())

if __name__ == "__main__":
    unittest.main()
