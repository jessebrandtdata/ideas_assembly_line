"""collect_warehouse.py against a local stand-in for the warehouse: a publication.v2.json pointer and
three small Parquet files written by the test itself, so no network is involved."""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
PROTO = HERE.parent
PREFIX = "generations/bill-family/testdigest"

VERSIONS = [
    # bill_id, version_code, package_id, version_date
    ("119-hr-1", "reported-in-house", "BILLS-119hr1rh", "2025-05-20T04:00:00Z"),
    ("119-hr-1", "engrossed-in-house", "BILLS-119hr1eh", "2025-05-22T04:00:00Z"),
    ("119-hr-1", "eas2", "BILLS-119hr1eas2", "2025-07-01T04:00:00Z"),
    ("119-hr-1", "public-law", None, ""),  # listed, not a printing: no package id
    ("119-hr-10779", "introduced-in-house", "BILLS-119hr10779ih", "2026-10-09T04:00:00Z"),
    ("119-hres-5", "introduced-in-house", "BILLS-119hres5ih", "2025-01-03T05:00:00Z"),  # outside the default types
    ("118-hr-1", "introduced-in-house", "BILLS-118hr1ih", "2023-01-09T05:00:00Z"),  # other Congress
]
BILLS = [
    ("119-hr-1", "One Big Beautiful Bill Act"),
    ("119-hr-10779", "A post office naming"),
    ("119-hres-5", "A resolution"),
]
SUMMARIES = [
    # bill_id, summary_version_code, action_date, action_desc, update_date
    ("119-hr-1", "00", "2025-05-20", "Introduced in House", "2025-05-22T17:15:29Z"),
    ("119-hr-1", "00", "2025-05-20", "Introduced in House", "2025-09-01T10:00:00Z"),  # a later revision, retained
    ("119-hr-1", "53", "2025-05-22", "Passed House", "2025-06-10T13:42:01Z"),
    ("119-hres-5", "00", "2025-01-03", "Introduced in House", "2025-01-10T00:00:00Z"),
    ("118-hr-1", "00", "2023-01-09", "Introduced in House", "2023-01-20T00:00:00Z"),
]


def write_parquet(con, path, columns, rows):
    con.execute(f"CREATE OR REPLACE TABLE t AS SELECT * FROM (VALUES {', '.join(['(' + ', '.join(['?'] * len(columns)) + ')'] * len(rows))}) "
                f"AS t({', '.join(columns)})", [v for row in rows for v in row])
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")


