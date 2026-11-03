"""
Unit tests for Malaria Molecular Surveillance Knowledgebase.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from vcfscape.core.malaria_db import MalariaAnnotationDB

class TestMalariaAnnotationDB(unittest.TestCase):

    def test_k13_c580y_lookup(self):
        marker = MalariaAnnotationDB.lookup("Pf3D7_13_v3", 1725259, "C", "T")
        self.assertIsNotNone(marker)
        self.assertEqual(marker.gene, "Pfkelch13")
        self.assertEqual(marker.mutation, "C580Y")
        self.assertEqual(marker.drug, "Artemisinin")
        self.assertIn("Validated", marker.status)

    def test_crt_k76t_lookup(self):
        marker = MalariaAnnotationDB.lookup("Pf3D7_07_v3", 403625, "C", "T")
        self.assertIsNotNone(marker)
        self.assertEqual(marker.gene, "Pfcrt")
        self.assertEqual(marker.mutation, "K76T")
        self.assertEqual(marker.drug, "Chloroquine")

    def test_mdr1_n86y_lookup(self):
        marker = MalariaAnnotationDB.lookup("Pf3D7_05_v3", 958145, "A", "T")
        self.assertIsNotNone(marker)
        self.assertEqual(marker.gene, "Pfmdr1")
        self.assertEqual(marker.mutation, "N86Y")

    def test_dhps_a437g_lookup(self):
        marker = MalariaAnnotationDB.lookup("Pf3D7_08_v3", 549685, "G", "C")
        self.assertIsNotNone(marker)
        self.assertEqual(marker.gene, "Pfdhps")
        self.assertEqual(marker.mutation, "A437G")
        self.assertEqual(marker.drug, "Sulfadoxine")

    def test_chrom_normalization(self):
        self.assertEqual(MalariaAnnotationDB.normalize_chrom("13"), "Pf3D7_13_v3")
        self.assertEqual(MalariaAnnotationDB.normalize_chrom("chr7"), "Pf3D7_07_v3")
        self.assertEqual(MalariaAnnotationDB.normalize_chrom("Pf3D7_05_v3"), "Pf3D7_05_v3")

    def test_unknown_region_fallback(self):
        # Locus inside Pfkelch13 region but not a known marker
        marker = MalariaAnnotationDB.lookup("Pf3D7_13_v3", 1726000, "A", "G")
        self.assertIsNotNone(marker)
        self.assertEqual(marker.gene, "Pfkelch13")
        self.assertEqual(marker.status, "Regional Locus")


if __name__ == "__main__":
    unittest.main()
