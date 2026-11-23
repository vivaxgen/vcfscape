"""
Unit tests for VariantSplitView dynamic appending, in-place sample hydration without
backend resets, top-widget key/mouse-wheel capture, and lockstep scrolling.
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
        """Verify FixedVariantTable appends full rows while SampleMatrixTable stays fixed at viewport size."""
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
        self.assertEqual(sv.fixed_buffer.row_count, 150)
        self.assertEqual(sv.fixed_table.row_count, 150)
        self.assertLessEqual(sv.sample_table.row_count, 25)
        self.assertEqual(len(sv.records), sv.sample_table.row_count)

        self.assertTrue(sv.fetch_more_rows(100))
        self.assertEqual(sv.fixed_buffer.row_count, 250)
        self.assertEqual(sv.fixed_table.row_count, 250)
        self.assertLessEqual(sv.sample_table.row_count, 25)

        self.assertTrue(sv.fetch_more_rows(250))
        self.assertEqual(sv.fixed_buffer.row_count, 500)
        self.assertEqual(sv.fixed_table.row_count, 500)
        self.assertLessEqual(sv.sample_table.row_count, 25)

    def test_async_site_stream_populates_fixed_table_and_direct_filters(self):
        """Verify Handle 1 async _MinimalSite streaming fills FixedArrowBuffer and filters directly."""
        from vcfscape.core.vcf_reader import _MinimalSite

        sites = [
            _MinimalSite(
                chrom="Pf3D7_07_v3" if i % 10 == 0 else "Pf3D7_01_v3",
                pos=403625 if i == 50 else (1000 + i * 20),
                var_id=f"site_{i}",
                ref="AT" if i % 4 == 0 else "A",
                alt=("A",) if i % 4 == 0 else ("T",),
                qual=60.0 if i % 2 == 0 else 10.0,
                filter_str="PASS",
            )
            for i in range(400)
        ]

        class StreamingSiteReader:
            def __init__(self, all_sites, hydrated_recs):
                self._sites = all_sites
                self._hydrated = hydrated_recs
                self.streamed_until = 150
                self.total_variants_ready = False
                self.samples = ["S1"]
                self.requested_index_batches = []
            def get_site_slice(self, offset=0, limit=None):
                end = self.streamed_until if limit is None else min(self.streamed_until, offset + limit)
                return self._sites[offset:end]
            def request_sample_indices(self, indices):
                self.requested_index_batches.append(list(indices))
            def get_hydrated_record(self, row_idx):
                s = self._sites[row_idx]
                rec = s.to_variant_record()
                if row_idx == 0:
                    rec.sample_data = {"S1": {"GT": "0/1", "DP": "25"}}
                    rec.samples_loaded = True
                return rec
            def get_total_variants_async(self):
                return len(self._sites) if self.total_variants_ready else None

        reader = StreamingSiteReader(sites, self.records[:400])
        initial = [s.to_variant_record() for s in sites[:150]]
        sv = VariantSplitView(initial, ["S1"], reader=reader)
        self.assertEqual(sv.fixed_buffer.row_count, 150)

        # Simulate background Handle 1 progress arriving asynchronously
        reader.streamed_until = 400
        reader.total_variants_ready = True
        sv.update_total_variants(400)

        self.assertEqual(sv.fixed_buffer.row_count, 400)
        self.assertEqual(sv.fixed_table.row_count, 400)
        self.assertLessEqual(sv.sample_table.row_count, 25)

        # Direct in-memory INDEL filter on FixedArrowBuffer
        reader.requested_index_batches.clear()
        matched = sv.apply_filter(variant_type="INDEL")
        self.assertEqual(matched, 100)
        self.assertEqual(sv.fixed_table.row_count, 100)
        self.assertLessEqual(sv.sample_table.row_count, 25)
        self.assertEqual(sv.records[0].var_id, "site_0")
        self.assertTrue(reader.requested_index_batches)
        self.assertTrue(all(idx % 4 == 0 for idx in reader.requested_index_batches[-1]))

        # Direct region jump lookup on FixedArrowBuffer finds Pfcrt K76T site at row 50
        self.assertTrue(sv.apply_filter(variant_type="ALL") == 400)
        self.assertTrue(sv.jump_to_region("Pf3D7_07_v3", 403600))
        self.assertGreaterEqual(sv.fixed_table.row_count, 1)
        self.assertEqual(sv.records[0].pos, 403625)

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
        self.assertEqual(sv.fixed_buffer.row_count, 150)

        self.assertTrue(sv.fetch_more_rows(200))
        self.assertEqual(sv.fixed_buffer.row_count, 350)
        self.assertEqual(sv.fixed_table.row_count, 350)

        sv.update_total_variants(500)
        self.assertEqual(sv.total_records_count, 500)

    def test_advance_row_monotonic_across_boundary(self):
        """Verify advancing row by row across window boundary keeps cursor monotonic and slides SampleMatrixTable."""
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
        self.assertEqual(sv.get_record_at_display_row(sv.current_row_idx).var_id, "var_130")

        for expected_global in range(131, 161):
            self.assertTrue(sv.can_advance_row(forward=True))
            sv.advance_row(forward=True)
            self.assertEqual(sv.current_row_idx, expected_global)
            self.assertEqual(sv.get_record_at_display_row(sv.current_row_idx).var_id, f"var_{expected_global}")
            local_row = sv.current_row_idx - sv._viewport_scroll_y
            self.assertEqual(sv.records[local_row].var_id, f"var_{expected_global}")

        self.assertGreaterEqual(sv.fixed_buffer.row_count, 250)
        self.assertEqual(sv.get_record_at_display_row(sv.current_row_idx).var_id, "var_160")

        for expected_global in range(159, 119, -1):
            self.assertTrue(sv.can_advance_row(forward=False))
            sv.advance_row(forward=False)
            self.assertEqual(sv.current_row_idx, expected_global)
            self.assertEqual(sv.get_record_at_display_row(sv.current_row_idx).var_id, f"var_{expected_global}")

    def test_in_place_hydration_preserves_backend_and_scroll_state(self):
        """Hydrating unhydrated global rows maps into local viewport rows without swapping sample_table.backend."""
        placeholder_recs = [
            VariantRecord(
                chrom="Pf3D7_07_v3",
                pos=1000 + i * 50,
                var_id=f"var_{i}",
                ref="A",
                alt=["T"],
                qual=99.0,
                filter_str="PASS",
                info={},
                format_keys=["GT", "DP"],
                sample_data={},
                genotypes={},
                depths={},
                ad={},
                samples_loaded=False,
            )
            for i in range(60)
        ]

        class HydratingMockReader:
            def __init__(self, hydrated_records, placeholders):
                self._hydrated = hydrated_records
                self._placeholders = placeholders
                self._ready = set()
                self.total_variants_ready = True
                self.samples = ["S1"]
            def get_total_variants_async(self):
                return len(self._hydrated)
            def get_hydrated_record(self, row_idx):
                if row_idx in self._ready:
                    return self._hydrated[row_idx]
                return self._placeholders[row_idx]

        reader = HydratingMockReader(self.records[:60], placeholder_recs)
        sv = VariantSplitView(placeholder_recs, ["S1"], reader=reader)
        initial_backend = sv.sample_table.backend

        # Slide viewport past row 30 so global row 35 maps to local viewport row (35 - _viewport_scroll_y)
        sv.set_active_row(35)
        local_idx = 35 - sv._sample_window_start
        self.assertEqual(sv.sample_table.backend.get_cell_at(local_idx, 0).plain, "...")

        # Mark global rows hydrated and notify SplitView
        reader._ready.update([35, 36, 37])
        sv.hydrate_rows([35, 36, 37])

        # Backend object identity must stay unchanged (no set_backend reset)
        self.assertIs(sv.sample_table.backend, initial_backend)
        self.assertEqual(sv.current_row_idx, 35)
        self.assertEqual(sv.sample_table.backend.get_cell_at(local_idx, 0).plain, "0/1")

    def test_top_widget_key_and_wheel_capture(self):
        """Verify VariantSplitView captures Up/Down/PageUp/PageDown/Home/End and mouse wheel cleanly."""
        samples_30 = [f"Sample_{i:03d}" for i in range(30)]
        sv = VariantSplitView(self.records[:100], samples_30, reader=None)
        initial_backend = sv.sample_table.backend

        self.assertTrue(sv.handle_navigation_key("down"))
        self.assertEqual(sv.current_row_idx, 1)
        self.assertTrue(sv.handle_navigation_key("pagedown"))
        self.assertGreater(sv.current_row_idx, 1)
        prev_row = sv.current_row_idx
        self.assertTrue(sv.handle_navigation_key("up"))
        self.assertEqual(sv.current_row_idx, prev_row - 1)
        self.assertTrue(sv.handle_navigation_key("pageup"))
        self.assertEqual(sv.current_row_idx, 0)

        # Mouse wheel slides viewport buffer without moving row cursor or replacing backend
        sv.handle_mouse_scroll(delta=6)
        self.assertEqual(sv.current_row_idx, 0)
        self.assertEqual(sv._viewport_scroll_y, 6)
        self.assertEqual(sv._sample_window_start, 6)
        self.assertEqual(sv.records[0].var_id, "var_6")
        self.assertIs(sv.sample_table.backend, initial_backend)
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

    def test_sample_vertical_scrollbar_hidden_above_1000_rows(self):
        """Hide vertical scrollbar on SampleMatrixTable when total or loaded rows > 1000."""
        # Small <= 1000 dataset shows vertical scrollbar
        sv = VariantSplitView(self.records[:20], ["S1", "S2"], reader=None)
        self.assertFalse(sv.should_hide_sample_vertical_scrollbar())
        self.assertTrue(sv.sample_table.show_vertical_scrollbar)
        self.assertTrue(sv.sample_table.show_horizontal_scrollbar)
        self.assertFalse(sv.sample_table.has_class("no-vertical-scrollbar"))

        # Progress crossing 1000 hides vertical scrollbar while keeping horizontal scrollbar & scrolling
        sv.update_counting_progress(1001)
        self.assertTrue(sv.should_hide_sample_vertical_scrollbar())
        self.assertFalse(sv.sample_table.show_vertical_scrollbar)
        self.assertTrue(sv.sample_table.show_horizontal_scrollbar)
        self.assertTrue(sv.sample_table.has_class("no-vertical-scrollbar"))

        # Keyboard & wheel vertical scrolling remain active
        sv.handle_navigation_key("down")
        self.assertEqual(sv.current_row_idx, 1)
        sv.handle_mouse_scroll(delta=3)
        self.assertGreaterEqual(sv._viewport_scroll_y, 0)

        # Filtering down to <= 1000 restores vertical scrollbar
        sv.set_records(self.records[:50], is_main_stream=False)
        self.assertFalse(sv.should_hide_sample_vertical_scrollbar())
        self.assertTrue(sv.sample_table.show_vertical_scrollbar)
        self.assertFalse(sv.sample_table.has_class("no-vertical-scrollbar"))

        # Loaded rows > 1000 also hides vertical scrollbar even without external reader total
        sv.set_records(self.records * 3, is_main_stream=False)
        self.assertEqual(sv.fixed_buffer.row_count, 1500)
        self.assertLessEqual(sv.sample_table.row_count, 25)
        self.assertTrue(sv.should_hide_sample_vertical_scrollbar())
        self.assertFalse(sv.sample_table.show_vertical_scrollbar)
        self.assertTrue(sv.sample_table.show_horizontal_scrollbar)
        self.assertTrue(sv.sample_table.has_class("no-vertical-scrollbar"))


class TestFixedArrowBufferFiltering(unittest.TestCase):
    """Tests FixedArrowBuffer Handle 1 minimal-site appending, lazy metadata, and direct filtering."""

    def test_minimal_site_append_filter_region_and_lazy_metadata(self):
        from vcfscape.core.arrow_buffer import FixedArrowBuffer
        from vcfscape.core.vcf_reader import _MinimalSite

        sites = [
            _MinimalSite("Pf3D7_01_v3", 1000, "r0", "A", ("T",), 50.0, "PASS"),
            _MinimalSite("Pf3D7_07_v3", 403625, "k76t", "A", ("T",), 99.0, "PASS"),
            _MinimalSite("Pf3D7_12_v3", 974200, "poly", "AT", ("A", "ATT"), 25.0, "LowQual"),
            _MinimalSite("Pf3D7_13_v3", 1725259, "c580y", "C", ("T", "A"), 120.0, "PASS"),
        ]

        buf = FixedArrowBuffer(sites[:2])
        self.assertEqual(buf.row_count, 2)
        self.assertTrue(buf.is_drug_row(1))
        self.assertFalse(buf.is_drug_row(0))
        self.assertEqual(buf.get_cell_value(1, "GENE"), "Pfcrt")
        self.assertEqual(buf.get_cell_value(1, "INFO"), ".")

        # Async batch append remaining _MinimalSite objects
        buf.append_records(sites[2:])
        self.assertEqual(buf.row_count, 4)
        self.assertTrue(buf.is_drug_row(3))
        self.assertEqual(buf.get_cell_value(3, "GENE"), "Pfkelch13")

        # Direct in-memory filtering on FixedArrowBuffer
        self.assertEqual(buf.filter_indices(variant_type="INDEL"), [2])
        self.assertEqual(buf.filter_indices(variant_type="SNP"), [0, 1, 3])
        self.assertEqual(buf.filter_indices(variant_type="DRUG_RESISTANT"), [1, 2, 3])
        self.assertEqual(buf.filter_indices(variant_type="MULTI_ALLELIC"), [2, 3])
        self.assertEqual(buf.filter_indices(min_qual=80.0), [1, 3])
        self.assertEqual(buf.filter_indices(filter_status="LowQual"), [2])
        self.assertEqual(buf.filter_indices(search_query="C580Y"), [3])
        self.assertEqual(buf.filter_indices(search_query="artemisinin"), [3])

        # Direct region lookup on core CHROM/POS arrays
        self.assertEqual(buf.find_region_indices("Pf3D7_13_v3", 1725000, 1726000), [3])
        self.assertEqual(buf.find_region_indices("Pf3D7_07_v3", 403000, 404000), [1])

        # Lazy INFO/FORMAT override on visible hydrated row
        hydrated_rec = VariantRecord(
            chrom="Pf3D7_13_v3",
            pos=1725259,
            var_id="c580y",
            ref="C",
            alt=["T", "A"],
            qual=120.0,
            filter_str="PASS",
            info={"GENE": "Pfkelch13", "MUT": "C580Y"},
            format_keys=["GT", "DP", "AD"],
            sample_data={"S1": {"GT": "0/1"}},
            genotypes={"S1": (0, 1)},
            depths={"S1": 30},
            ad={"S1": [15, 15]},
        )
        self.assertTrue(buf.update_row_metadata(3, hydrated_rec))
        self.assertEqual(buf.get_cell_value(3, "INFO"), "GENE=Pfkelch13;MUT=C580Y")
        self.assertEqual(buf.get_cell_value(3, "FORMAT"), "GT:DP:AD")


if __name__ == "__main__":
    unittest.main()
