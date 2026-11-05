"""
Unit tests for CohortManagerScreen modal and UI actions.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
try:
    import textual
    from vcfscape.ui.screens.cohort_manager_screen import CohortManagerScreen
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    CohortManagerScreen = None

from vcfscape.core.cohorts import CohortManager


@unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual library not installed in this environment")
class TestCohortManagerScreen(unittest.TestCase):

    def setUp(self):
        self.samples = [
            "KL_001", "KL_002", "KL_003",
            "AS_001", "AS_002", "AS_003",
            "BS_001", "BS_002", "BS_003"
        ]
        self.manager = CohortManager(self.samples)
        self.manager.add_cohort("Cohort KL", [s for s in self.samples if s.startswith("KL_")])

    def test_screen_initialization(self):
        screen = CohortManagerScreen(self.manager, initial_cohort="Cohort KL")
        self.assertEqual(screen.active_cohort_name, "Cohort KL")
        self.assertEqual(screen.working_name, "Cohort KL")
        self.assertFalse(screen.is_new_mode)
        self.assertGreater(len(screen.selected_samples), 0)

    def test_screen_invert_selection(self):
        screen = CohortManagerScreen(self.manager, initial_cohort="Cohort KL")
        initial_count = len(screen.selected_samples)
        screen.action_invert_selection()
        self.assertEqual(len(screen.selected_samples), len(self.samples) - initial_count)

    def test_screen_select_and_deselect_all(self):
        screen = CohortManagerScreen(self.manager)
        screen.action_select_all()
        self.assertEqual(len(screen.selected_samples), len(self.samples))

        screen.action_deselect_all()
        self.assertEqual(len(screen.selected_samples), 0)

    def test_screen_clone_action(self):
        screen = CohortManagerScreen(self.manager, initial_cohort="Cohort KL")
        initial_cohort_count = len(self.manager.cohorts)
        cloned = self.manager.clone_cohort("Cohort KL")
        self.assertEqual(len(self.manager.cohorts), initial_cohort_count + 1)
        self.assertIn(cloned.name, self.manager.cohorts)


if __name__ == "__main__":
    unittest.main()
