"""Charter Score for charter files, and signed attestations.
Run: python -m pytest tests  (or python -m unittest discover tests)"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from census import attest
from census.charter import score_charter, validate
from census.signals import PILLAR_MAX

FIX = Path(__file__).parent / "fixtures"
EXAMPLE_RAW = (FIX / "estimate-intake.charter.json").read_bytes()
EXAMPLE = json.loads(EXAMPLE_RAW)
SCHEMA = json.loads((FIX / "charter-0.1.2.schema.json").read_text())


def pts(c):
    return [p["points"] for p in score_charter(c)["pillars"]]


class Score(unittest.TestCase):
    def test_weights_are_the_census_weights(self):
        self.assertEqual([p["max"] for p in score_charter(EXAMPLE)["pillars"]], PILLAR_MAX)
        self.assertEqual(sum(PILLAR_MAX), 100)

    def test_spec_example_scores_100(self):
        s = score_charter(EXAMPLE)
        self.assertEqual(s["charter_score"], 100, s)
        self.assertTrue(all(p["result"] == "pass" for p in s["pillars"]))

    def test_tiers(self):
        c = copy.deepcopy(EXAMPLE)
        c["escalation_recipient"].pop("backup")             # 2: named, no backup -> 6
        for i in c["scope"]["never_do"]:                    # 4: instructed only -> 8
            i["enforcement"] = "instructed"; i.pop("tool", None)
        c["systems"][1].pop("reversal")                      # 5: write tool without reversal owner -> 6
        c["constraints"].pop("max_tool_calls_per_run")       # 8: no limits -> 5
        c["escalation_rules"] = c["escalation_rules"][:2]    # 7: 2 of 4 -> 8
        self.assertEqual(pts(c), [20, 6, 15, 8, 6, 5, 8, 5])
        s = score_charter(c)
        self.assertEqual(s["charter_score"], 73)
        self.assertEqual([p["result"] for p in s["pillars"]],
                         ["pass", "partial", "pass", "partial", "partial", "pass", "partial", "partial"])

    def test_group_owner_and_missing_approver(self):
        c = copy.deepcopy(EXAMPLE)
        c["owner"]["identity"] = "role:ops"
        c.pop("approval_authority")
        self.assertEqual(pts(c)[:3], [4, 10, 0])

    def test_read_only_needs_no_approver_or_inputs(self):
        c = copy.deepcopy(EXAMPLE)
        c["systems"] = [{"tool": "rate_card_lookup", "access": "read"}]
        c.pop("approval_authority"); c.pop("inputs"); c.pop("constraints")
        self.assertEqual(pts(c)[2], 15)
        self.assertEqual(pts(c)[5], 5)
        self.assertEqual(pts(c)[7], 5)

    def test_irreversible_not_held_zeroes_pillar_8(self):
        c = copy.deepcopy(EXAMPLE)
        c["escalation_rules"][3]["action"] = "notify_and_continue"
        self.assertEqual(pts(c)[7], 0)
        c = copy.deepcopy(EXAMPLE)
        c["systems"].append({"tool": "send_invoice", "access": "irreversible"})
        c["constraints"].pop("irreversible_actions")
        self.assertEqual(pts(c)[7], 0)

    def test_empty_draft_scores_low_and_validates(self):
        c = {"spec": "delegation-charter/0.1.2", "id": "chr_x", "version": 0, "name": "x", "state": "draft",
             "owner": {"identity": None}, "escalation_recipient": {"identity": None},
             "scope": {"never_do": []}, "systems": [], "escalation_rules": []}
        self.assertEqual(validate(c, SCHEMA), [])
        self.assertEqual(pts(c), [0, 0, 15, 0, 10, 5, 0, 5])

    def test_schema_error_messages_are_readable(self):
        c = copy.deepcopy(EXAMPLE); c["escalation_rules"] = c["escalation_rules"][1:]
        errs = validate(c, SCHEMA)
        self.assertTrue(any("out_of_scope" in e for e in errs), errs)


class Attestation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pub = attest.generate_key(self.tmp / "k.pem")
        self.key = attest.load_key(self.tmp / "k.pem")
        self.product = {"product_slug": "estimate-intake",
                        "accountable_person": {"name": "Ana Ruiz", "role": "Operations manager"}}

    def test_round_trip(self):
        att = attest.build(EXAMPLE_RAW, self.product, self.key)
        self.assertEqual(att["charter_score"], 100)
        self.assertEqual(attest.verify(att, EXAMPLE_RAW, self.pub), [])
        self.assertEqual((self.tmp / "k.pem").stat().st_mode & 0o777, 0o600)

    def test_edited_score_is_caught(self):
        att = attest.build(EXAMPLE_RAW, self.product, self.key)
        att["charter_score"] = 99
        errs = attest.verify(att, EXAMPLE_RAW)
        self.assertTrue(any("signature" in e for e in errs))
        self.assertTrue(any("recomputed" in e for e in errs))

    def test_changed_charter_is_caught(self):
        att = attest.build(EXAMPLE_RAW, self.product, self.key)
        errs = attest.verify(att, EXAMPLE_RAW.replace(b"Estimate intake", b"Estimate intake!"))
        self.assertTrue(any("charter_hash" in e for e in errs))

    def test_other_key_is_caught(self):
        other = attest.generate_key(self.tmp / "other.pem")
        att = attest.build(EXAMPLE_RAW, self.product, self.key)
        self.assertTrue(any("different key" in e for e in attest.verify(att, EXAMPLE_RAW, other)))

    def test_existing_key_is_never_overwritten(self):
        with self.assertRaises(FileExistsError):
            attest.generate_key(self.tmp / "k.pem")


if __name__ == "__main__":
    unittest.main()
