"""
Unit tests for CohortManager and population genetics statistics computations.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from vcfscape.core.vcf_reader import VcfReader
from vcfscape.core.cohorts import CohortManager

DEMO_VCF = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "examples", "pf3d7_surveillance_demo.vcf")
)

class TestCohorts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.reader = VcfReader(DEMO_VCF)

    def setUp(self):
        self.manager = CohortManager(self.reader.samples)

    def test_default_cohort_creation(self):
        # By default, no automatic initial cohorts are created (only "All Samples" baseline exists)
        self.assertIn("All Samples", self.manager.cohorts)
        self.assertEqual(len(self.manager.cohorts), 1)

    def test_allele_frequency_calculation(self):
        rec = self.reader.get_records()[0]  # k13 C580Y
        stats = self.manager.calculate_variant_stats(
            {
                "genotypes": rec.genotypes,
                "depths": rec.depths,
                "ad": rec.ad,
            },
            rec.num_alleles
        )

        all_stats = stats["All Samples"]
        self.assertEqual(all_stats.total_samples, 24)
        self.assertEqual(all_stats.missing_samples, 0)
        self.assertAlmostEqual(all_stats.missingness_rate, 0.0)

        # Sum of allele frequencies should be approximately 1.0
        sum_af = sum(all_stats.allele_frequencies.values())
        self.assertAlmostEqual(sum_af, 1.0, places=3)

        # Check mean depth > 0
        self.assertGreater(all_stats.mean_depth, 20.0)

    def test_cohort_toggling(self):
        # Add custom cohort and toggle it
        self.manager.add_cohort("Cohort KL", self.reader.samples[:8])
        active_before = self.manager.cohorts["Cohort KL"].active
        new_state = self.manager.toggle_cohort("Cohort KL")
        self.assertNotEqual(active_before, new_state)

    def test_cohort_cloning(self):
        if "Cohort KL" not in self.manager.cohorts:
            self.manager.add_cohort("Cohort KL", self.reader.samples[:8])
        cloned = self.manager.clone_cohort("Cohort KL")
        self.assertEqual(cloned.name, "Cohort KL (Copy)")
        self.assertEqual(cloned.sample_ids, self.manager.cohorts["Cohort KL"].sample_ids)
        self.assertIn("Cohort KL (Copy)", self.manager.cohorts)

    def test_cohort_update_and_rename(self):
        self.manager.add_cohort("Test_Group", self.reader.samples[:3], description="Initial")
        self.assertIn("Test_Group", self.manager.cohorts)

        updated = self.manager.update_cohort(
            "Test_Group",
            new_name="Renamed_Group",
            sample_ids=self.reader.samples[:5],
            description="Updated description",
            color="#ec4899"
        )
        self.assertNotIn("Test_Group", self.manager.cohorts)
        self.assertIn("Renamed_Group", self.manager.cohorts)
        self.assertEqual(len(updated.sample_ids), 5)
        self.assertEqual(updated.color, "#ec4899")

    def test_cohort_deletion(self):
        # All Samples cannot be deleted
        res = self.manager.delete_cohort("All Samples")
        self.assertFalse(res)
        self.assertIn("All Samples", self.manager.cohorts)

        # Other cohorts can be deleted
        self.manager.add_cohort("Temp_Cohort", self.reader.samples[:2])
        self.assertIn("Temp_Cohort", self.manager.cohorts)
        deleted = self.manager.delete_cohort("Temp_Cohort")
        self.assertTrue(deleted)
        self.assertNotIn("Temp_Cohort", self.manager.cohorts)

    def test_invert_selection(self):
        selected = self.reader.samples[:5]
        inverted = self.manager.invert_selection(selected)
        self.assertEqual(len(inverted), len(self.reader.samples) - 5)
        for s in selected:
            self.assertNotIn(s, inverted)
        for s in inverted:
            self.assertIn(s, self.reader.samples)


if __name__ == "__main__":
    unittest.main()
