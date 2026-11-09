"""congress.py: which Congress a date is in, and the --congress option."""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from congress import BILL_TYPES, congress_dirs, congress_end, congress_on, congress_start, parse_congresses  # noqa: E402


class CongressDates(unittest.TestCase):
    def test_start_and_end(self):
        self.assertEqual(congress_start(119), date(2025, 1, 3))
        self.assertEqual(congress_end(119), date(2027, 1, 2))
        self.assertEqual(congress_start(120), date(2027, 1, 3))
        self.assertEqual(congress_start(74), date(1935, 1, 3))

    def test_the_january_handover(self):
        self.assertEqual(congress_on(date(2027, 1, 2)), 119)
        self.assertEqual(congress_on(date(2027, 1, 3)), 120)
        self.assertEqual(congress_on(date(2026, 12, 31)), 119)
        self.assertEqual(congress_on(date(2025, 1, 3)), 119)
        self.assertEqual(congress_on(date(2025, 1, 2)), 118)

    def test_every_day_of_a_congress_maps_back_to_it(self):
        for n in (108, 119, 120, 125):
            self.assertEqual(congress_on(congress_start(n)), n)
            self.assertEqual(congress_on(congress_end(n)), n)

    def test_before_the_january_third_rule_is_refused(self):
        with self.assertRaises(ValueError):
            congress_start(73)
        with self.assertRaises(ValueError):
            congress_on(date(1934, 6, 1))


class ParseCongresses(unittest.TestCase):
    TODAY = date(2026, 11, 9)

    def test_numbers_ranges_and_words_newest_first(self):
        self.assertEqual(parse_congresses("119", self.TODAY), [119])
        self.assertEqual(parse_congresses("113-115,119", self.TODAY), [119, 115, 114, 113])
        self.assertEqual(parse_congresses("current,previous", self.TODAY), [119, 118])
        self.assertEqual(parse_congresses("current, 119 ,118", self.TODAY), [119, 118])

    def test_current_moves_in_january(self):
        self.assertEqual(parse_congresses("current,previous", date(2027, 1, 3)), [120, 119])

    def test_all_needs_a_listing(self):
        self.assertEqual(parse_congresses("all", self.TODAY, available=[108, 110, 109]), [110, 109, 108])
        with self.assertRaises(ValueError):
            parse_congresses("all", self.TODAY)

    def test_bad_values_are_refused(self):
        for spec in ("", "119-113", "next", "60"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_congresses(spec, self.TODAY)


class CongressDirs(unittest.TestCase):
    def test_numbered_folders_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("119", "108", "notes"):
                (root / name).mkdir()
            (root / "120").write_text("a file, not a folder")
            self.assertEqual(congress_dirs(root), [108, 119])
            self.assertEqual(congress_dirs(root / "missing"), [])


class BillTypes(unittest.TestCase):
    def test_all_eight_measure_types(self):
        self.assertEqual(set(BILL_TYPES), {"hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"})


if __name__ == "__main__":
    unittest.main()
