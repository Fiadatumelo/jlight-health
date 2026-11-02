import csv
import tempfile
import unittest
from pathlib import Path

from engine.who_tb_surveillance import load_who_tb_bundle, build_tb_intelligence_cards, WHO_FILES


class WhoTbSurveillanceTests(unittest.TestCase):
    def _write_fixture(self, root, prefix, columns, rows):
        path = root / f"{prefix}_fixture.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted(columns))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_loads_country_aggregate_and_preserves_unknowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for key, (prefix, columns) in WHO_FILES.items():
                rows = [{"iso3": "ZAF", "country": "South Africa", "year": "2023"}]
                rows[0].update({column: "" for column in columns - {"iso3", "country", "year"}})
                if key == "burden":
                    rows[0].update({"e_inc_num": "100", "e_inc_num_lo": "80", "e_inc_num_hi": "120", "e_inc_100k": "10", "e_mort_num": "5", "e_mort_100k": "0.5"})
                    prior = dict(rows[0], year="2022", e_inc_num="125")
                    self._write_fixture(root, prefix, columns, [prior, rows[0]])
                elif key == "mdr_rr":
                    rows[0].update({"e_rr_pct_new": "3.6", "e_rr_pct_ret": "17", "e_inc_rr_num": "14"})
                    self._write_fixture(root, prefix, columns, rows)
                else:
                    self._write_fixture(root, prefix, columns, rows)
            bundle = load_who_tb_bundle(root)
            self.assertEqual(bundle["iso3"], "ZAF")
            self.assertEqual(bundle["latest_year"], 2023)
            self.assertEqual(bundle["burden"]["estimated_incidence_cases"], 100)
            self.assertEqual(bundle["burden"]["incidence_change_vs_previous_year_percent"], -20.0)
            self.assertIsNone(bundle["burden"]["case_fatality_ratio_percent"])
            self.assertFalse(bundle["interpretation"]["patient_matching_permitted"])
            cards = build_tb_intelligence_cards(bundle)
            self.assertEqual(len(cards), 2)
            self.assertTrue(all(card["requires_human_review"] for card in cards))

    def test_rejects_missing_country_burden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for key, (prefix, columns) in WHO_FILES.items():
                rows = [{"iso3": "AFG", "country": "Afghanistan", "year": "2023"}]
                rows[0].update({column: "" for column in columns - {"iso3", "country", "year"}})
                self._write_fixture(root, prefix, columns, rows)
            with self.assertRaisesRegex(ValueError, "No WHO burden rows"):
                load_who_tb_bundle(root)


if __name__ == "__main__":
    unittest.main()
