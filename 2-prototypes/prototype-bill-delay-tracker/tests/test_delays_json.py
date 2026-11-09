import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTO = HERE.parent


class DelaysJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        cls.tmp = cls.root / "119"
        cls.tmp.mkdir()
        for name in ("versions.csv", "summaries.csv"):
            shutil.copy(HERE / "fixture" / "119" / name, cls.tmp / name)
        # a second, ended Congress with no size columns at all, written here
        old = cls.root / "118"
        old.mkdir()
        (old / "versions.csv").write_text(
            "package_id,congress,bill_type,number,version,date_issued,last_modified,title\n"
            "BILLS-118hr1ih,118,hr,1,ih,2023-01-09,,One\n"
            "BILLS-118hr2ih,118,hr,2,ih,2023-01-10,,Two\n"
            "BILLS-118hres3ih,118,hres,3,ih,2023-02-01,,Three\n"
            "BILLS-118s4is,118,s,4,is,,,Undated\n"
            "BILLS-118s5is,118,s,5,is,2064-03-01,,Misprinted year\n"
            "BILLS-118s6is,118,s,6,is,2023-03-01,,Summarized only as a law\n")
        (old / "summaries.csv").write_text(
            "congress,bill_type,number,version_code,action_desc,action_date,update_date,current_chapter,last_summary_update_date\n"
            "118,hr,1,00,Introduced in House,2023-01-09,2023-01-29T00:00:00Z,,2023-01-29T00:00:00Z\n"
            "118,hres,3,00,Introduced in House,2023-02-01,2025-02-01T00:00:00Z,,2025-02-01T00:00:00Z\n"
            "118,s,6,49,Public Law,2024-06-25,2024-08-29T00:00:00Z,,2024-08-29T00:00:00Z\n")
        subprocess.run([sys.executable, str(PROTO / "delays.py"), "--data-dir", str(cls.root),
                        "--as-of", "2026-10-14"], check=True, capture_output=True)
        cls.doc = json.loads((cls.tmp / "delays.json").read_text())
        cls.records = cls.doc["records"]
        cls.old = json.loads((old / "stats.json").read_text())
        cls.index = json.loads((cls.root / "congresses.json").read_text())["congresses"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_index_lists_every_congress_newest_first(self):
        self.assertEqual([e["congress"] for e in self.index], ["119", "118"])
        e = self.index[1]
        self.assertEqual((e["start"], e["end"], e["ended"]), ("2023-01-03", "2025-01-02", True))
        self.assertFalse(self.index[0]["ended"])
        self.assertEqual(e["file"], "118/delays.js")

    def test_index_script_matches_the_json(self):
        js = (self.root / "congresses.js").read_text()
        body = js[js.index("JSON.parse(") + len("JSON.parse("):js.rindex(")")]
        self.assertEqual(json.loads(json.loads(body))["congresses"], self.index)

    def test_delays_js_registers_under_its_congress(self):
        js = (self.root / "118" / "delays.js").read_text()
        self.assertIn('(window.BILL_DELAYS = window.BILL_DELAYS || {})["118"] = JSON.parse(', js)

    def test_comparison_measures_from_the_printed_date_per_type(self):
        c = self.old["comparison"]
        self.assertEqual(c["all"]["introduced_bills"], 4)  # the undated s4 and the misprinted s5 are left out
        self.assertEqual(c["all"]["introduced_summarized"], 3)  # hr 1, hres 3, and s 6 by its Public Law summary
        self.assertEqual(c["hr"]["median_lag_printed"], 20)  # 2023-01-09 to 2023-01-29
        self.assertEqual(c["hres"]["introduced_bills"], 1)
        self.assertEqual(c["all"]["summaries_after_end"], 1)  # hres 3, dated after 2025-01-02

    def test_undated_versions_are_counted_not_measured(self):
        self.assertEqual(self.old["versions_without_date"], 1)
        self.assertEqual(self.old["versions_dated_after_as_of"], 1)  # the 2064 misprint, as of 2026-10-14
        self.assertEqual(self.old["text_versions"], 4)
        self.assertEqual(self.old["measures"], [])  # no size columns, no size measures

    def test_lag_runs_to_the_first_summary_whatever_version_it_describes(self):
        # like S. 1869 of the 115th: introduced text printed, one CRS summary, at Public Law
        c = self.old["comparison"]
        self.assertEqual(c["all"]["summarized_other_stage"], 1)
        self.assertEqual(c["s"]["introduced_summarized"], 1)
        self.assertEqual(c["s"]["median_lag_printed"], 547)  # 2023-03-01 to 2024-08-29
        records = json.loads((self.root / "118" / "delays.json").read_text())["records"]
        r = next(r for r in records if r["type"] == "s" and r["number"] == "6")
        self.assertEqual((r["stage"], r["summary_date"], r["lag_days"], r["summary_stage"]),
                         ("introduced", "2024-08-29", 547, "enrolled"))
        hr1 = next(r for r in records if r["type"] == "hr" and r["number"] == "1")
        self.assertNotIn("summary_stage", hr1)  # its first summary is the introduced one
        with (self.root / "118" / "awaiting.csv").open(newline="") as f:
            self.assertNotIn(("s", "6"), [(w["bill_type"], w["number"]) for w in csv.DictReader(f)])
        self.assertEqual(self.old["introduced_awaiting_summary"], 1)  # only hr 2 waits
        self.assertEqual(self.old["bills_summarized"], 3)  # hr 1, hres 3 and s 6

    def test_bill_types_listed_from_the_data(self):
        self.assertEqual(sorted(self.old["bill_types"]), ["hr", "hres", "s"])

    def test_envelope(self):
        self.assertEqual(self.doc["as_of"], "2026-10-14")
        self.assertEqual(self.doc["congress"], "119")

    def test_one_record_per_version(self):
        # fixture: hr1 rh + eh + eah (later passed-stage edition), hr10786 ih, hr10779 ih, plus one unmapped rfs edition of hr1
        self.assertEqual(len(self.records), 6)
        keys = sorted((r["type"], r["number"], r["stage"] or "-") for r in self.records)
        self.assertEqual(keys, [("hr", "1", "-"), ("hr", "1", "-"), ("hr", "1", "passed"), ("hr", "1", "reported"),
                                ("hr", "10779", "introduced"), ("hr", "10786", "introduced")])

    def test_later_edition_of_a_staged_stage_has_no_stage(self):
        r = next(r for r in self.records if r["text_date"] == "2025-07-02")  # the printed date
        self.assertIsNone(r["stage"])
        self.assertIsNone(r["lag_days"])
        self.assertEqual(sum(1 for r in self.records if r["stage"] == "passed"), 1)

    def test_unmapped_version_keeps_its_size_and_has_no_stage(self):
        r = next(r for r in self.records if r["stage"] is None and r["text_date"] == "2025-05-23")
        self.assertEqual((r["pages"], r["sections"], r["characters"]), (900, 870, 1650000))
        self.assertIsNone(r["lag_days"])

    def test_measures_are_the_size_columns_with_values_in_order(self):
        self.assertEqual(self.doc["measures"], ["pages", "characters", "sections"])
        r = next(r for r in self.records if r["number"] == "10779")
        self.assertEqual((r["pages"], r["sections"], r["characters"]), (None, 2, 1200))
        stats = json.loads((self.tmp / "stats.json").read_text())
        self.assertEqual(stats["size"]["characters"]["total"], 1920000 + 1801000 + 9100 + 1200 + 1650000)
        self.assertEqual(stats["size"]["pages"]["versions_with_value"], 3)

    def test_summary_before_text_counted(self):
        # fixture summaries.csv has an Introduced summary for hr 99999, which has no text version
        self.assertEqual(self.doc["summary_before_text"], {"introduced": 1})

    def test_summarized_record(self):
        r = next(r for r in self.records if r["number"] == "1" and r["stage"] == "reported")
        self.assertEqual(r["text_date"], "2025-05-20")  # the date printed on the bill
        self.assertNotIn("printed_date", r)  # one date now, so no second field
        self.assertEqual(r["summary_date"], "2025-09-22")
        self.assertEqual(r["lag_days"], 125)
        self.assertEqual(r["pages"], 1118)
        self.assertTrue(r["reported"])
        self.assertEqual(r["title"], "One Big Beautiful Bill Act")

    def test_summary_date_is_last_summary_update_not_record_update(self):
        # fixture: hr1 Passed House has updateDate 2025-06-16 and lastSummaryUpdateDate 2025-06-10
        r = next(r for r in self.records if r["number"] == "1" and r["stage"] == "passed")
        self.assertEqual(r["summary_date"], "2025-06-10")
        self.assertEqual(r["lag_days"], 19)  # from the eh printed date 2025-05-22

    def test_envelope_counts_versions_left_out(self):
        self.assertEqual(self.doc["versions_without_date"], 0)
        self.assertEqual(self.doc["versions_dated_after_as_of"], 0)

    def test_waiting_record_has_nulls(self):
        r = next(r for r in self.records if r["number"] == "10779")
        self.assertIsNone(r["summary_date"])
        self.assertIsNone(r["lag_days"])
        self.assertIsNone(r["pages"])
        self.assertFalse(r["reported"])

    def test_count_matches_csvs(self):
        import csv
        with (self.tmp / "delays.csv").open(newline="") as f:
            delays = list(csv.DictReader(f))
        with (self.tmp / "awaiting.csv").open(newline="") as f:
            awaiting = list(csv.DictReader(f))
        waiting = [r for r in self.records if r["lag_days"] is None]
        self.assertEqual(len([r for r in self.records if r["lag_days"] is not None]), len(delays))
        # awaiting.csv only lists the introduced stage; the json lists waiting at every stage
        self.assertGreaterEqual(len(waiting), len(awaiting))


if __name__ == "__main__":
    unittest.main()
