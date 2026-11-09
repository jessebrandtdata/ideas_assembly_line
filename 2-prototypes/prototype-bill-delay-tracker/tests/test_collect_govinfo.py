"""collect_govinfo.py, the optional GovInfo page-count lookups, with the network call replaced."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_govinfo  # noqa: E402

MODS = """<mods xmlns="http://www.loc.gov/mods/v3"><physicalDescription><note type="source content type">deposited</note>
<extent>9 p.</extent></physicalDescription><extension><dateIngested>2026-11-06</dateIngested></extension></mods>"""


def write(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


class ParseMods(unittest.TestCase):
    def test_pages_and_ingest_date(self):
        self.assertEqual(collect_govinfo.parse_mods(MODS), ("9", "2026-11-06"))

    def test_missing_fields_are_empty_not_zero(self):
        self.assertEqual(collect_govinfo.parse_mods("<mods></mods>"), ("", ""))
        self.assertEqual(collect_govinfo.parse_mods(None), ("", ""))
        self.assertEqual(collect_govinfo.parse_mods("<extent>1 online resource</extent>"), ("", ""))

    def test_time_on_the_ingest_date_is_dropped(self):
        self.assertEqual(collect_govinfo.parse_mods("<dateIngested>2010-09-21T12:00:00Z</dateIngested>")[1], "2010-09-21")


class LookUp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.calls = []
        self._real = collect_govinfo.get_text

        def fake(url, key, **kw):
            self.calls.append(url.rsplit("/", 2)[-2])
            return MODS
        collect_govinfo.get_text = fake
        self.versions = [{"package_id": f"BILLS-119hr{n}ih", "date_issued": f"2025-0{n}-01"} for n in (1, 2, 3)]

    def tearDown(self):
        collect_govinfo.get_text = self._real
        self._tmp.cleanup()

    def test_only_missing_printings_newest_first_within_the_budget(self):
        path = self.root / "govinfo.csv"
        write(path, [{"package_id": "BILLS-119hr3ih", "pages": "4", "date_ingested": "2025-03-05"}], collect_govinfo.FIELDS)
        used = collect_govinfo.look_up(path, "k", self.versions, budget=1)
        self.assertEqual(used, 1)
        self.assertEqual(self.calls, ["BILLS-119hr2ih"])  # hr 3 cached; hr 2 is the newest missing one
        rows = {r["package_id"]: r for r in read(path)}
        self.assertEqual(rows["BILLS-119hr3ih"]["pages"], "4")  # the cached row is kept as it was
        self.assertEqual((rows["BILLS-119hr2ih"]["pages"], rows["BILLS-119hr2ih"]["date_ingested"]), ("9", "2026-11-06"))

    def test_cache_merges_both_ways_without_replacing_rows(self):
        data, cache = self.root / "data.csv", self.root / "cache.csv"
        write(data, [{"package_id": "A", "pages": "1", "date_ingested": ""}], collect_govinfo.FIELDS)
        write(cache, [{"package_id": "A", "pages": "99", "date_ingested": ""},
                      {"package_id": "B", "pages": "2", "date_ingested": ""}], collect_govinfo.FIELDS)
        self.assertEqual(collect_govinfo.merge_cache(cache, data), 1)
        self.assertEqual([(r["package_id"], r["pages"]) for r in read(data)], [("A", "1"), ("B", "2")])
        self.assertEqual(collect_govinfo.merge_cache(None, data), 0)


if __name__ == "__main__":
    unittest.main()
