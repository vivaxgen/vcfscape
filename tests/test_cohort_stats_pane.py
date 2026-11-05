"""
Unit tests for CohortStatsPane resizability logic and state management.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import textual
    from vcfscape.ui.widgets.cohort_stats_pane import CohortStatsPane
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    CohortStatsPane = None


@unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual library not installed in this environment")
class TestCohortStatsPane(unittest.TestCase):

    def setUp(self):
        mock_manager = MagicMock()
        mock_manager.cohorts = {}
        mock_manager.calculate_variant_stats.return_value = {}
        self.pane = CohortStatsPane(mock_manager)

    def test_initial_state(self):
        self.assertEqual(self.pane.current_height, 8)
        self.assertTrue(self.pane.is_collapsed)

    def test_stats_not_calculated_when_collapsed(self):
        rec = MagicMock()
        rec.alt = ["T"]
        rec.genotypes = {}
        rec.depths = {}
        rec.ad = {}
        rec.num_alleles = 2

        # Updating while collapsed should NOT calculate stats
        self.pane.update_stats(rec)
        self.pane.cohort_manager.calculate_variant_stats.assert_not_called()

        # Expanding via toggle_pane() should calculate stats
        self.pane.toggle_pane()
        self.assertFalse(self.pane.is_collapsed)
        self.pane.cohort_manager.calculate_variant_stats.assert_called_once()

    def test_resize_by_increments(self):
        self.pane.resize_by(2)
        self.assertEqual(self.pane.current_height, 10)

        self.pane.resize_by(-4)
        self.assertEqual(self.pane.current_height, 6)

    def test_clamp_limits(self):
        # Above maximum
        self.pane.set_height(50)
        self.assertEqual(self.pane.current_height, self.pane.MAX_HEIGHT)

        # Below minimum
        self.pane.set_height(1)
        self.assertEqual(self.pane.current_height, self.pane.MIN_HEIGHT)

    def test_toggle_collapse(self):
        # Starts collapsed
        self.assertTrue(self.pane.is_collapsed)

        # 1st toggle expands
        self.pane.toggle_pane()
        self.assertFalse(self.pane.is_collapsed)
        self.assertEqual(self.pane.current_height, 8)

        # 2nd toggle collapses
        self.pane.toggle_pane()
        self.assertTrue(self.pane.is_collapsed)

    def test_toggle_collapse_with_variant(self):
        rec1 = MagicMock()
        rec1.alt = ["T"]
        rec1.genotypes = {}
        rec1.depths = {}
        rec1.ad = {}
        rec1.num_alleles = 2

        # Expand pane
        self.pane.toggle_pane()
        self.assertFalse(self.pane.is_collapsed)

        # Scrolling/selecting rec1 updates content while visible
        self.pane.update_stats(rec1)
        self.assertEqual(self.pane.current_height, 8)
        self.assertIsNotNone(self.pane.current_record)

        # Toggle collapse
        self.pane.toggle_pane()
        self.assertTrue(self.pane.is_collapsed)

        # Toggle expand again via [s] - re-heights to optimal height 9
        self.pane.toggle_pane()
        self.assertFalse(self.pane.is_collapsed)
        self.assertEqual(self.pane.current_height, 9)

        # Variant with 2 ALT alleles (multi-allelic) - scrolling updates content without auto-reheight
        rec2 = MagicMock()
        rec2.alt = ["T", "G"]
        rec2.genotypes = {}
        rec2.depths = {}
        rec2.ad = {}
        rec2.num_alleles = 3

        self.pane.update_stats(rec2)
        self.assertEqual(self.pane.current_height, 9)

        # Toggle off and on via [s]: manually re-heights for rec2 to 10
        self.pane.toggle_pane()
        self.assertTrue(self.pane.is_collapsed)
        self.pane.toggle_pane()
        self.assertFalse(self.pane.is_collapsed)
        self.assertEqual(self.pane.current_height, 10)
        self.assertEqual(self.pane.current_height, 10)


if __name__ == "__main__":
    unittest.main()
