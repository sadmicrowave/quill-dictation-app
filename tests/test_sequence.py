"""Counter columns: what the last values of a column say comes next."""
import unittest

from quill.sequence import detect


class TestWhatCountsAsACounter(unittest.TestCase):
    def test_plain_numbers(self):
        found = detect([41, 42, 43])
        self.assertEqual(found.next, 44)
        self.assertIsInstance(found.next, int)

    def test_floats_that_are_whole_numbers_come_back_as_integers(self):
        found = detect([41.0, 42.0, 43.0])               # (what a live Excel hands over)
        self.assertEqual(found.next, 44)
        self.assertIsInstance(found.next, int)

    def test_text_with_a_prefix_and_zero_padding(self):
        self.assertEqual(detect(["A-0041", "A-0042", "A-0043"]).next, "A-0044")

    def test_padding_is_kept_across_a_new_digit(self):
        self.assertEqual(detect(["R007", "R008", "R009"]).next, "R010")
        self.assertEqual(detect(["R098", "R099", "R100"]).next, "R101")

    def test_numbers_with_no_padding_grow_a_digit(self):
        self.assertEqual(detect(["INV8", "INV9", "INV10", "INV11"]).next, "INV12")
        self.assertEqual(detect(["8", "9", "10"]).next, "11")

    def test_text_after_the_number_is_kept(self):
        self.assertEqual(detect(["12b", "13b", "14b"]).next, "15b")

    def test_the_last_number_in_the_text_is_the_one_that_counts(self):
        self.assertIsNone(detect(["12/24", "13/24", "14/24"]))               # (the 24 does not change: no counter)
        self.assertEqual(detect(["12/24", "12/25", "12/26"]).next, "12/27")

    def test_digits_earlier_in_the_text_are_part_of_the_prefix(self):
        self.assertEqual(detect(["2026-001", "2026-002", "2026-003"]).next, "2026-004")

    def test_the_numbers_may_be_text_in_the_sheet(self):
        self.assertEqual(detect(["7", "8", "9"]).next, "10")
        self.assertEqual(detect([7, "8", 9]).next, "10")                     # (a mix of the two reads the same)

    def test_only_the_end_of_the_column_counts(self):
        self.assertEqual(detect([3, 9, 1, 2, 3]).next, 4)                    # (older rows may be out of order)

    def test_the_explanation_names_the_run_and_the_next_value(self):
        self.assertEqual(detect(["A-0041", "A-0042", "A-0043"]).explanation, "A-0041, A-0042, A-0043 → A-0044")
        self.assertEqual(detect(list(range(1, 11))).explanation, "8, 9, 10 → 11")


class TestWhatDoesNot(unittest.TestCase):
    def test_too_short_a_run(self):
        self.assertIsNone(detect([1, 2]))
        self.assertIsNone(detect([5]))
        self.assertIsNone(detect([]))

    def test_a_jump_ends_the_run(self):
        self.assertIsNone(detect([1, 2, 4]))
        self.assertIsNone(detect([1, 2, 3, 5]))
        self.assertIsNone(detect([3, 2, 1]))                                 # (counting down is not a counter)
        self.assertIsNone(detect([5, 5, 5]))

    def test_different_text_around_the_number(self):
        self.assertIsNone(detect(["A-1", "B-2", "A-3"]))
        self.assertIsNone(detect(["A-1", "A-2", "A.3"]))

    def test_text_dates_and_blanks(self):
        import datetime as dt
        self.assertIsNone(detect(["fern", "cactus", "orchid"]))
        self.assertIsNone(detect([dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)]))
        self.assertIsNone(detect([1, 2, None]))
        self.assertIsNone(detect([1, 2, "n/a"]))

    def test_a_formula_is_not_a_counter(self):
        self.assertIsNone(detect(["=ROW()-1", "=ROW()-1", "=ROW()-1"]))
        self.assertIsNone(detect(["=A2+1", "=A3+1", "=A4+1"]))               # (digits inside a formula are not a number to continue)

    def test_booleans_negatives_and_decimals(self):
        self.assertIsNone(detect([True, False, True]))
        self.assertIsNone(detect([-3, -2, -1]))
        self.assertIsNone(detect([1.5, 2.5, 3.5]))

    def test_a_padded_number_is_not_continued_with_a_different_width(self):
        self.assertIsNone(detect(["A-01", "A-002", "A-003"]))                # ("01" and "002" are not the same form of number)


if __name__ == "__main__":
    unittest.main()
