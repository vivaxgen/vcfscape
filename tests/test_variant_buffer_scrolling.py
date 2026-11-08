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
            self.columns = {}
        def clear(self, columns=True):
            if columns:
                self.columns = {}
        def add_column(self, label, key=None, *args, **kwargs):
            k = key or str(label)
            self.columns[k] = type("Col", (), {"width": 8, "auto_width": 8})()
        def add_row(self, *args, **kwargs):
            pass
        def update_cell(self, row_key, column_key, value, update_width=False):
            pass
        def scroll_to(self, x=None, y=None, *args, **kwargs):
            if x is not None:
                self.scroll_x = x
            if y is not None:
                self.scroll_y = y
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
        """Verify horizontal sample navigation monotonically advances without snapback across native columns."""
        samples_50 = [f"Sample_{i:03d}" for i in range(50)]
        sv = VariantSplitView(self.records[:10], samples_50, reader=None)

        self.assertEqual(sv.current_sample_idx, 0)
        # All columns are present in the sample table
        self.assertEqual(len(sv.get_visible_samples()), 50)

        # Step across sample columns from 0 to 30
        for expected_col in range(1, 31):
            self.assertTrue(sv.can_advance_sample(forward=True))
            sv.advance_sample(forward=True)
            self.assertEqual(sv.current_sample_idx, expected_col)
            # The active sample must be contained within the sample columns
            visible = sv.get_visible_samples()
            self.assertIn(f"Sample_{expected_col:03d}", visible)

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

    def test_auto_centering_only_when_pointer_passes_viewport_edge(self):
        """Verify that auto-centering only occurs when the pointer passes the edge of the viewport."""
        samples_10 = [f"Sample_{i}" for i in range(10)]
        sv = VariantSplitView(self.records[:5], samples_10, reader=None)
        table = sv.sample_table

        # Override viewport width to 40 characters (columns are 8 chars wide each, so ~5 cols fit)
        table._get_viewport_width = lambda: 40

        table.scroll_x = 0
        self.assertTrue(table.is_column_in_viewport(0))
        self.assertTrue(table.is_column_in_viewport(1))
        self.assertTrue(table.is_column_in_viewport(2))
        self.assertTrue(table.is_column_in_viewport(3))
        self.assertTrue(table.is_column_in_viewport(4))  # Col 4 bounds: 32..40, fully in [0..40]
        self.assertFalse(table.is_column_in_viewport(5)) # Col 5 bounds: 40..48, passes right edge

        # Moving within viewport: col 0 -> col 1 -> col 2 -> col 3 -> col 4
        # scroll_x MUST stay at 0 (no auto-centering)
        for col in range(1, 5):
            table.scroll_column_centered(col)
            self.assertEqual(table.scroll_x, 0, f"Column {col} is inside viewport, scroll_x should not change")

        # Now pointer passes the right edge: moving to col 5 (bounds 40..48)
        table.scroll_column_centered(5)
        # It must auto-center col 5:
        # col_center = (40 + 48) // 2 = 44. target_x = max(0, 44 - 20) = 24.
        self.assertEqual(table.scroll_x, 24)

        # Now within new viewport [24..64]: col 5 (40..48) and col 6 (48..56) are inside
        self.assertTrue(table.is_column_in_viewport(5))
        self.assertTrue(table.is_column_in_viewport(6))
        table.scroll_column_centered(6)
        # Should NOT change scroll_x:
        self.assertEqual(table.scroll_x, 24)

        # Moving backward: col 2 (16..24) passes left edge of viewport [24..64]
        self.assertFalse(table.is_column_in_viewport(2))
        table.scroll_column_centered(2)
        # Auto-centers col 2:
        # col_center = 20. target_x = max(0, 20 - 20) = 0.
        self.assertEqual(table.scroll_x, 0)

    def test_inplace_row_updates_no_clear_during_shift(self):
        """Verify that shifting buffer updates cells in place without calling clear() on tables."""
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
        sv = VariantSplitView(reader.get_slice(0, 150), ["S1"], reader=reader)

        # Track clear() and update_cell() calls
        fixed_clears = 0
        sample_clears = 0
        update_cell_calls = 0

        orig_f_clear = sv.fixed_table.clear
        orig_s_clear = sv.sample_table.clear
        orig_update_cell = sv.fixed_table.update_cell

        def f_clear_spy(*args, **kwargs):
            nonlocal fixed_clears
            fixed_clears += 1
            return orig_f_clear(*args, **kwargs)

        def s_clear_spy(*args, **kwargs):
            nonlocal sample_clears
            sample_clears += 1
            return orig_s_clear(*args, **kwargs)

        def update_cell_spy(*args, **kwargs):
            nonlocal update_cell_calls
            update_cell_calls += 1
            return orig_update_cell(*args, **kwargs)

        sv.fixed_table.clear = f_clear_spy
        sv.sample_table.clear = s_clear_spy
        sv.fixed_table.update_cell = update_cell_spy

        # Trigger buffer shift forward
        sv.set_active_row(145)
        self.assertEqual(sv.buffer_start, 40)
        self.assertEqual(sv.records[0].var_id, "var_40")

        # Zero clear() calls must have occurred during the shift!
        self.assertEqual(fixed_clears, 0, "fixed_table.clear() should not be called during buffer shift")
        self.assertEqual(sample_clears, 0, "sample_table.clear() should not be called during buffer shift")
        # In-place cell updates must have occurred!
        self.assertGreater(update_cell_calls, 0, "Cells must be updated in place via update_cell")


if __name__ == "__main__":
    unittest.main()



