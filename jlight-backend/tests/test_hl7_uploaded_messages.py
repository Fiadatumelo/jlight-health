"""Regression tests based on the three uploaded synthetic HL7 v2.5.1 messages.

Identifiers and demographics are replaced with synthetic placeholders. These tests
exercise parsing only; they do not assert a live interface or persist patient data.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.interoperability import parse_hl7_v25_message, compare_hl7_order_to_result


ADT = (
    "MSH|^~\\&|SYNTH_HIS|SYNTH_HOSP|SYNTH_LAB|PATHOLOGY|202603011430||ADT^A01^ADT_A01|MSG_ADT_0001|P|2.5.1|||AL|NE\r"
    "EVN|A01|202603011430\r"
    "PID|1||SYNTH-MRN-0001^^^SYNTH_HOSP^MR||TEST^PATIENT||19800115|U\r"
    "PV1|1|I|WARD^0101^01^SYNTH_HOSP"
)

ORM = (
    "MSH|^~\\&|SYNTH_HIS|SYNTH_HOSP|SYNTH_LAB|PATHOLOGY|202603011400||ORM^O01^ORM_O01|MSG_ORM_0001|P|2.5.1|||AL|NE\r"
    "PID|1||SYNTH-MRN-0001^^^SYNTH_HOSP^MR||TEST^PATIENT||19800115|U\r"
    "PV1|1|I|WARD^0101^01^SYNTH_HOSP\r"
    "ORC|NW|SYNTH-ORD-5678^EPIC||SYNTH-GRP-001^EPIC|||||202603011400\r"
    "OBR|1|SYNTH-ORD-5678^EPIC||58410-2^CBC with Diff^LN|||202603011400"
)

ORU = (
    "MSH|^~\\&|SYNTH_LAB|SYNTH_HOSP|SYNTH_HIS|SYNTH_HOSP|202603011630||ORU^R01^ORU_R01|MSG_ORU_0001|P|2.5.1|||AL|NE\r"
    "PID|1||SYNTH-MRN-0001^^^SYNTH_HOSP^MR||TEST^PATIENT||19800115|U\r"
    "PV1|1|I|WARD^0101^01^SYNTH_HOSP\r"
    "ORC|RE|SYNTH-ORD-5678^EPIC|SYNTH-FIL-9012^SYNTH_LAB||CM\r"
    "OBR|1|SYNTH-ORD-5678^EPIC|SYNTH-FIL-9012^SYNTH_LAB|24323-8^CMP^LN|||202603011445|||||||||SYNTH_PROVIDER||||||202603011615||LAB|F\r"
    "OBX|1|NM|2345-7^Glucose^LN||98|mg/dL|70-100|N|||F\r"
    "OBX|2|NM|2160-0^Creatinine^LN||1.1|mg/dL|0.6-1.2|N|||F\r"
    "OBX|3|NM|3094-0^BUN^LN||18|mg/dL|7-20|N|||F\r"
    "OBX|4|NM|2951-2^Sodium^LN||140|meq/L|136-145|N|||F\r"
    "OBX|5|NM|2823-3^Potassium^LN||4.2|meq/L|3.5-5.0|N|||F\r"
    "OBX|6|NM|17861-6^Calcium^LN||9.4|mg/dL|8.5-10.5|N|||F\r"
    "OBX|7|NM|1742-6^ALT^LN||28|U/L|7-56|N|||F"
)


class UploadedHL7MessageRegressionTests(unittest.TestCase):
    def setUp(self):
        self.timezone = "America/New_York"

    def test_adt_a01_parses_with_configured_source_timezone(self):
        parsed = parse_hl7_v25_message(ADT, source_system="synthetic-hospital", source_timezone=self.timezone)
        self.assertEqual(parsed["message_type"], "ADT^A01^ADT_A01")
        self.assertEqual(parsed["domain"], "hospital")
        self.assertEqual(len(parsed["events"]), 1)
        self.assertEqual(parsed["events"][0]["event_type"], "admission")
        self.assertFalse(parsed["events"][0]["patient_link_verified"])
        self.assertNotIn("SYNTH-MRN-0001", str(parsed))

    def test_orm_orc_and_obr_are_one_order_event(self):
        parsed = parse_hl7_v25_message(ORM, source_system="synthetic-lis", source_timezone=self.timezone)
        self.assertEqual(len(parsed["events"]), 1)
        event = parsed["events"][0]
        self.assertEqual(event["event_type"], "laboratory_order")
        self.assertEqual(event["placer_order_number"], "SYNTH-ORD-5678^EPIC")
        self.assertEqual(event["service_identifier"]["code"], "58410-2")
        self.assertEqual(event["service_identifier"]["text"], "CBC with Diff")

    def test_oru_groups_observations_and_does_not_return_values(self):
        parsed = parse_hl7_v25_message(ORU, source_system="synthetic-lis", source_timezone=self.timezone)
        self.assertEqual(len(parsed["events"]), 1)
        event = parsed["events"][0]
        self.assertEqual(event["event_type"], "laboratory_result")
        self.assertEqual(event["placer_order_number"], "SYNTH-ORD-5678^EPIC")
        self.assertEqual(event["service_identifier"]["code"], "24323-8")
        self.assertEqual(event["observation_count"], 7)
        self.assertFalse(event["result_values_returned"])
        self.assertNotIn('"98"', str(parsed))
        self.assertNotIn('"1.1"', str(parsed))

    def test_same_order_but_different_test_is_flagged_for_review(self):
        order = parse_hl7_v25_message(ORM, source_system="synthetic-lis", source_timezone=self.timezone)["events"][0]
        result = parse_hl7_v25_message(ORU, source_system="synthetic-lis", source_timezone=self.timezone)["events"][0]
        comparison = compare_hl7_order_to_result(order, result)
        self.assertEqual(comparison["status"], "review_required")
        self.assertEqual(comparison["reason"], "ordered_test_does_not_match_result_test")
        self.assertEqual(comparison["ordered_test_code"], "58410-2")
        self.assertEqual(comparison["result_test_code"], "24323-8")

    def test_timezone_free_timestamp_requires_explicit_source_timezone(self):
        with self.assertRaisesRegex(ValueError, "configure source_timezone"):
            parse_hl7_v25_message(ADT, source_system="synthetic-hospital")

    def test_exact_order_and_test_match_is_accepted(self):
        order = parse_hl7_v25_message(ORM, source_system="synthetic-lis", source_timezone=self.timezone)["events"][0]
        matching_oru = ORU.replace("24323-8^CMP^LN", "58410-2^CBC with Diff^LN")
        result = parse_hl7_v25_message(matching_oru, source_system="synthetic-lis", source_timezone=self.timezone)["events"][0]
        self.assertEqual(compare_hl7_order_to_result(order, result)["status"], "matched")


if __name__ == "__main__":
    unittest.main(verbosity=2)
