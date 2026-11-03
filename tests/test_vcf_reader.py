"""
Unit tests for VcfReader with malaria multi-allelic and indel datasets.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from vcfscape.core.vcf_reader import VcfReader

DEMO_VCF = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "examples", "pf3d7_surveillance_demo.vcf")
)

class TestVcfReader(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.reader = VcfReader(DEMO_VCF)

    def test_samples_loaded(self):
        self.assertEqual(len(self.reader.samples), 24)
        self.assertIn("KL_001", self.reader.samples)
        self.assertIn("AS_001", self.reader.samples)
        self.assertIn("BS_001", self.reader.samples)

    def test_variant_counts(self):
        records = self.reader.get_records()
        self.assertGreaterEqual(len(records), 10)

    def test_multiallelic_parsing(self):
        # Find k13 C580Y with ALT T,A
        k13 = None
        for r in self.reader.get_records():
            if r.pos == 1725259:
                k13 = r
                break
        self.assertIsNotNone(k13)
        self.assertTrue(k13.is_multiallelic)
        self.assertEqual(k13.alt, ["T", "A"])
        self.assertEqual(k13.num_alleles, 3)
        self.assertIsNotNone(k13.drug_annotation)
        self.assertEqual(k13.drug_annotation.drug, "Artemisinin")

    def test_complex_indel_parsing(self):
        # Find microsatellite poly indel
        indel = None
        for r in self.reader.get_records():
            if r.pos == 974200:
                indel = r
                break
        self.assertIsNotNone(indel)
        self.assertTrue(indel.is_indel)
        self.assertTrue(indel.is_multiallelic)
        self.assertEqual(indel.var_type, "Multi-Allelic INDEL")
        self.assertEqual(len(indel.alt), 3)

    def test_filtering(self):
        # Filter for only drug resistant loci
        drug_vars = self.reader.filter_records(variant_type="DRUG_RESISTANT")
        self.assertGreater(len(drug_vars), 0)
        for v in drug_vars:
            self.assertIsNotNone(v.drug_annotation)


if __name__ == "__main__":
    unittest.main()
