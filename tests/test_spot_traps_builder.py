"""Unit tests verifying docs/spot_traps builder and generated data/spot_traps.json."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from tools.build_spot_traps import DOCS_DIR, OUT_PATH, build_bundle


class TestSpotTrapsBuilder(unittest.TestCase):
    def test_build_bundle_and_committed_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_tmp = pathlib.Path(tmp) / "spot_traps.json"
            bundle = build_bundle(docs_dir=DOCS_DIR, out_path=out_tmp)
            self.assertTrue(out_tmp.exists())
            parsed = json.loads(out_tmp.read_text(encoding="utf-8"))

        self.assertEqual(bundle["mindset"], "1.0x_spot_only")
        self.assertEqual(len(bundle["guardrails"]), 7)
        self.assertEqual(len(bundle["pillars"]), 5)
        self.assertEqual(len(bundle["items"]), 17)

        ids = [it["id"] for it in bundle["items"]]
        expected_ids = [f"trap_{i:02d}" for i in range(1, 17)] + ["bonus_b1"]
        self.assertEqual(ids, expected_ids)

        id_set = set(ids)
        for it in bundle["items"]:
            self.assertTrue(it["title"])
            self.assertTrue(it["short_title"])
            self.assertTrue(it["core_mistake"], f"missing core_mistake on {it['id']}")
            self.assertTrue(it["key_defense"], f"missing key_defense on {it['id']}")
            self.assertTrue(it["body_md"], f"missing body_md on {it['id']}")
            self.assertGreaterEqual(len(it["quick_steps"]), 3, f"few quick_steps on {it['id']}")
            for rel in it["related_traps"]:
                self.assertIn(rel, id_set, f"broken related_traps ref {rel} in {it['id']}")

        bonus = next(it for it in bundle["items"] if it["id"] == "bonus_b1")
        self.assertIn("Prophecy-Based TA", bonus["body_md"])
        self.assertIn("If-Then", bonus["body_md"])

        # Committed artifact matches builder schema cleanly
        committed = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed["items"], parsed["items"])
        self.assertEqual(committed["guardrails"], parsed["guardrails"])


if __name__ == "__main__":
    unittest.main()
