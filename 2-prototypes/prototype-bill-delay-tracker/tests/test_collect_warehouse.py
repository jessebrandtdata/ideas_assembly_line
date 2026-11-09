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
    # bill_id, version_code, printing_id, package_id, version_date
    ("119-hr-1", "reported-in-house", "p:1rh", "BILLS-119hr1rh", "2025-05-20T04:00:00Z"),
    ("119-hr-1", "engrossed-in-house", "p:1eh", "BILLS-119hr1eh", "2025-05-22T04:00:00Z"),
    ("119-hr-1", "eas2", "p:1eas2", "BILLS-119hr1eas2", "2025-07-01T04:00:00Z"),
    ("119-hr-1", "public-law", "p:law", None, ""),  # listed, not a printing: no package id
    ("119-hr-10779", "introduced-in-house", "p:10779", "BILLS-119hr10779ih", "2026-10-09T04:00:00Z"),
    ("119-hres-5", "introduced-in-house", "p:hres5", "BILLS-119hres5ih", "2025-01-03T05:00:00Z"),  # a simple resolution
    ("118-hr-1", "introduced-in-house", "p:118hr1", "BILLS-118hr1ih", "2023-01-09T05:00:00Z"),  # another Congress
    ("118-s-7", "introduced-in-senate", "p:118s7", "BILLS-118s7is", ""),  # a printing with no date
]
SECTIONS = {
    # partition -> rows of (bill_id, printing_id, body_chars): parsed bill text, one row per section
    "119": [("119-hr-1", "p:1rh", 1000), ("119-hr-1", "p:1rh", 500), ("119-hr-1", "p:1eh", 700),
            ("119-hr-10779", "p:10779", 120)],
    "118": [("118-hr-1", "p:118hr1", 300)],
}
BILLS = [
    ("119-hr-1", "One Big Beautiful Bill Act"),
    ("119-hr-10779", "A post office naming"),
    ("119-hres-5", "A resolution"),
    ("118-hr-1", "Lower Energy Costs Act"),
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


def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


class CollectWarehouse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.source = cls.tmp / "source"
        gen = cls.source / PREFIX
        gen.mkdir(parents=True)
        con = duckdb.connect()
        write_parquet(con, gen / "bill_versions.parquet",
                      ["bill_id", "version_code", "printing_id", "package_id", "version_date"], VERSIONS)
        write_parquet(con, gen / "congress_bills.parquet", ["bill_id", "title"], BILLS)
        write_parquet(con, gen / "bill_publisher_summaries.parquet",
                      ["bill_id", "summary_version_code", "action_date", "action_desc", "update_date"], SUMMARIES)
        members = []  # bill_sections is partitioned by Congress, one member file each, as the real pointer lists it
        for congress, rows in SECTIONS.items():
            key = f"bill_sections/congress={congress}/part-000000.parquet"
            (gen / key).parent.mkdir(parents=True)
            write_parquet(con, gen / key, ["bill_id", "printing_id", "body_chars"], rows)
            members.append({"key": key, "partition": {"congress": congress}, "rows": len(rows)})
        con.close()
        (cls.source / "publication.v2.json").write_text(json.dumps({
            "format": "spicy-regs-publication", "version": 2,
            "families": {"bill-family": {"prefix": PREFIX, "publishedAt": "2026-11-06T04:26:02Z",
                                         "artifactDigest": "sha256:test",
                                         "tables": {"bill_sections.parquet": {"partitionColumns": ["congress"],
                                                                               "members": members}}}}}))
        cls.data = cls.tmp / "data"
        cls.collect(cls.data, "--congress", "118,119")
        cls.versions = read(cls.data / "119" / "versions.csv")
        cls.summaries = read(cls.data / "119" / "summaries.csv")

    @classmethod
    def collect(cls, data, *args):
        return subprocess.run([sys.executable, str(PROTO / "collect_warehouse.py"), "--source", str(cls.source),
                               "--data-dir", str(data), *args], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_one_folder_per_congress(self):
        self.assertEqual(sorted(p.name for p in self.data.iterdir() if p.is_dir()), ["118", "119"])
        self.assertEqual([r["package_id"] for r in read(self.data / "118" / "versions.csv")],
                         ["BILLS-118hr1ih", "BILLS-118s7is"])
        self.assertEqual([r["number"] for r in read(self.data / "118" / "summaries.csv")], ["1"])

    def test_versions_shape(self):
        self.assertEqual(list(self.versions[0].keys()),
                         ["package_id", "congress", "bill_type", "number", "version", "date_issued", "title",
                          "pages", "sections", "characters"])

    def test_size_from_parsed_sections(self):
        by_id = {r["package_id"]: r for r in self.versions}
        self.assertEqual((by_id["BILLS-119hr1rh"]["sections"], by_id["BILLS-119hr1rh"]["characters"]), ("2", "1500"))
        self.assertEqual((by_id["BILLS-119hr1eh"]["sections"], by_id["BILLS-119hr1eh"]["characters"]), ("1", "700"))
        self.assertEqual(by_id["BILLS-119hr1eas2"]["characters"], "")  # not parsed: empty, not zero
        self.assertEqual(by_id["BILLS-119hr1rh"]["pages"], "")  # the warehouse publishes no page count
        r118 = next(r for r in read(self.data / "118" / "versions.csv") if r["package_id"] == "BILLS-118hr1ih")
        self.assertEqual(r118["characters"], "300")  # read from the 118th's own partition

    def test_one_row_per_text_package_in_scope(self):
        ids = sorted(r["package_id"] for r in self.versions)
        # the public-law listing has no package; every bill type is in scope by default
        self.assertEqual(ids, ["BILLS-119hr10779ih", "BILLS-119hr1eas2", "BILLS-119hr1eh", "BILLS-119hr1rh",
                               "BILLS-119hres5ih"])

    def test_version_code_is_the_package_suffix(self):
        by_id = {r["package_id"]: r for r in self.versions}
        self.assertEqual(by_id["BILLS-119hr1rh"]["version"], "rh")
        self.assertEqual(by_id["BILLS-119hr1eas2"]["version"], "eas2")
        self.assertEqual(by_id["BILLS-119hr10779ih"]["version"], "ih")
        self.assertEqual(by_id["BILLS-119hres5ih"]["version"], "ih")

    def test_version_row_fields(self):
        r = next(r for r in self.versions if r["package_id"] == "BILLS-119hr1rh")
        self.assertEqual((r["congress"], r["bill_type"], r["number"]), ("119", "hr", "1"))
        self.assertEqual(r["date_issued"], "2025-05-20")  # the publisher's date, printed on the bill
        self.assertEqual(r["title"], "One Big Beautiful Bill Act")

    def test_undated_printing_is_kept_with_an_empty_date(self):
        r = next(r for r in read(self.data / "118" / "versions.csv") if r["package_id"] == "BILLS-118s7is")
        self.assertEqual(r["date_issued"], "")

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
        self.assertEqual(keys, [("hr", "1", "00"), ("hr", "1", "53"), ("hres", "5", "00")])

    def test_warehouse_json_records_the_generation(self):
        doc = json.loads((self.data / "119" / "warehouse.json").read_text())
        self.assertEqual(doc["prefix"], PREFIX)
        self.assertEqual(doc["published_at"], "2026-11-06T04:26:02Z")
        self.assertEqual(doc["congress"], "119")
        self.assertEqual((doc["versions"], doc["summaries"], doc["summaries_with_retained_revisions"]), (5, 3, 1))

    def test_bill_types_narrow_the_scope(self):
        data = self.tmp / "narrow"
        self.collect(data, "--congress", "119", "--bill-types", "hr,s")
        self.assertNotIn("BILLS-119hres5ih", [r["package_id"] for r in read(data / "119" / "versions.csv")])

    def test_unknown_bill_type_is_refused(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.collect(self.tmp / "bad", "--congress", "119", "--bill-types", "hr,xyz")

    def test_all_reads_every_congress_the_warehouse_lists(self):
        data = self.tmp / "all"
        self.collect(data, "--congress", "all")
        self.assertEqual(sorted(p.name for p in data.iterdir() if p.is_dir()), ["118", "119"])

    def test_congress_with_no_rows_is_skipped_and_never_emptied(self):
        data = self.tmp / "empty"
        (data / "117").mkdir(parents=True)
        (data / "117" / "versions.csv").write_text("kept\n")
        out = self.collect(data, "--congress", "116,117")
        self.assertEqual((data / "117" / "versions.csv").read_text(), "kept\n")
        self.assertFalse((data / "116").exists())
        self.assertIn("skipped", out.stderr)

    def test_default_refreshes_the_folders_on_disk(self):
        data = self.tmp / "default"
        (data / "118").mkdir(parents=True)
        self.collect(data)
        self.assertTrue((data / "118" / "warehouse.json").exists())

    def test_delays_py_runs_on_the_output(self):
        # delays.py reads this output alone: lags from the printed date to last_summary_update_date, sizes from versions.csv
        subprocess.run([sys.executable, str(PROTO / "delays.py"), "--data-dir", str(self.data), "--as-of", "2026-11-06"],
                       check=True, capture_output=True)
        doc = json.loads((self.data / "119" / "delays.json").read_text())
        records = doc["records"]
        self.assertEqual(doc["measures"], ["characters", "sections"])  # no page count, so no pages measure
        reported = next(r for r in records if r["number"] == "1" and r["stage"] == "reported")
        self.assertEqual(reported["text_date"], "2025-05-20")  # the printed date
        self.assertEqual(reported["characters"], 1500)
        self.assertIsNone(reported["summary_date"])  # the fixture has no reported-stage summary
        passed = next(r for r in records if r["number"] == "1" and r["stage"] == "passed")
        self.assertEqual(passed["text_date"], "2025-05-22")
        self.assertEqual(passed["summary_date"], "2025-06-10")
        self.assertEqual(passed["lag_days"], 19)
        index = json.loads((self.data / "congresses.json").read_text())["congresses"]
        self.assertEqual([e["congress"] for e in index], ["119", "118"])


if __name__ == "__main__":
    unittest.main()
