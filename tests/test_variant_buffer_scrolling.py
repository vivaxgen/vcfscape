"""
Unit tests for VariantSplitView continuous dynamic appending,
total records handling, and smooth vertical scrolling past the initial buffer.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import textual
    from vcfscape.ui.widgets.variant_table import VariantSplitView, FixedVariantTable, SampleMatrixTable
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    VariantSplitView = None
    FixedVariantTable = None
    SampleMatrixTable = None

from vcfscape.core.vcf_reader import VariantRecord


@unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual library not installed in this environment")
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

    def test_buffer_continuous_append_past_window_with_total_count(self):
        """Verify continuous dynamic append extends rows smoothly without hitting walls."""
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
        sv.rebuild_tables()

        self.assertEqual(sv.total_records_count, 500)
        self.assertEqual(len(sv.records), 150)
        self.assertEqual(sv.fixed_table.row_count, 150)
        self.assertEqual(sv.sample_table.row_count, 150)

        # Trigger boundary check at bottom of initial 150-variant window (row 140)
        sv._check_buffer_boundary(140)
        # Should dynamically append 100 more rows: 150 -> 250
        self.assertEqual(len(sv.records), 250)
        self.assertEqual(sv.fixed_table.row_count, 250)
        self.assertEqual(sv.sample_table.row_count, 250)

        # Trigger boundary check at bottom of 250 (row 235)
        sv._check_buffer_boundary(235)
        self.assertEqual(len(sv.records), 350)
        self.assertEqual(sv.fixed_table.row_count, 350)

        # Continuous append until file end (500 records)
        sv.request_scroll_shift(forward=True, step=200)
        self.assertEqual(len(sv.records), 500)
        self.assertEqual(sv.fixed_table.row_count, 500)

    def test_continuous_append_with_async_background_counting(self):
        """Verify dynamic appending works even before background variant counting finishes."""
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
        sv.rebuild_tables()

        self.assertIsNone(sv.total_records_count)
        self.assertEqual(len(sv.records), 150)

        # Append more rows while background counting is active
        sv.request_scroll_shift(forward=True, step=100)
        self.assertEqual(len(sv.records), 350)
        self.assertEqual(sv.fixed_table.row_count, 350)

        # Background counting completes
        sv.update_total_variants(500)
        self.assertEqual(sv.total_records_count, 500)

    def test_advance_row_monotonic_across_boundary(self):
        """Verify advancing row by row across window boundary (row 130 -> 160) keeps cursor advancing without snapback."""
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
        sv.rebuild_tables()

        # Set cursor to row 130
        sv.set_active_row(130)
        self.assertEqual(sv.current_row_idx, 130)
        self.assertEqual(sv.records[sv.current_row_idx].var_id, "var_130")

        # Step one-by-one from 130 to 160
        for expected_global in range(131, 161):
            self.assertTrue(sv.can_advance_row(forward=True))
            sv.advance_row(forward=True)
            self.assertEqual(sv.current_row_idx, expected_global)
            self.assertEqual(sv.records[sv.current_row_idx].var_id, f"var_{expected_global}")

        # Check table has grown to accommodate row 160
        self.assertGreaterEqual(len(sv.records), 250)
        self.assertEqual(sv.records[sv.current_row_idx].var_id, "var_160")

        # Now step backward from 160 to 120
        for expected_global in range(159, 119, -1):
            self.assertTrue(sv.can_advance_row(forward=False))
            sv.advance_row(forward=False)
            self.assertEqual(sv.current_row_idx, expected_global)
            self.assertEqual(sv.records[sv.current_row_idx].var_id, f"var_{expected_global}")

    def test_sample_window_advance_and_centering(self):
        """Verify horizontal sample navigation monotonically advances without snapback across native columns."""
        samples_50 = [f"Sample_{i:03d}" for i in range(50)]
        sv = VariantSplitView(self.records[:10], samples_50, reader=None)
        sv.rebuild_tables()

        self.assertEqual(sv.current_sample_idx, 0)
        self.assertEqual(len(sv.get_visible_samples()), 50)

        # Step across sample columns from 0 to 30
        for expected_col in range(1, 31):
            self.assertTrue(sv.can_advance_sample(forward=True))
            sv.advance_sample(forward=True)
            self.assertEqual(sv.current_sample_idx, expected_col)
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
        self.assertTrue(table.is_column_in_viewport(4))
        self.assertFalse(table.is_column_in_viewport(5))

        for col in range(1, 5):
            table.scroll_column_centered(col)
            self.assertEqual(table.scroll_x, 0, f"Column {col} is inside viewport, scroll_x should not change")

        # Now pointer passes the right edge: moving to col 5
        table.scroll_column_centered(5)
        self.assertEqual(table.scroll_x, 24)

        # Now within new viewport [24..64]: col 5 and col 6 are inside
        self.assertTrue(table.is_column_in_viewport(5))
        self.assertTrue(table.is_column_in_viewport(6))
        table.scroll_column_centered(6)
        self.assertEqual(table.scroll_x, 24)

        # Moving backward: col 2 passes left edge of viewport [24..64]
        self.assertFalse(table.is_column_in_viewport(2))
        table.scroll_column_centered(2)
        self.assertEqual(table.scroll_x, 0)

    def test_continuous_append_no_table_clear(self):
        """Verify that dynamic appending adds rows without clearing existing table columns or rows."""
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
        sv.rebuild_tables()

        fixed_clears = 0
        sample_clears = 0

        orig_f_clear = sv.fixed_table.clear
        orig_s_clear = sv.sample_table.clear

        def f_clear_spy(*args, **kwargs):
            nonlocal fixed_clears
            fixed_clears += 1
            return orig_f_clear(*args, **kwargs)

        def s_clear_spy(*args, **kwargs):
            nonlocal sample_clears
            sample_clears += 1
            return orig_s_clear(*args, **kwargs)

        sv.fixed_table.clear = f_clear_spy
        sv.sample_table.clear = s_clear_spy

        # Trigger dynamic continuous append
        sv.set_active_row(145)
        self.assertEqual(len(sv.records), 250)
        self.assertEqual(sv.records[0].var_id, "var_0")
        self.assertEqual(sv.records[249].var_id, "var_249")

        # Zero clear() calls must occur during dynamic row appending!
        self.assertEqual(fixed_clears, 0, "fixed_table.clear() should not be called during row append")
        self.assertEqual(sample_clears, 0, "sample_table.clear() should not be called during row append")

    def test_large_cohort_sample_column_virtualization(self):
        """Verify cohorts with 500+ samples virtualize columns to 50 in DOM and navigate smoothly."""
        cohort_500 = [f"Sample_{i:04d}" for i in range(500)]
        sv = VariantSplitView(self.records[:10], cohort_500, reader=None)
        sv.rebuild_tables()

        # Capped at 50 columns in the DOM instead of 500
        self.assertEqual(len(sv.get_visible_samples()), 50)
        self.assertEqual(sv.sample_window_start, 0)
        self.assertEqual(sv.current_sample_idx, 0)
        self.assertEqual(sv.get_visible_samples()[0], "Sample_0000")
        self.assertEqual(sv.get_visible_samples()[-1], "Sample_0049")

        # Step horizontally into boundary margin (e.g. sample 46)
        sv.set_active_sample(46)
        self.assertEqual(sv.current_sample_idx, 46)
        self.assertGreater(sv.sample_window_start, 0)
        self.assertEqual(len(sv.get_visible_samples()), 50)
        self.assertIn("Sample_0046", sv.get_visible_samples())

        # Jump to sample 250 in large cohort
        sv.set_active_sample(250)
        self.assertEqual(sv.current_sample_idx, 250)
        visible = sv.get_visible_samples()
        self.assertEqual(len(visible), 50)
        self.assertIn("Sample_0250", visible)

        # Jump towards cohort end (sample 499)
        sv.set_active_sample(499)
        self.assertEqual(sv.current_sample_idx, 499)
        visible = sv.get_visible_samples()
        self.assertEqual(len(visible), 50)
        self.assertIn("Sample_0499", visible)
        self.assertEqual(sv.sample_window_start, 450)

        # Jump back to start
        sv.set_active_sample(5)
        self.assertEqual(sv.current_sample_idx, 5)
        visible = sv.get_visible_samples()
        self.assertEqual(len(visible), 50)
        self.assertIn("Sample_0005", visible)
        self.assertEqual(sv.sample_window_start, 0)


if __name__ == "__main__":
    unittest.main()
