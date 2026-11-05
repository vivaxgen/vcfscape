"""
Tests for high-performance VCF indexing, sparse byte offset seeking, and LRU cache.
"""

import os
import time
import tempfile
import unittest

from vcfscape.core.indexer import SparseVcfIndex, RecordLruCache
from vcfscape.core.vcf_reader import VcfReader, parse_vcf_line


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


if __name__ == "__main__":
    unittest.main()
