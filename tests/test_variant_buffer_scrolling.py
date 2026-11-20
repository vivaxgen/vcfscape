"""
Unit tests for VariantSplitView dynamic appending, native all-sample horizontal navigation,
top-widget key/mouse-wheel capture, and lockstep vertical scrolling.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import textual
    import textual_fastdatatable
    import pyarrow
    from vcfscape.ui.widgets.variant_table import VariantSplitView, FixedVariantTable, SampleMatrixTable
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    VariantSplitView = None
    FixedVariantTable = None
    SampleMatrixTable = None

from vcfscape.core.vcf_reader import VariantRecord


@unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual / textual-fastdatatable / pyarrow not installed in this environment")
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
        """Verify dynamic appending extends ArrowBackend rows cleanly without clearing tables."""
        class MockReader:
            def __init__(self, records):
                self.all_records = records
                self.total_variants = len(records)
                self.total_variants_ready = True
                self.samples = ["S1"]
            def get_slice(self, offset, limit, allow_placeholder=False):
                return self.all_records[offset: offset + limit]
            def get_total_variants_async(self):
                return len(self.all_records)

        reader = MockReader(self.records)
        sv = VariantSplitView(reader.get_slice(0, 150), ["S1"], reader=reader)

        self.assertEqual(sv.total_records_count, 500)
        self.assertEqual(len(sv.records), 150)
        self.assertEqual(sv.fixed_table.row_count, 150)
        self.assertEqual(sv.sample_table.row_count, 150)

        self.assertTrue(sv.fetch_more_rows(100))
        self.assertEqual(len(sv.records), 250)
        self.assertEqual(sv.fixed_table.row_count, 250)
        self.assertEqual(sv.sample_table.row_count, 250)

        self.assertTrue(sv.fetch_more_rows(250))
        self.assertEqual(len(sv.records), 500)
        self.assertEqual(sv.fixed_table.row_count, 500)

    def test_continuous_append_with_async_background_counting(self):
        """Verify dynamic appending works even before background variant counting finishes."""
        class AsyncCountingReader:
            def __init__(self, records):
                self.all_records = records
                self.total_variants_ready = False
                self.samples = ["S1"]
            def get_slice(self, offset, limit, allow_placeholder=False):
                return self.all_records[offset: offset + limit]
            def get_total_variants_async(self):
                return None

        reader = AsyncCountingReader(self.records)
        sv = VariantSplitView(reader.get_slice(0, 150), ["S1"], reader=reader)

        self.assertIsNone(sv.total_records_count)
        self.assertEqual(len(sv.records), 150)

        self.assertTrue(sv.fetch_more_rows(200))
        self.assertEqual(len(sv.records), 350)
        self.assertEqual(sv.fixed_table.row_count, 350)

        sv.update_total_variants(500)
        self.assertEqual(sv.total_records_count, 500)

    def test_advance_row_monotonic_across_boundary(self):
        """Verify advancing row by row across window boundary keeps cursor monotonic without snapback."""
        class MockReader:
            def __init__(self, records):
                self.all_records = records
                self.total_variants = len(records)
                self.total_variants_ready = True
                self.samples = ["S1"]
            def get_slice(self, offset, limit, allow_placeholder=False):
                return self.all_records[offset: offset + limit]
            def get_total_variants_async(self):
                return len(self.all_records)

        reader = MockReader(self.records)
        sv = VariantSplitView(reader.get_slice(0, 150), ["S1"], reader=reader)

        sv.set_active_row(130)
        self.assertEqual(sv.current_row_idx, 130)
        self.assertEqual(sv.records[sv.current_row_idx].var_id, "var_130")

        for expected_global in range(131, 161):
            self.assertTrue(sv.can_advance_row(forward=True))
            sv.advance_row(forward=True)
            self.assertEqual(sv.current_row_idx, expected_global)
            self.assertEqual(sv.records[sv.current_row_idx].var_id, f"var_{expected_global}")

        self.assertGreaterEqual(len(sv.records), 250)
        self.assertEqual(sv.records[sv.current_row_idx].var_id, "var_160")

        for expected_global in range(159, 119, -1):
            self.assertTrue(sv.can_advance_row(forward=False))
            sv.advance_row(forward=False)
            self.assertEqual(sv.current_row_idx, expected_global)
            self.assertEqual(sv.records[sv.current_row_idx].var_id, f"var_{expected_global}")

    def test_top_widget_key_and_wheel_capture(self):
        """Verify VariantSplitView captures Up/Down/PageUp/PageDown/Home/End and mouse wheel cleanly."""
        samples_30 = [f"Sample_{i:03d}" for i in range(30)]
        sv = VariantSplitView(self.records[:100], samples_30, reader=None)

        self.assertTrue(sv.handle_navigation_key("down"))
        self.assertEqual(sv.current_row_idx, 1)
        self.assertTrue(sv.handle_navigation_key("pagedown"))
        self.assertGreater(sv.current_row_idx, 1)
        prev_row = sv.current_row_idx
        self.assertTrue(sv.handle_navigation_key("up"))
        self.assertEqual(sv.current_row_idx, prev_row - 1)
        self.assertTrue(sv.handle_navigation_key("pageup"))
        self.assertEqual(sv.current_row_idx, 0)

        # Mouse wheel moves viewport scroll offset without moving row cursor
        sv.handle_mouse_scroll(delta=6)
        self.assertEqual(sv.current_row_idx, 0)
        self.assertGreater(sv._viewport_scroll_y, 0)
        saved_y = sv._viewport_scroll_y

        # Home/End scroll sample matrix horizontally without altering vertical scroll or row
        self.assertTrue(sv.handle_navigation_key("end"))
        self.assertEqual(sv.current_sample_idx, 29)
        self.assertEqual(sv._viewport_scroll_y, saved_y)
        self.assertTrue(sv.handle_navigation_key("home"))
        self.assertEqual(sv.current_sample_idx, 0)
        self.assertEqual(sv._viewport_scroll_y, saved_y)

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

    def test_large_cohort_native_sample_columns(self):
        """Verify cohorts with 500+ samples expose all columns natively to FastDataTable."""
        cohort_500 = [f"Sample_{i:04d}" for i in range(500)]
        sv = VariantSplitView(self.records[:10], cohort_500, reader=None)

        self.assertEqual(len(sv.get_visible_samples()), 500)
        self.assertEqual(sv.sample_table.backend.column_count, 500)
        self.assertEqual(sv.current_sample_idx, 0)

        sv.set_active_sample(250)
        self.assertEqual(sv.current_sample_idx, 250)
        sv.scroll_samples_end()
        self.assertEqual(sv.current_sample_idx, 499)
        sv.scroll_samples_home()
        self.assertEqual(sv.current_sample_idx, 0)


if __name__ == "__main__":
    unittest.main()
