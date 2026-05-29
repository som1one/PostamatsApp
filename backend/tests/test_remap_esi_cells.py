"""Тесты логики сопоставления меток ячеек с номерами ESI.

Проверяем натуральную сортировку меток (I10 после I9, не после I1) и
разбор явного --map.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from scripts.remap_esi_cells_to_numbers import (
    _extract_esi_cell_ids,
    _natural_key,
    _parse_explicit_map,
)


class NaturalSortTests(unittest.TestCase):
    def test_orders_labels_naturally(self) -> None:
        labels = ["I10", "A2", "I9", "A1", "B1", "I8", "A3", "C2", "C1", "B2", "I12", "I11"]
        ordered = sorted(labels, key=_natural_key)
        self.assertEqual(
            ordered,
            ["A1", "A2", "A3", "B1", "B2", "C1", "C2", "I8", "I9", "I10", "I11", "I12"],
        )

    def test_numeric_suffix_beats_lexical(self) -> None:
        # I9 должен идти раньше I10 (числа, не строки).
        self.assertLess(_natural_key("I9"), _natural_key("I10"))


class EsiCellIdsTests(unittest.TestCase):
    def test_extracts_and_sorts_numeric_ids(self) -> None:
        snapshot = {
            "cells": {
                "10": {"state": "unassigned"},
                "2": {"state": "assigned"},
                "1": {"state": "assigned"},
                "12": {"state": "unassigned"},
            }
        }
        self.assertEqual(_extract_esi_cell_ids(snapshot), ["1", "2", "10", "12"])

    def test_empty_for_bad_snapshot(self) -> None:
        self.assertEqual(_extract_esi_cell_ids(None), [])
        self.assertEqual(_extract_esi_cell_ids({}), [])


class ParseMapTests(unittest.TestCase):
    def test_parses_pairs_uppercases_labels(self) -> None:
        out = _parse_explicit_map("a1=1, a2=2 ,I8=8")
        self.assertEqual(out, {"A1": "1", "A2": "2", "I8": "8"})

    def test_empty(self) -> None:
        self.assertEqual(_parse_explicit_map(None), {})
        self.assertEqual(_parse_explicit_map(""), {})


if __name__ == "__main__":
    unittest.main()
