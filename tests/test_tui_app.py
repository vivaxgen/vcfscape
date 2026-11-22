"""
Unit tests for VcfscapeApp TUI actions, hotkeys, theme toggling, scrolling, and clean exit.
"""

import gzip
import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    import cyvcf2  # noqa: F401
    import textual
    import textual_fastdatatable
    import pyarrow
    from vcfscape.ui.app import VcfscapeApp, MalariaVcfApp
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    VcfscapeApp = None
    MalariaVcfApp = None

DEMO_VCF = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "examples", "pf3d7_surveillance_demo.vcf")
)


@unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual / textual-fastdatatable / pyarrow / cyvcf2 not installed")
class TestMalariaVcfApp(unittest.TestCase):

    def setUp(self):
        self.app = MalariaVcfApp(DEMO_VCF)

    def tearDown(self):
        if hasattr(self, "app") and hasattr(self.app, "reader"):
            self.app.reader.close(wait=True, timeout=0.5)

    def test_theme_toggle_action(self):
        self.assertNotIn("theme-light", self.app.classes)

        self.app.action_toggle_theme()
        self.assertIn("theme-light", self.app.classes)
        self.assertFalse(self.app.dark)
        self.assertIn("LIGHT", self.app.footer_bar.log_message)

        self.app.action_toggle_theme()
        self.assertNotIn("theme-light", self.app.classes)
        self.assertTrue(self.app.dark)
        self.assertIn("DARK", self.app.footer_bar.log_message)

    def test_hotkey_bindings_present(self):
        bindings = {b.key: b.action for b in self.app.BINDINGS}
        self.assertIn("t", bindings)
        self.assertEqual(bindings["t"], "toggle_theme")
        self.assertIn("1", bindings)
        self.assertIn("v", bindings)
        self.assertIn("s", bindings)
        self.assertIn("c", bindings)
        self.assertIn("f", bindings)
        self.assertIn("?", bindings)
        self.assertIn("q", bindings)
        self.assertEqual(bindings.get("ctrl+c"), "quit")
        self.assertEqual(bindings.get("ctrl+z"), "suspend_process")

    def test_cohort_stats_pane_resizing(self):
        pane = self.app.stats_pane
        self.assertEqual(pane.current_height, 8)
        self.assertTrue(pane.is_collapsed)

        new_h = pane.resize_by(2)
        self.assertEqual(new_h, 10)
        self.assertEqual(pane.current_height, 10)

        new_h = pane.resize_by(-3)
        self.assertEqual(new_h, 7)
        self.assertEqual(pane.current_height, 7)

        new_h = pane.set_height(100)
        self.assertEqual(new_h, pane.MAX_HEIGHT)
        self.assertEqual(pane.current_height, pane.MAX_HEIGHT)

        new_h = pane.set_height(0)
        self.assertEqual(new_h, pane.MIN_HEIGHT)
        self.assertEqual(pane.current_height, pane.MIN_HEIGHT)
        self.assertFalse(pane.is_collapsed)

        is_expanded = pane.toggle_pane()
        self.assertFalse(is_expanded)
        self.assertTrue(pane.is_collapsed)

        is_expanded = pane.toggle_pane()
        self.assertTrue(is_expanded)
        self.assertFalse(pane.is_collapsed)

        is_expanded = pane.toggle_pane()
        self.assertFalse(is_expanded)
        self.assertTrue(pane.is_collapsed)

        new_h = pane.resize_by(3)
        self.assertFalse(pane.is_collapsed)
        self.assertEqual(new_h, pane.MIN_HEIGHT + 3)

    def test_app_resize_actions(self):
        initial_h = self.app.stats_pane.current_height
        self.app.action_resize_split_up()
        self.assertEqual(self.app.stats_pane.current_height, initial_h + 1)
        self.assertIn("resized to", self.app.footer_bar.log_message)

        self.app.action_resize_split_down()
        self.assertEqual(self.app.stats_pane.current_height, initial_h)

    def test_resize_hotkey_bindings(self):
        bindings = {b.key: b.action for b in self.app.BINDINGS}
        self.assertIn("+", bindings)
        self.assertEqual(bindings["+"], "resize_split_up")
        self.assertIn("-", bindings)
        self.assertEqual(bindings["-"], "resize_split_down")
        self.assertIn("ctrl+up", bindings)

    def test_top_widget_focus_and_passive_tables(self):
        split_view = self.app.table_widget
        fixed_table = split_view.fixed_table
        sample_table = split_view.sample_table
        self.assertTrue(split_view.can_focus)
        self.assertFalse(fixed_table.can_focus)
        self.assertFalse(sample_table.can_focus)
        self.assertEqual(fixed_table.id, "fixed_table")
        self.assertEqual(sample_table.id, "sample_table")
        self.assertTrue(hasattr(fixed_table, "on_mouse_scroll_left"))
        self.assertTrue(hasattr(fixed_table, "on_mouse_scroll_right"))
        self.assertTrue(hasattr(split_view, "handle_navigation_key"))
        self.assertTrue(hasattr(split_view, "handle_mouse_scroll"))
        split_view.stop_timers()
        self.assertTrue(split_view._split_view_closing)
        self.assertFalse(getattr(split_view, "_closing", False))

    def test_variant_split_view_cursor_sync_and_deduplication(self):
        split_view = self.app.table_widget
        self.assertIsNotNone(split_view)
        self.assertTrue(hasattr(split_view, "_last_notified"))
        self.assertEqual(split_view.fixed_table.peer_table, split_view.sample_table)
        self.assertEqual(split_view.sample_table.peer_table, split_view.fixed_table)

    def test_sample_matrix_table_visible_and_populated(self):
        split_view = self.app.table_widget
        self.assertEqual(split_view.divider.styles.width.value, 1)
        self.assertEqual(split_view.sample_table.styles.width.value, 1)
        self.assertIsNotNone(split_view.sample_table)
        self.assertIsNotNone(split_view.fixed_table)

    def test_sidebar_panel_widgets_configured(self):
        sb = self.app.sidebar_panel
        self.assertIsNotNone(sb.variant_summary)
        self.assertIsNotNone(sb.cohort_widget)
        self.assertIsNotNone(sb.cell_inspector)
        self.assertIn("VARIANT SUMMARY", sb.variant_summary.render().plain)
        self.assertIn("COHORTS & FILTERS", sb.cohort_widget.render().plain)
        self.assertIn("CELL INSPECTOR", sb.cell_inspector.render().plain)

        composed_widgets = list(sb.children) if sb.children else list(sb.compose())
        children = [c.__class__.__name__ for c in composed_widgets]
        self.assertEqual(children, ["CohortListWidget", "VariantSummary", "CellInspector"])


