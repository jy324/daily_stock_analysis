# -*- coding: utf-8 -*-
"""Tests for prompt version-hash helper (workflow D.2)."""

import hashlib
import unittest

from src.utils.version_attribution import compute_prompt_version_hash


class ComputePromptVersionHashTestCase(unittest.TestCase):
    def test_returns_16_hex_chars(self):
        h = compute_prompt_version_hash("hello prompt")
        self.assertEqual(len(h), 16)
        int(h, 16)  # must be valid hex

    def test_is_first_16_of_sha256(self):
        text = "你是一位投资分析师"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        self.assertEqual(compute_prompt_version_hash(text), expected)

    def test_is_stable_for_same_text(self):
        self.assertEqual(
            compute_prompt_version_hash("same"), compute_prompt_version_hash("same")
        )

    def test_changes_when_text_changes(self):
        self.assertNotEqual(
            compute_prompt_version_hash("template v1"),
            compute_prompt_version_hash("template v2"),
        )

    def test_none_or_empty_returns_none(self):
        self.assertIsNone(compute_prompt_version_hash(None))
        self.assertIsNone(compute_prompt_version_hash(""))


if __name__ == "__main__":
    unittest.main()
