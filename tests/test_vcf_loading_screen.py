"""
Unit tests for inline HeaderBar / FooterBar progress reporting and VcfReader callbacks.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import cyvcf2  # noqa: F401
    CYVCF2_AVAILABLE = True
except ImportError:
    CYVCF2_AVAILABLE = False

try:
    import textual  # noqa: F401
    from vcfscape.ui.widgets.header_bar import HeaderBar
    from vcfscape.ui.widgets.footer_bar import FooterBar
    TEXTUAL_AVAILABLE = True
except ImportError:
    HeaderBar = None
    FooterBar = None
    TEXTUAL_AVAILABLE = False


class TestInlineProgressReporting(unittest.TestCase):

    @unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual not installed in this environment")
    def test_header_bar_inline_counting_progress_rendering(self):
        hb = HeaderBar(filename="cohort_malaria.vcf.gz", total_variants=None, total_samples=12)
        self.assertIn("Counting...", hb.render().plain)

        hb.counting_progress = 15000
        self.assertIn("Counting (15,000)...", hb.render().plain)

        hb.total_variants = 52400
        rendered = hb.render().plain
        self.assertIn("52,400", rendered)
        self.assertNotIn("Counting", rendered)

    @unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual not installed in this environment")
    def test_footer_bar_inline_progress_log(self):
        fb = FooterBar()
        fb.set_log("Indexing variants in background: 2,000 sites...")
        self.assertIn("2,000 sites", fb.render().plain)

        fb.set_log("VCF file indexing complete: 2,500 total variants.")
        self.assertIn("2,500 total variants", fb.render().plain)

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_vcf_reader_progress_callbacks(self):
        from vcfscape.core.vcf_reader import VcfReader

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False) as f:
            f.write("##fileformat=VCFv4.2\n")
            f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n")
            for i in range(25):
                f.write(f"Pf3D7_07_v3\t{1000 + i * 10}\t.\tA\tT\t99\tPASS\t.\tGT\t0/1\n")
            temp_path = f.name

        try:
            reader = VcfReader(temp_path, lazy=True)
            try:
                progress_calls = []
                total_calls = []

                reader.add_progress_callback(lambda count: progress_calls.append(count))
                reader.add_total_variants_callback(lambda count: total_calls.append(count))

                self.assertEqual(reader.total_variants, 25)
                self.assertTrue(len(total_calls) > 0)
                self.assertEqual(total_calls[-1], 25)
            finally:
                reader.close()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @unittest.skipUnless(CYVCF2_AVAILABLE, "cyvcf2 not installed in this environment")
    def test_async_uncompressed_vcf_indexing_progress(self):
        """Verify uncompressed VCF starts immediately via cyvcf2 and streams progress callbacks."""
        from vcfscape.core.vcf_reader import VcfReader

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False) as f:
            f.write("##fileformat=VCFv4.2\n")
            f.write("##contig=<ID=Pf3D7_07_v3,length=1445207>\n")
            f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n")
            for i in range(2500):
                f.write(f"Pf3D7_07_v3\t{1000 + i * 5}\tvar_{i}\tA\tT\t99\tPASS\t.\tGT\t0/1\n")
            temp_path = f.name

        try:
            reader = VcfReader(temp_path, lazy=True)
            try:
                init_slice = reader.get_slice(0, 10)
                self.assertEqual(len(init_slice), 10)
                self.assertEqual(init_slice[0].var_id, "var_0")

                progress_counts = []
                reader.add_progress_callback(lambda count: progress_counts.append(count))

                total = reader.total_variants
                self.assertEqual(total, 2500)
                self.assertTrue(reader.total_variants_ready)
                self.assertTrue(len(progress_counts) > 0)
                self.assertEqual(progress_counts[-1], 2500)
            finally:
                reader.close()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
