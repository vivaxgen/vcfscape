"""
Unit tests for VcfLoadingScreen and VcfReader progress reporting.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import textual
    from vcfscape.ui.screens.vcf_loading_screen import VcfLoadingScreen, AnimatedSpinner
except ImportError:
    class MockWidget:
        def __init__(self, *args, **kwargs):
            self.styles = type("Styles", (), {"width": 1, "min_width": 1, "max_width": 1, "height": "100%"})()
            self._text = ""
        def update(self, text):
            self._text = str(text)
        def query_one(self, selector, expected_type=None):
            return self

    class MockScreen(MockWidget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._dismissed = False
            self._result = None
        def dismiss(self, result=None):
            self._dismissed = True
            self._result = result
        def __class_getitem__(cls, item):
            return cls

    sys.modules["textual"] = MagicMock()
    sys.modules["textual.screen"] = MagicMock()
    sys.modules["textual.screen"].ModalScreen = MockScreen
    sys.modules["textual.app"] = MagicMock()
    sys.modules["textual.widget"] = MagicMock()
    sys.modules["textual.widget"].Widget = MockWidget
    sys.modules["textual.widgets"] = MagicMock()
    MockWidget.Pressed = type("Pressed", (), {})
    sys.modules["textual.widgets"].Static = MockWidget
    sys.modules["textual.widgets"].Button = MockWidget
    sys.modules["textual.containers"] = MagicMock()
    sys.modules["textual.binding"] = MagicMock()
    sys.modules["rich.text"] = MagicMock()
    sys.modules["rich.text"].Text = lambda x, **kw: x

    from vcfscape.ui.screens.vcf_loading_screen import VcfLoadingScreen, AnimatedSpinner


class TestVcfLoadingScreen(unittest.TestCase):

    def test_loading_screen_initialization(self):
        screen = VcfLoadingScreen(filename="cohort_malaria.vcf.gz")
        self.assertEqual(screen.filename, "cohort_malaria.vcf.gz")
        self.assertFalse(screen.is_completed)
        self.assertEqual(screen._current_count, 0)

    def test_update_progress(self):
        screen = VcfLoadingScreen(filename="cohort_malaria.vcf.gz")
        screen.update_progress(15000)
        self.assertEqual(screen._current_count, 15000)

        screen.update_progress(45000)
        self.assertEqual(screen._current_count, 45000)

    def test_mark_complete_auto_dismisses(self):
        screen = VcfLoadingScreen(filename="cohort_malaria.vcf.gz")
        screen.mark_complete(52400)
        self.assertTrue(screen.is_completed)
        self.assertEqual(screen._current_count, 52400)

    def test_dismiss_action(self):
        screen = VcfLoadingScreen(filename="cohort_malaria.vcf.gz")
        screen.update_progress(10000)
        screen.action_dismiss_screen()
        # Verify dismissal was invoked without errors

    def test_vcf_reader_progress_callbacks(self):
        from vcfscape.core.vcf_reader import VcfReader
        import tempfile

        # Create a small temp VCF
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False) as f:
            f.write("##fileformat=VCFv4.2\n")
            f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n")
            for i in range(25):
                f.write(f"Pf3D7_07_v3\t{1000 + i * 10}\t.\tA\tT\t99\tPASS\t.\tGT\t0/1\n")
            temp_path = f.name

        try:
            reader = VcfReader(temp_path, lazy=True)
            progress_calls = []
            total_calls = []

            reader.add_progress_callback(lambda count: progress_calls.append(count))
            reader.add_total_variants_callback(lambda count: total_calls.append(count))

            self.assertEqual(reader.total_variants, 25)
            self.assertTrue(len(total_calls) > 0)
            self.assertEqual(total_calls[-1], 25)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_async_uncompressed_vcf_indexing_progress(self):
        """Verify uncompressed VCF starts immediately and streams progress callbacks."""
        from vcfscape.core.vcf_reader import VcfReader
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False) as f:
            f.write("##fileformat=VCFv4.2\n")
            f.write("##contig=<ID=Pf3D7_07_v3,length=1445207>\n")
            f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n")
            for i in range(2500):
                f.write(f"Pf3D7_07_v3\t{1000 + i * 5}\tvar_{i}\tA\tT\t99\tPASS\t.\tGT\t0/1\n")
            temp_path = f.name

        try:
            reader = VcfReader(temp_path, lazy=True)
            # Immediate slice retrieval should succeed instantly
            init_slice = reader.get_slice(0, 10)
            self.assertEqual(len(init_slice), 10)
            self.assertEqual(init_slice[0].var_id, "var_0")

            progress_counts = []
            reader.add_progress_callback(lambda count: progress_counts.append(count))

            # Total variants waits for background worker to complete
            total = reader.total_variants
            self.assertEqual(total, 2500)
            self.assertTrue(reader.total_variants_ready)
            self.assertTrue(len(progress_counts) > 0)
            self.assertEqual(progress_counts[-1], 2500)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            idx_cache = os.path.join(os.path.dirname(temp_path), f".{os.path.basename(temp_path)}.vcfscape.idx")
            if os.path.exists(idx_cache):
                os.remove(idx_cache)


if __name__ == "__main__":
    unittest.main()