class CollectWarehouse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        gen = cls.tmp / "source" / PREFIX
        gen.mkdir(parents=True)
        con = duckdb.connect()
        write_parquet(con, gen / "bill_versions.parquet", ["bill_id", "version_code", "package_id", "version_date"], VERSIONS)
        write_parquet(con, gen / "congress_bills.parquet", ["bill_id", "title"], BILLS)
        write_parquet(con, gen / "bill_publisher_summaries.parquet",
                      ["bill_id", "summary_version_code", "action_date", "action_desc", "update_date"], SUMMARIES)
        con.close()
        (cls.tmp / "source" / "publication.v2.json").write_text(json.dumps({
            "format": "spicy-regs-publication", "version": 2,
            "families": {"bill-family": {"prefix": PREFIX, "publishedAt": "2026-11-06T04:26:02Z",
                                         "artifactDigest": "sha256:test"}}}))
        cls.data = cls.tmp / "data"
        subprocess.run([sys.executable, str(PROTO / "collect_warehouse.py"), "--source", str(cls.tmp / "source"),
                        "--data-dir", str(cls.data), "--congress", "119"], check=True, capture_output=True)
        cls.versions = cls.read("versions.csv")
        cls.summaries = cls.read("summaries.csv")

    @classmethod
    def read(cls, name):
        with (cls.data / name).open(newline="") as f:
            return list(csv.DictReader(f))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_versions_shape_matches_collect_py(self):
        self.assertEqual(list(self.versions[0].keys()),
                         ["package_id", "congress", "bill_type", "number", "version", "date_issued", "last_modified", "title"])

    def test_one_row_per_text_package_in_scope(self):
        ids = sorted(r["package_id"] for r in self.versions)
        # the public-law listing has no package, hres is outside the default types, 118 is another Congress
        self.assertEqual(ids, ["BILLS-119hr10779ih", "BILLS-119hr1eas2", "BILLS-119hr1eh", "BILLS-119hr1rh"])

    def test_version_code_is_the_package_suffix(self):
        by_id = {r["package_id"]: r for r in self.versions}
        self.assertEqual(by_id["BILLS-119hr1rh"]["version"], "rh")
        self.assertEqual(by_id["BILLS-119hr1eas2"]["version"], "eas2")
        self.assertEqual(by_id["BILLS-119hr10779ih"]["version"], "ih")

    def test_version_row_fields(self):
        r = next(r for r in self.versions if r["package_id"] == "BILLS-119hr1rh")
        self.assertEqual((r["congress"], r["bill_type"], r["number"]), ("119", "hr", "1"))
        self.assertEqual(r["date_issued"], "2025-05-20")  # the publisher's date, printed on the bill
        self.assertEqual(r["last_modified"], "")
        self.assertEqual(r["title"], "One Big Beautiful Bill Act")

    def test_summaries_shape_matches_collect_py(self):
        self.assertEqual(list(self.summaries[0].keys()),
                         ["congress", "bill_type", "number", "version_code", "action_desc", "action_date",
                          "update_date", "current_chapter", "last_summary_update_date"])

    def test_revisions_fold_to_first_and_latest(self):
        intro = next(r for r in self.summaries if r["number"] == "1" and r["version_code"] == "00")
        self.assertEqual(intro["last_summary_update_date"], "2025-05-22T17:15:29Z")  # first publication
        self.assertEqual(intro["update_date"], "2025-09-01T10:00:00Z")  # latest revision
        self.assertEqual(intro["action_desc"], "Introduced in House")
        self.assertEqual(intro["action_date"], "2025-05-20")

    def test_summaries_in_scope_only(self):
        keys = sorted((r["bill_type"], r["number"], r["version_code"]) for r in self.summaries)
        self.assertEqual(keys, [("hr", "1", "00"), ("hr", "1", "53")])

    def test_warehouse_json_records_the_generation(self):
        doc = json.loads((self.data / "warehouse.json").read_text())
        self.assertEqual(doc["prefix"], PREFIX)
        self.assertEqual(doc["published_at"], "2026-11-06T04:26:02Z")
        self.assertEqual((doc["versions"], doc["summaries"], doc["summaries_with_retained_revisions"]), (4, 2, 1))

    def test_delays_py_runs_on_the_output(self):
        # the join downstream is unchanged: it measures to last_summary_update_date
        (self.data / "pages.csv").write_text("package_id,pages\n")
        (self.data / "ingest.csv").write_text("package_id,date_ingested\nBILLS-119hr1rh,2025-05-21\n")
        subprocess.run([sys.executable, str(PROTO / "delays.py"), "--data-dir", str(self.data), "--as-of", "2026-11-06"],
                       check=True, capture_output=True)
        records = json.loads((self.data / "delays.json").read_text())["records"]
        reported = next(r for r in records if r["number"] == "1" and r["stage"] == "reported")
        self.assertEqual(reported["text_date"], "2025-05-21")  # ingest.csv still wins when present
        self.assertIsNone(reported["summary_date"])  # the fixture has no reported-stage summary
        passed = next(r for r in records if r["number"] == "1" and r["stage"] == "passed")
        self.assertEqual(passed["text_date"], "2025-05-22")  # no ingest row: the printed date
        self.assertEqual(passed["summary_date"], "2025-06-10")
        self.assertEqual(passed["lag_days"], 19)


if __name__ == "__main__":
    unittest.main()
