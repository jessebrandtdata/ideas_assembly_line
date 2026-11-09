"""collect.py's --cache-dir merge: a union by package_id that never replaces a row already present."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collect import merge_cache  # noqa: E402

FIELDS = ["package_id", "pages"]


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def read(path):
    with path.open(newline="") as f:
        return [(r["package_id"], r["pages"]) for r in csv.DictReader(f)]


class MergeCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data, self.cache = self.root / "data", self.root / "cache"

    def tearDown(self):
        self._tmp.cleanup()

    def test_adds_missing_rows_and_keeps_existing_ones(self):
        write(self.data / "pages.csv", [{"package_id": "A", "pages": "1"}, {"package_id": "B", "pages": "2"}])
        write(self.cache / "pages.csv", [{"package_id": "B", "pages": "99"}, {"package_id": "C", "pages": "3"}])
        self.assertEqual(merge_cache(self.cache, self.data, "pages.csv", FIELDS), 1)
        self.assertEqual(read(self.data / "pages.csv"), [("A", "1"), ("B", "2"), ("C", "3")])

    def test_writes_back_into_an_empty_cache(self):
        write(self.data / "pages.csv", [{"package_id": "A", "pages": "1"}])
        self.assertEqual(merge_cache(self.data, self.cache, "pages.csv", FIELDS), 1)
        self.assertEqual(read(self.cache / "pages.csv"), [("A", "1")])

    def test_no_cache_is_a_no_op(self):
        write(self.data / "pages.csv", [{"package_id": "A", "pages": "1"}])
        self.assertEqual(merge_cache(None, self.data, "pages.csv", FIELDS), 0)
        self.assertEqual(merge_cache(self.cache, self.data, "pages.csv", FIELDS), 0)  # cache file absent
        self.assertEqual(read(self.data / "pages.csv"), [("A", "1")])


if __name__ == "__main__":
    unittest.main()
