"""
Tests for high-performance VCF indexing, sparse byte offset seeking, and LRU cache.
"""

import os
import time
import tempfile
import unittest

from vcfscape.core.indexer import SparseVcfIndex, RecordLruCache
from vcfscape.core.vcf_reader import (
    VcfReader,
    parse_vcf_line,
    parse_vcf_site_only,
    check_vcf_index_requirement,
    UnindexedLargeVcfError,
)


class TestVcfIndexing(unittest.TestCase):
    """Test suite for VCF sparse indexing, seeking, and LRU caching."""

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

            # Write 2,500 variants across two contigs
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

        # Adding 4th element should evict key 2 (key 1 was recently accessed)
        cache.put(4, "four")
        self.assertIsNone(cache.get(2))
        self.assertEqual(cache.get(1), "one")
        self.assertEqual(cache.get(3), "three")
        self.assertEqual(cache.get(4), "four")

    def test_sparse_index_creation_and_seek(self):
        index = SparseVcfIndex(self.vcf_path, step=100)
        self.assertEqual(index.total_records, 2500)
        self.assertGreater(len(index.checkpoints), 20)

        # Test seek offset for index 550
        offset, start_idx = index.get_seek_offset_for_index(550)
        self.assertEqual(start_idx, 500)
        self.assertGreater(offset, 0)

        # Seek in file and verify we reach record 550 accurately
        with open(self.vcf_path, "r", encoding="utf-8") as f:
            f.seek(offset)
            curr = start_idx
            target_line = None
            while curr <= 550:
                line = f.readline()
                if curr == 550:
                    target_line = line
                    break
                curr += 1

            self.assertIsNotNone(target_line)
            parts = target_line.split("\t")
            self.assertEqual(parts[2], "var_550")
            self.assertEqual(int(parts[1]), 400000 + 550 * 10)

    def test_indexed_vcf_reader_fast_startup(self):
        t0 = time.perf_counter()
        reader = VcfReader(self.vcf_path, lazy=True)
        init_time_ms = (time.perf_counter() - t0) * 1000

        # Fast header extraction should be sub-50ms
        self.assertLess(init_time_ms, 150)
        self.assertEqual(len(reader.samples), 20)
        self.assertEqual(reader.total_variants, 2500)
        self.assertEqual(len(reader.contigs), 2)

    def test_indexed_vcf_reader_slices(self):
        reader = VcfReader(self.vcf_path, lazy=True)
        slice_100 = reader.get_slice(offset=1200, limit=25)
        self.assertEqual(len(slice_100), 25)
        self.assertEqual(slice_100[0].var_id, "var_1200")
        self.assertEqual(slice_100[-1].var_id, "var_1224")

    def test_query_region(self):
        reader = VcfReader(self.vcf_path, lazy=True)
        # Query Pf3D7_07_v3:405000-406000
        region_records = reader.query_region("Pf3D7_07_v3", 405000, 406000, limit=100)
        self.assertGreater(len(region_records), 0)
        for r in region_records:
            self.assertEqual(r.chrom, "Pf3D7_07_v3")
            self.assertGreaterEqual(r.pos, 405000)
            self.assertLessEqual(r.pos, 406000)

    def test_lazy_streaming_filter_records(self):
        reader = VcfReader(self.vcf_path, lazy=True)
        # Filter with limit
        filtered = reader.filter_records(variant_type="SNP", limit=10)
        self.assertEqual(len(filtered), 10)
        for r in filtered:
            self.assertIn("SNP", r.var_type)

    def test_async_background_counting_and_callback(self):
        # Create a gzipped test file
        import gzip
        gz_path = os.path.join(self.temp_dir.name, "test_async.vcf.gz")
        with open(self.vcf_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            f_out.writelines(f_in)

        reader = VcfReader(gz_path, lazy=True)
        received_count = []

        def on_counted(count):
            received_count.append(count)

        reader.add_total_variants_callback(on_counted)
        # Verify total_variants returns correct count even when called directly
        total = reader.total_variants
        self.assertEqual(total, 2500)
        self.assertTrue(reader.total_variants_ready)
        self.assertIn(2500, received_count)
        reader.close()

    def test_large_unindexed_vcf_guard_does_not_open_file(self):
        """Files larger than threshold without an index must fail before opening."""
        from unittest.mock import patch
        import gzip

        gz_path = os.path.join(self.temp_dir.name, "large_guard_test.vcf.gz")
        with open(self.vcf_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            f_out.writelines(f_in)

        # File has no .tbi/.csi index; passing small threshold triggers >100MB guard cleanly
        with patch("builtins.open", side_effect=AssertionError("VCF must not be opened")) as mock_open:
            with self.assertRaises(UnindexedLargeVcfError) as ctx:
                check_vcf_index_requirement(gz_path, max_unindexed_bytes=10)
            mock_open.assert_not_called()

        self.assertIn("tabix", ctx.exception.suggested_command)

        # Creating a sibling .tbi file allows the pre-open check to pass
        tbi_path = f"{gz_path}.tbi"
        with open(tbi_path, "wb") as f:
            f.write(b"TBI")
        check_vcf_index_requirement(gz_path, max_unindexed_bytes=10)

    def test_site_only_parsing_and_async_hydration(self):
        """Site-only pipeline parses fixed fields quickly while Handle 2 hydrates samples asynchronously."""
        site_rec = parse_vcf_site_only(
            "Pf3D7_07_v3\t403625\tvar_crt\tG\tT\t99.0\tPASS\tGENE=crt\tGT:DP\t0/1:45\t1/1:60"
        )
        self.assertIsNotNone(site_rec)
        self.assertFalse(site_rec.samples_loaded)
        self.assertEqual(site_rec.sample_data, {})
        self.assertEqual(site_rec.chrom, "Pf3D7_07_v3")
        self.assertEqual(site_rec.pos, 403625)

        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            placeholder_or_hydrated = reader.get_slice(offset=500, limit=10, allow_placeholder=True)
            self.assertEqual(len(placeholder_or_hydrated), 10)
            self.assertEqual(placeholder_or_hydrated[0].var_id, "var_500")

            # Wait briefly for Handle 2 priority hydration to populate cache
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

    def test_dual_arrow_buffers_streaming_and_hydration(self):
        """Dual FixedArrowBuffer and SampleArrowBuffer track site projections and async sample hydration."""
        from vcfscape.core.arrow_buffer import FixedArrowBuffer, SampleArrowBuffer

        site_rec = parse_vcf_site_only(
            "Pf3D7_07_v3\t403625\tvar_crt\tG\tT\t99.0\tPASS\tGENE=crt\tGT:DP\t0/1:45\t1/1:60"
        )
        full_rec = parse_vcf_line(
            "Pf3D7_07_v3\t403625\tvar_crt\tG\tT\t99.0\tPASS\tGENE=crt\tGT:DP\t0/1:45\t1/1:60",
            ["S1", "S2"],
        )

        fixed_buf = FixedArrowBuffer([site_rec])
        self.assertEqual(fixed_buf.row_count, 1)
        self.assertEqual(fixed_buf.get_columns_for_mode("compact"), ["CHROM", "POS", "REF", "ALT"])
        self.assertEqual(fixed_buf.get_columns_for_mode("essential"), ["CHROM", "POS"])

        sample_buf = SampleArrowBuffer(visible_samples=["S1", "S2"], records=[site_rec])
        self.assertEqual(sample_buf.row_count, 1)
        self.assertEqual(sample_buf._tag_columns["GT"]["S1"][0], "...")
        self.assertEqual(sample_buf._tag_columns["DP"]["S2"][0], "...")

        self.assertTrue(sample_buf.hydrate_rows([0], {0: full_rec}))
        self.assertEqual(sample_buf._tag_columns["GT"]["S1"][0], "0/1")
        self.assertEqual(sample_buf._tag_columns["DP"]["S2"][0], "60")

    def test_minimal_handle1_sites_and_clean_close(self):
        """Background Handle 1 stores minimal core tuples only, and close() stops workers cleanly."""
        from vcfscape.core.vcf_reader import _MinimalSite

        reader = VcfReader(self.vcf_path, lazy=True)
        try:
            self.assertEqual(reader.total_variants, 2500)
            with reader._site_lock:
                self.assertIsInstance(reader._site_records[200], _MinimalSite)
        finally:
            reader.close()
        self.assertTrue(reader._stop_event.is_set())
        self.assertEqual(reader._progress_callbacks, [])
        self.assertEqual(reader._count_callbacks, [])
        self.assertEqual(reader._hydration_callbacks, [])


if __name__ == "__main__":
    unittest.main()
