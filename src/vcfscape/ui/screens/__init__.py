"""Modal screens for vcfscape Textual TUI."""

try:
    from vcfscape.ui.screens.cohort_manager_screen import CohortManagerScreen
except ImportError:
    CohortManagerScreen = None

try:
    from vcfscape.ui.screens.jump_region_screen import JumpRegionScreen
except ImportError:
    JumpRegionScreen = None

__all__ = ["CohortManagerScreen", "JumpRegionScreen"]
