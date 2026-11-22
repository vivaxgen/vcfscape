"""
Tests for mandatory dual-cyvcf2 VCF reader, pre-open index guard, LRU cache, and Arrow buffers.
"""

import gzip
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import cyvcf2  # noqa: F401
    CYVCF2_AVAILABLE = True
except ImportError:
    CYVCF2_AVAILABLE = False

from vcfscape.core.indexer import RecordLruCache
from vcfscape.core.vcf_reader import (
    VcfReader,
    VariantRecord,
    _MinimalSite,
    check_vcf_index_requirement,
    UnindexedLargeVcfError,
)


class TestVcfIndexing(unittest.TestCase):
    """Test suite for dual-cyvcf2 indexing, seeking, pre-open guards, and LRU caching."""

    @classmethod
    def setUpClass(cls):
        """Create a synthetic uncompressed VCF file with 2,500 variants."""
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.vcf_path = os.path.join(cls.temp_dir.name, "synthetic_large.vcf")
        cls.samples = [f"SAMPLE_{i:03d}" for i in range(20)]

        with open(cls.vcf_path, "w", encoding="utf-8") as f:
            f.write("##fileformat=VCFv4.2\n")
            f.write("##contig=<ID=Pf3D7_07_v3,length=1445207>\n")
            f.write("##contig=<ID=Pf3D7_13_v3,length=2925236>\n")
            f.write("##INFO=<ID=GENE,Number=1,Type=String,Description=\"Gene symbol\">\n")
            f.write("##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">\n")
            f.write("##FORMAT=<ID=DP,Number=1,Type=Integer,Description=\"Read Depth\">\n")
            header = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"] + cls.samples
            f.write("\t".join(header) + "\n")

            for i in range(2500):
                chrom = "Pf3D7_07_v3" if i < 1500 else "Pf3D7_13_v3"
                pos = 400000 + i * 10
                var_id = f"var_{i}"
                ref = "A"
                alt = "T" if i % 2 == 0 else "G"
                qual = "99.0"
                filter_s = "PASS"
                info = "GENE=crt" if i < 1500 else "GENE=k13"
                fmt = "GT:DP"
                calls = [f"{i%2}/1:45" for _ in cls.samples]
                line = [chrom, str(pos), var_id, ref, alt, qual, filter_s, info, fmt] + calls
                f.write("\t".join(line) + "\n")

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_lru_cache(self):
        cache = RecordLruCache(maxsize=3)
        cache.put(1, "one")
        cache.put(2, "two")
        cache.put(3, "three")
        self.assertEqual(len(cache), 3)
        self.assertEqual(cache.get(1), "one")

        cache.put(4, "four")
        self.assertIsNone(cache.get(2))
        self.assertEqual(cache.get(1), "one")
        self.assertEqual(cache.get(3), "three")
        self.assertEqual(cache.get(4), "four")

    def test_large_unindexed_vcf_guard_does_not_open_file(self):
        """Files larger than threshold without a .tbi/.csi index must fail before opening."""
        gz_path = os.path.join(self.temp_dir.name, "large_guard_test.vcf.gz")
        with open(self.vcf_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            f_out.writelines(f_in)

        with patch("builtins.open", side_effect=AssertionError("VCF must not be opened")) as mock_open:
            with self.assertRaises(UnindexedLargeVcfError) as ctx:
                check_vcf_index_requirement(gz_path, max_unindexed_bytes=10)
            mock_open.assert_not_called()

        self.assertIn("tabix", ctx.exception.suggested_command)

        tbi_path = f"{gz_path}.tbi"
        with open(tbi_path, "wb") as f:
            f.write(b"TBI")
        check_vcf_index_requirement(gz_path, max_unindexed_bytes=10)

    def test_mandatory_cyvcf2_error_when_missing(self):
        """VcfReader raises RuntimeError when cyvcf2 is unavailable (no Python fallback)."""
        with patch("vcfscape.core.vcf_reader.cyvcf2", None):
            with self.assertRaises(RuntimeError) as ctx:
                VcfReader(self.vcf_path, lazy=True)
            self.assertIn("cyvcf2", str(ctx.exception))

    def test_dual_arrow_buffers_streaming_and_hydration(self):
        """FixedArrowBuffer and single-tag SampleArrowBuffer track site projections and in-place hydration."""
        from vcfscape.core.arrow_buffer import FixedArrowBuffer, SampleArrowBuffer

        site_rec = _MinimalSite(
            chrom="Pf3D7_07_v3",
            pos=403625,
            var_id="var_crt",
            ref="G",
            alt=("T",),
            qual=99.0,
            filter_str="PASS",
        ).to_variant_record(info={"GENE": "crt"}, format_keys=["GT", "DP"])

        full_rec = VariantRecord(
            chrom="Pf3D7_07_v3",
            pos=403625,
            var_id="var_crt",
            ref="G",
            alt=["T"],
            qual=99.0,
            filter_str="PASS",
            info={"GENE": "crt"},
            format_keys=["GT", "DP"],
            sample_data={
                "S1": {"GT": "0/1", "DP": "45", "AD": ".", "GQ": "."},
                "S2": {"GT": "1/1", "DP": "60", "AD": ".", "GQ": "."},
            },
            genotypes={"S1": (0, 1), "S2": (1, 1)},
            depths={"S1": 45, "S2": 60},
            ad={"S1": [], "S2": []},
            samples_loaded=True,
        )

        fixed_buf = FixedArrowBuffer([site_rec])
        self.assertEqual(fixed_buf.row_count, 1)
        self.assertEqual(fixed_buf.get_columns_for_mode("compact"), ["CHROM", "POS", "REF", "ALT"])
        self.assertEqual(fixed_buf.get_columns_for_mode("essential"), ["CHROM", "POS"])

        sample_buf = SampleArrowBuffer(visible_samples=["S1", "S2"], records=[site_rec])
        self.assertEqual(sample_buf.row_count, 1)
        self.assertEqual(sample_buf.get_cell_value(0, 0, "GT"), "...")
        self.assertEqual(sample_buf.get_cell_value(0, 1, "DP"), "...")

        self.assertTrue(sample_buf.hydrate_rows([0], {0: full_rec}))
        self.assertEqual(sample_buf.get_cell_value(0, 0, "GT"), "0/1")
        self.assertEqual(sample_buf.get_cell_value(0, 1, "DP"), "60")

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_cyvcf2_vcf_reader_fast_startup(self):
        t0 = time.perf_counter()
        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            init_time_ms = (time.perf_counter() - t0) * 1000
            self.assertLess(init_time_ms, 250)
            self.assertEqual(len(reader.samples), 20)
            self.assertEqual(reader.total_variants, 2500)
            self.assertEqual(len(reader.contigs), 2)
            self.assertTrue(reader.backend.startswith("cyvcf2_dual"))
        finally:
            reader.close()

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_cyvcf2_vcf_reader_slices(self):
        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            slice_100 = reader.get_slice(offset=1200, limit=25)
            self.assertEqual(len(slice_100), 25)
            self.assertEqual(slice_100[0].var_id, "var_1200")
            self.assertEqual(slice_100[-1].var_id, "var_1224")
        finally:
            reader.close()

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_query_region(self):
        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            region_records = reader.query_region("Pf3D7_07_v3", 405000, 406000, limit=100)
            self.assertGreater(len(region_records), 0)
            for r in region_records:
                self.assertEqual(r.chrom, "Pf3D7_07_v3")
                self.assertGreaterEqual(r.pos, 405000)
                self.assertLessEqual(r.pos, 406000)
        finally:
            reader.close()

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_lazy_streaming_filter_records(self):
        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            filtered = reader.filter_records(variant_type="SNP", limit=10)
            self.assertEqual(len(filtered), 10)
            for r in filtered:
                self.assertIn("SNP", r.var_type)
        finally:
            reader.close()

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_async_background_counting_and_callback(self):
        gz_path = os.path.join(self.temp_dir.name, "test_async.vcf.gz")
        with open(self.vcf_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            f_out.writelines(f_in)

        reader = VcfReader(gz_path, lazy=True)
        try:
            received_count = []
            reader.add_total_variants_callback(lambda count: received_count.append(count))
            total = reader.total_variants
            self.assertEqual(total, 2500)
            self.assertTrue(reader.total_variants_ready)
            self.assertIn(2500, received_count)
        finally:
            reader.close()

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_site_only_parsing_and_async_hydration(self):
        """Handle 1 serves unhydrated sites immediately while Handle 2 hydrates samples asynchronously."""
        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            placeholder_or_hydrated = reader.get_slice(offset=500, limit=10, allow_placeholder=True)
            self.assertEqual(len(placeholder_or_hydrated), 10)
            self.assertEqual(placeholder_or_hydrated[0].var_id, "var_500")

            deadline = time.time() + 2.0
            hydrated = reader.get_hydrated_record(500)
            while hydrated and not hydrated.samples_loaded and time.time() < deadline:
                time.sleep(0.02)
                hydrated = reader.get_hydrated_record(500)

            self.assertIsNotNone(hydrated)
            self.assertTrue(hydrated.samples_loaded)
            self.assertEqual(len(hydrated.sample_data), 20)
        finally:
            reader.close()

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_minimal_handle1_sites_and_clean_close(self):
        """Background Handle 1 stores minimal core tuples only, and close() stops workers cleanly."""
        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            self.assertEqual(reader.total_variants, 2500)
            if reader._site_thread is not None and reader._site_thread.is_alive():
                reader._site_thread.join(timeout=5.0)
            with reader._site_lock:
                self.assertEqual(len(reader._site_records), 2500)
                self.assertIsInstance(reader._site_records[200], _MinimalSite)
        finally:
            reader.close()
        self.assertTrue(reader._stop_event.is_set())
        self.assertEqual(reader._progress_callbacks, [])
        self.assertEqual(reader._count_callbacks, [])
        self.assertEqual(reader._hydration_callbacks, [])

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_gzipped_vcf_close_stops_workers_quickly(self):
        """VcfReader.close() stops active .vcf.gz site/sample threads cleanly without hanging."""
        gz_path = self.vcf_path + ".gz"
        with open(self.vcf_path, "rt", encoding="utf-8") as src, gzip.open(gz_path, "wt", encoding="utf-8") as dst:
            dst.write(src.read())

        try:
            reader = VcfReader(gz_path, lazy=True)
            reader.request_sample_hydration(0, 150)
            t0 = time.monotonic()
            reader.close()
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 1.0)
            self.assertTrue(reader._stop_workers)
            self.assertTrue(reader._stop_event.is_set())
            self.assertEqual(reader._progress_callbacks, [])
            self.assertEqual(reader._count_callbacks, [])
            self.assertEqual(reader._hydration_callbacks, [])
            if reader._sample_thread is not None:
                self.assertFalse(reader._sample_thread.is_alive())
            if reader._site_thread is not None:
                self.assertFalse(reader._site_thread.is_alive())
        finally:
            if os.path.exists(gz_path):
                os.remove(gz_path)

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_close_nonblocking_returns_immediately(self):
        """VcfReader.close(wait=False) signals stop immediately without blocking the UI thread."""
        gz_path = self.vcf_path + ".nonblock.gz"
        with open(self.vcf_path, "rt", encoding="utf-8") as src, gzip.open(gz_path, "wt", encoding="utf-8") as dst:
            dst.write(src.read())

        try:
            reader = VcfReader(gz_path, lazy=True)
            reader.request_sample_hydration(0, 150)
            t0 = time.monotonic()
            reader.close(wait=False)
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.05)
            self.assertTrue(reader._stop_workers)
            self.assertTrue(reader._stop_event.is_set())
            reader.close(wait=True, timeout=1.0)
        finally:
            if os.path.exists(gz_path):
                os.remove(gz_path)


if __name__ == "__main__":
    unittest.main()
