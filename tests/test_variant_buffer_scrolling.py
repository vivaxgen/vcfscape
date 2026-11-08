"""
Unit tests for VariantSplitView buffer windowing, total records handling,
and scrolling down past the buffer window end.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import textual
    from vcfscape.ui.widgets.variant_table import VariantSplitView, FixedVariantTable, SampleMatrixTable
except ImportError:
    from unittest.mock import MagicMock

    class MockWidget:
        def __init__(self, *args, **kwargs):
            self.styles = type("Styles", (), {"width": 1, "min_width": 1, "max_width": 1, "height": "100%"})()
        def post_message(self, msg):
            pass

    class MockDataTable(MockWidget):
        RowHighlighted = type("RowHighlighted", (), {})
        CellHighlighted = type("CellHighlighted", (), {})
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.cursor_row = 0
            self.row_count = 150
            self.scroll_y = 0
            self.scroll_x = 0
            self.max_scroll_y = 100
        def clear(self, columns=True):
            pass
        def add_column(self, *args, **kwargs):
            pass
        def add_row(self, *args, **kwargs):
            pass
        def scroll_to(self, *args, **kwargs):
            pass
        def move_cursor(self, row=None, column=None, animate=False):
            if row is not None:
                self.cursor_row = row

    sys.modules["textual"] = MagicMock()
    sys.modules["textual.events"] = MagicMock()
    sys.modules["textual.widget"] = MagicMock()
    sys.modules["textual.widget"].Widget = MockWidget
    sys.modules["textual.widgets"] = MagicMock()
    sys.modules["textual.widgets"].DataTable = MockDataTable
    sys.modules["textual.widgets"].Static = MockWidget
    sys.modules["textual.containers"] = MagicMock()
    sys.modules["textual.reactive"] = MagicMock()
    sys.modules["textual.reactive"].reactive = lambda x: x
    sys.modules["textual.message"] = MagicMock()
    sys.modules["textual.message"].Message = object
    sys.modules["rich.text"] = MagicMock()
    sys.modules["rich.text"].Text = lambda x, **kw: x

    from vcfscape.ui.widgets.variant_table import VariantSplitView, FixedVariantTable, SampleMatrixTable

from vcfscape.core.vcf_reader import VariantRecord


class TestVariantBufferScrolling(unittest.TestCase):

    def setUp(self):
        self.records = [
            VariantRecord(
                chrom=f"Pf3D7_{(i % 14) + 1:02d}_v3",
                pos=1000 + i * 50,
                var_id=f"var_{i}",
                ref="A",
                alt=["T"],
                qual=99.0,
                filter_str="PASS",
                info={},
                format_keys=["GT", "DP"],
                sample_data={"S1": {"GT": "0/1", "DP": "30"}},
                genotypes={"S1": (0, 1)},
                depths={"S1": 30},
                ad={"S1": [15, 15]},
            )
            for i in range(500)
        ]

    def test_buffer_scroll_past_window_with_total_count(self):
        class MockReader:
            def __init__(self, records):
                self.all_records = records
                self.total_variants = len(records)
                self.total_variants_ready = True
                self.samples = ["S1"]
            def get_slice(self, offset, limit):
                return self.all_records[offset: offset + limit]
            def get_total_variants_async(self):
                return len(self.all_records)

        reader = MockReader(self.records)
        initial_slice = reader.get_slice(0, 150)
        sv = VariantSplitView(initial_slice, ["S1"], reader=reader)

        self.assertEqual(sv.buffer_start, 0)
        self.assertEqual(sv.total_records_count, 500)
        self.assertEqual(len(sv.records), 150)

        # Trigger boundary check at bottom of initial 150-variant window
        sv._check_buffer_boundary(140)
        self.assertEqual(sv.buffer_start, 40)
        self.assertEqual(len(sv.records), 150)

        # Shift multiple steps past initial window (40 -> 80 -> 120 -> 160 -> 200)
        for _ in range(4):
            sv._check_buffer_boundary(140)
        self.assertGreater(sv.buffer_start, 150)
        self.assertEqual(sv.buffer_start, 200)

        # Shift until file end (max_start = 500 - 150 = 350)
        sv.request_scroll_shift(forward=True, step=200)
        self.assertEqual(sv.buffer_start, 350)

    def test_buffer_scroll_with_async_background_counting(self):
        class AsyncCountingReader:
            def __init__(self, records):
                self.all_records = records
                self.total_variants_ready = False
                self.samples = ["S1"]
            def get_slice(self, offset, limit):
                return self.all_records[offset: offset + limit]
            def get_total_variants_async(self):
                return None

        reader = AsyncCountingReader(self.records)
        initial_slice = reader.get_slice(0, 150)
        sv = VariantSplitView(initial_slice, ["S1"], reader=reader)

        # total_records_count must be None and not capped to len(records)
        self.assertIsNone(sv.total_records_count)

        # Must shift forward past 150 even while background counting is active
        sv.request_scroll_shift(forward=True, step=40)
        self.assertEqual(sv.buffer_start, 40)
        sv.request_scroll_shift(forward=True, step=40)
        self.assertEqual(sv.buffer_start, 80)
        sv.request_scroll_shift(forward=True, step=80)
        self.assertEqual(sv.buffer_start, 160)
        self.assertGreater(sv.buffer_start, 150)

    def test_advance_row_smooth_pinning_across_buffer_boundary(self):
        """Verify advancing row by row across window boundary (row 130 -> 160) keeps cursor pinned."""
        class MockReader:
            def __init__(self, records):
                self.all_records = records
                self.total_variants = len(records)
                self.total_variants_ready = True
                self.samples = ["S1"]
            def get_slice(self, offset, limit):
                return self.all_records[offset: offset + limit]
            def get_total_variants_async(self):
                return len(self.all_records)

        reader = MockReader(self.records)
        initial_slice = reader.get_slice(0, 150)
        sv = VariantSplitView(initial_slice, ["S1"], reader=reader)

        # Set cursor to row 130
        sv.set_active_row(130)
        self.assertEqual(sv.current_row_idx + sv.buffer_start, 130)
        self.assertEqual(sv.records[sv.current_row_idx].var_id, "var_130")

        # Step one-by-one from 130 to 160
        for expected_global in range(131, 161):
            self.assertTrue(sv.can_advance_row(forward=True))
            sv.advance_row(forward=True)
            active_global = sv.current_row_idx + sv.buffer_start
            self.assertEqual(active_global, expected_global)
            self.assertEqual(sv.records[sv.current_row_idx].var_id, f"var_{expected_global}")

        # Buffer should have shifted forward smoothly
        self.assertGreater(sv.buffer_start, 0)
        self.assertEqual(sv.records[sv.current_row_idx].var_id, "var_160")

        # Now step backward from 160 to 120
        for expected_global in range(159, 119, -1):
            self.assertTrue(sv.can_advance_row(forward=False))
            sv.advance_row(forward=False)
            active_global = sv.current_row_idx + sv.buffer_start
            self.assertEqual(active_global, expected_global)
            self.assertEqual(sv.records[sv.current_row_idx].var_id, f"var_{expected_global}")

    def test_sample_window_advance_and_centering(self):
        """Verify horizontal sample navigation monotonically advances without snapback."""
        samples_50 = [f"Sample_{i:03d}" for i in range(50)]
        sv = VariantSplitView(self.records[:10], samples_50, reader=None)
        sv.sample_window_size = 20

        self.assertEqual(sv.current_sample_idx, 0)
        self.assertEqual(sv.sample_window_start, 0)

        # Step across sample boundary from 0 to 30
        for expected_col in range(1, 31):
            self.assertTrue(sv.can_advance_sample(forward=True))
            sv.advance_sample(forward=True)
            self.assertEqual(sv.current_sample_idx, expected_col)
            # The active sample must be contained within the visible sample window
            visible = sv.get_visible_samples()
            self.assertIn(f"Sample_{expected_col:03d}", visible)

        # Window start should have shifted to keep sample centered
        self.assertGreater(sv.sample_window_start, 0)
        self.assertEqual(sv.current_sample_idx, 30)

        # Step back towards start
        for expected_col in range(29, 9, -1):
            self.assertTrue(sv.can_advance_sample(forward=False))
            sv.advance_sample(forward=False)
            self.assertEqual(sv.current_sample_idx, expected_col)
            visible = sv.get_visible_samples()
            self.assertIn(f"Sample_{expected_col:03d}", visible)

    def test_chromosome_contig_names_unmodified(self):
        """Verify chromosome contig names are never normalized or stripped."""
        chrom_names = ["Pf3D7_07_v3", "chr1", "chrX", "NC_000001.11", "MT"]
        test_records = [
            VariantRecord(
                chrom=chrom,
                pos=1000 + idx,
                var_id=f"v_{idx}",
                ref="A",
                alt=["T"],
                qual=99.0,
                filter_str="PASS",
                info={},
                format_keys=["GT"],
                sample_data={"S1": {"GT": "0/1"}},
                genotypes={"S1": (0, 1)},
                depths={"S1": 30},
                ad={"S1": [15, 15]},
            )
            for idx, chrom in enumerate(chrom_names)
        ]
        sv = VariantSplitView(test_records, ["S1"], reader=None)
        for idx, rec in enumerate(sv.records):
            self.assertEqual(rec.chrom, chrom_names[idx])


if __name__ == "__main__":
    unittest.main()