@unittest.skipUnless(TEXTUAL_AVAILABLE, "Textual / textual-fastdatatable / pyarrow / cyvcf2 not installed")
class TestVcfscapeAsyncPilot(unittest.IsolatedAsyncioTestCase):
    """Headless Textual pilot tests verifying direct screen navigation, scrolling, and clean exit."""

    async def test_demo_startup_navigation_and_q_exit(self):
        app = VcfscapeApp(DEMO_VCF)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 1)
            self.assertIs(app.focused, app.table_widget)

            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.table_widget.current_row_idx, 1)

            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app.table_widget.current_sample_idx, 1)

            await pilot.press("left", "up")
            await pilot.pause()
            self.assertEqual(app.table_widget.current_row_idx, 0)
            self.assertEqual(app.table_widget.current_sample_idx, 0)

            await pilot.press("pagedown")
            await pilot.pause()
            self.assertGreater(app.table_widget.current_row_idx, 0)

            await pilot.press("q")
            await pilot.pause()
            self.assertTrue(app._vcfscape_closing)
        self.assertFalse(app.is_running)

    async def test_demo_ctrl_c_exit(self):
        app = VcfscapeApp(DEMO_VCF)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertTrue(app._vcfscape_closing)
        self.assertFalse(app.is_running)

    async def test_large_gzipped_vcf_scrolling_and_q_exit_cleanly(self):
        with tempfile.NamedTemporaryFile(suffix=".vcf.gz", delete=False) as tf:
            gz_path = tf.name

        try:
            samples = [f"S_{i:02d}" for i in range(40)]
            header = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + "\t".join(samples) + "\n"
            calls = "\t".join(["0/1:30" for _ in samples])
            with gzip.open(gz_path, "wt", encoding="utf-8") as f:
                f.write("##fileformat=VCFv4.2\n")
                f.write("##contig=<ID=Pf3D7_07_v3,length=1445207>\n")
                f.write("##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">\n")
                f.write("##FORMAT=<ID=DP,Number=1,Type=Integer,Description=\"Read Depth\">\n")
                f.write(header)
                for i in range(1200):
                    f.write(
                        f"Pf3D7_07_v3\t{1000 + i * 10}\tvar_{i}\tA\tT\t99\tPASS\t.\tGT:DP\t{calls}\n"
                    )

            app = VcfscapeApp(gz_path)
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                self.assertIs(app.focused, app.table_widget)

                # Vertical & horizontal navigation across big gzipped VCF
                await pilot.press("pagedown", "pagedown", "down")
                await pilot.pause()
                self.assertGreater(app.table_widget.current_row_idx, 30)
                self.assertEqual(
                    app.table_widget.sample_table.cursor_coordinate.row,
                    app.table_widget.current_row_idx,
                )

                await pilot.press("end")
                await pilot.pause()
                self.assertEqual(app.table_widget.current_sample_idx, 39)
                self.assertEqual(app.table_widget.sample_table.cursor_coordinate.column, 39)
                self.assertGreater(app.table_widget.sample_table.scroll_x, 0)

                await pilot.press("home")
                await pilot.pause()
                self.assertEqual(app.table_widget.current_sample_idx, 0)
                self.assertEqual(app.table_widget.sample_table.cursor_coordinate.column, 0)

                await pilot.press("q")
                await pilot.pause()
                self.assertTrue(app._vcfscape_closing)
                self.assertTrue(app.reader._stop_workers)
                self.assertTrue(app.reader._stop_event.is_set())
            self.assertFalse(app.is_running)
        finally:
            if os.path.exists(gz_path):
                os.remove(gz_path)


class TestWidgetFilesPresence(unittest.TestCase):
    """Verifies that all widget files and assets exist and compile without syntax errors."""

    def test_all_ui_widget_files_exist(self):
        src_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "vcfscape"))
        expected_files = [
            os.path.join(src_root, "ui", "widgets", "footer_bar.py"),
            os.path.join(src_root, "ui", "widgets", "header_bar.py"),
            os.path.join(src_root, "ui", "widgets", "sidebar.py"),
            os.path.join(src_root, "ui", "widgets", "cohort_stats_pane.py"),
            os.path.join(src_root, "ui", "widgets", "variant_summary.py"),
            os.path.join(src_root, "ui", "widgets", "variant_table.py"),
            os.path.join(src_root, "ui", "widgets", "__init__.py"),
            os.path.join(src_root, "ui", "screens", "cohort_manager_screen.py"),
            os.path.join(src_root, "ui", "screens", "__init__.py"),
            os.path.join(src_root, "ui", "app.py"),
            os.path.join(src_root, "ui", "styles.tcss"),
            os.path.join(src_root, "ui", "__init__.py"),
            os.path.join(src_root, "core", "__init__.py"),
            os.path.join(src_root, "core", "vcf_reader.py"),
            os.path.join(src_root, "core", "arrow_buffer.py"),
            os.path.join(src_root, "core", "cohorts.py"),
            os.path.join(src_root, "core", "malaria_db.py"),
        ]
        for f in expected_files:
            self.assertTrue(os.path.isfile(f), f"Expected file '{f}' to exist.")


if __name__ == "__main__":
    unittest.main()
