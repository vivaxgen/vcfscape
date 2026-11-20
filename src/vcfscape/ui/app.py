"""
Main Textual Application for VCFscape - VCF inspector part of vivaxGEN Project.
"""

import os
import signal
import threading
from typing import Optional, List, Set
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.binding import Binding
from textual.screen import Screen

from vcfscape.core.vcf_reader import VcfReader, VariantRecord
from vcfscape.core.cohorts import CohortManager
from vcfscape.ui.widgets.header_bar import HeaderBar
from vcfscape.ui.widgets.variant_table import VariantSplitView
from vcfscape.ui.widgets.sidebar import SidebarPanel
from vcfscape.ui.widgets.cohort_stats_pane import CohortStatsPane
from vcfscape.ui.widgets.footer_bar import FooterBar
from vcfscape.ui.screens.cohort_manager_screen import CohortManagerScreen
from vcfscape.ui.screens.jump_region_screen import JumpRegionScreen
from vcfscape.ui.screens.vcf_loading_screen import VcfLoadingScreen


class MainScreen(Screen):
    """Explicit root workspace screen always anchored at the base of screen_stack."""

    def __init__(self, app_ref: "VcfscapeApp", **kwargs):
        super().__init__(**kwargs)
        self._app_ref = app_ref

    def compose(self) -> ComposeResult:
        yield self._app_ref.header_bar
        with Horizontal(id="main_container"):
            yield self._app_ref.table_widget
            yield self._app_ref.sidebar_panel
        yield self._app_ref.stats_pane
        yield self._app_ref.footer_bar

    def on_mount(self) -> None:
        self._app_ref._on_main_screen_mounted()

    def on_screen_resume(self) -> None:
        """Restore focus and layout whenever a modal screen dismisses back to MainScreen."""
        try:
            self._app_ref.table_widget.focus()
        except Exception:
            pass
        try:
            self.refresh(layout=True)
        except Exception:
            pass


class VcfscapeApp(App):
    """VCFscape - VCF inspector part of vivaxGEN Project TUI Application."""

    CSS_PATH = "styles.tcss"
    TITLE = "VCFscape - vivaxGEN Project"

    BINDINGS = [
        Binding("1", "set_tag_gt", "GT", show=False),
        Binding("2", "set_tag_dp", "DP", show=False),
        Binding("3", "set_tag_ad", "AD", show=False),
        Binding("4", "set_tag_gq", "GQ", show=False),
        Binding("v", "cycle_view", "View Mode", show=False),
        Binding("g", "jump_region", "Jump Locus", show=False),
        Binding("s", "toggle_split", "Split Pane", show=False),
        Binding("+", "resize_split_up", "Grow Split Pane", show=False),
        Binding("=", "resize_split_up", "Grow Split Pane", show=False),
        Binding("-", "resize_split_down", "Shrink Split Pane", show=False),
        Binding("_", "resize_split_down", "Shrink Split Pane", show=False),
        Binding("ctrl+up", "resize_split_up", "Grow Split Pane", show=False),
        Binding("ctrl+down", "resize_split_down", "Shrink Split Pane", show=False),
        Binding("c", "open_cohort_manager", "Cohort Manager", show=False),
        Binding("C", "toggle_cohort", "Toggle Cohort", show=False),
        Binding("f", "toggle_filter", "Filter", show=False),
        Binding("t", "toggle_theme", "Theme", show=False),
        Binding("?", "show_help", "Help", show=False),
        Binding("q", "quit", "Quit", show=False),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+z", "suspend_process", "Suspend", show=False, priority=True),
    ]

    def __init__(self, vcf_path: str, **kwargs):
        super().__init__(**kwargs)
        self.vcf_path = vcf_path
        self.reader = VcfReader(vcf_path, lazy=True)
        self.cohort_manager = CohortManager(self.reader.samples)
        self.current_filter = "ALL"  # "ALL", "DRUG_RESISTANT", "INDEL", "SNP"
        self.loading_screen: Optional[VcfLoadingScreen] = None
        self._closing = False
        self._main_screen: Optional[MainScreen] = None
        self._callbacks_hooked = False
        self._pending_hydrated_indices: Set[int] = set()
        self._hydration_timer: Optional[object] = None

        # Widgets
        provisional_variants = self.reader.get_total_variants_async()
        self.header_bar = HeaderBar(
            filename=os.path.basename(vcf_path),
            total_variants=provisional_variants,
            total_samples=self.reader.total_samples,
        )
        self.header_bar.backend = self.reader.backend

        # True split with virtual buffer: left fixed columns + right scrollable samples
        try:
            initial_slice = self.reader.get_slice(0, 150, allow_placeholder=True)
        except TypeError:
            initial_slice = self.reader.get_slice(0, 150)

        self.table_widget = VariantSplitView(
            records=initial_slice,
            samples=self.reader.samples,
            reader=self.reader,
        )
        self.sidebar_panel = SidebarPanel(self.cohort_manager)
        self.stats_pane = CohortStatsPane(self.cohort_manager)
        self.footer_bar = FooterBar()

    def get_default_screen(self) -> Screen:
        """Install explicit MainScreen as the permanent base of screen_stack."""
        if self._main_screen is None:
            self._main_screen = MainScreen(self, id="main_screen")
        return self._main_screen

    def _hook_reader_callbacks(self) -> None:
        if self._callbacks_hooked:
            return
        self._callbacks_hooked = True
        if hasattr(self.reader, "add_hydration_callback"):
            self.reader.add_hydration_callback(self._on_samples_hydrated)
        if not self.reader.total_variants_ready:
            self.reader.add_progress_callback(self._on_progress_update)
            self.reader.add_total_variants_callback(self._on_total_variants_ready)

    def _on_main_screen_mounted(self) -> None:
        """Called after MainScreen and all child widgets have mounted."""
        self._hook_reader_callbacks()
        try:
            self.table_widget.focus()
        except Exception:
            pass

        # Reconcile any rows hydrated before UI loop mounted
        if hasattr(self.table_widget, "hydrate_rows") and self.table_widget.records:
            self.table_widget.hydrate_rows(list(range(len(self.table_widget.records))))

        if not self.reader.total_variants_ready:
            def _push_loading_modal() -> None:
                if self._closing or self.reader.total_variants_ready:
                    total = self.reader.get_total_variants_async()
                    if total is not None:
                        self._apply_total_variants(total)
                    return

                def _on_loading_dismiss(_result=None):
                    self.loading_screen = None
                    try:
                        self.table_widget.focus()
                    except Exception:
                        pass
                    if self._main_screen is not None:
                        try:
                            self._main_screen.refresh(layout=True)
                        except Exception:
                            pass

                self.loading_screen = VcfLoadingScreen(os.path.basename(self.vcf_path))
                self.push_screen(self.loading_screen, _on_loading_dismiss)

                # Re-check in case worker completed right as modal was pushed
                if self.reader.total_variants_ready:
                    total = self.reader.get_total_variants_async()
                    if total is not None:
                        self._apply_total_variants(total)

            try:
                self.call_after_refresh(_push_loading_modal)
            except Exception:
                _push_loading_modal()

    def _stop_hydration_timer(self) -> None:
        if self._hydration_timer is not None:
            try:
                self._hydration_timer.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._hydration_timer = None

    def on_unmount(self) -> None:
        self._closing = True
        self._stop_hydration_timer()
        if hasattr(self.reader, "close"):
            self.reader.close()

    def action_quit(self) -> None:
        self._closing = True
        self._stop_hydration_timer()
        if hasattr(self.reader, "close"):
            self.reader.close()
        self.exit()

    def action_suspend_process(self) -> None:
        """Suspend TUI cleanly on Ctrl-Z and restore terminal until resumed with fg."""
        sig_tstp = getattr(signal, "SIGTSTP", None)
        if sig_tstp is None:
            return
        try:
            with self.suspend():
                os.kill(os.getpid(), sig_tstp)
        except Exception:
            try:
                parent_suspend = getattr(super(), "action_suspend_process", None)
                if callable(parent_suspend):
                    parent_suspend()
            except Exception:
                pass

    def _invoke_on_ui(self, fn, *args) -> None:
        if self._closing or not getattr(self, "is_running", False):
            return
        try:
            if threading.get_ident() == getattr(self, "_thread_id", None):
                fn(*args)
            else:
                self.call_from_thread(fn, *args)
        except Exception:
            pass

    def _on_samples_hydrated(self, indices: List[int]) -> None:
        self._invoke_on_ui(self._apply_samples_hydrated, indices)

    def _apply_samples_hydrated(self, indices: List[int]) -> None:
        if self._closing or not indices:
            return
        self._pending_hydrated_indices.update(indices)
        if self._hydration_timer is None:
            try:
                self._hydration_timer = self.set_timer(0.05, self._flush_hydrated_rows)
            except Exception:
                self._flush_hydrated_rows()

    def _flush_hydrated_rows(self) -> None:
        self._hydration_timer = None
        if self._closing or not self._pending_hydrated_indices:
            return
        batch = sorted(self._pending_hydrated_indices)
        self._pending_hydrated_indices.clear()
        if hasattr(self, "table_widget") and hasattr(self.table_widget, "hydrate_rows"):
            self.table_widget.hydrate_rows(batch)

    def _on_progress_update(self, count: int) -> None:
        self._invoke_on_ui(self._apply_progress_update, count)

    def _apply_progress_update(self, count: int) -> None:
        if self._closing:
            return
        if self.loading_screen is not None:
            self.loading_screen.update_progress(count)

    def _on_total_variants_ready(self, total: int):
        self._invoke_on_ui(self._apply_total_variants, total)

    def _apply_total_variants(self, total: int):
        if self._closing:
            return
        self.header_bar.total_variants = total
        self.table_widget.update_total_variants(total)
        if self.loading_screen is not None:
            modal = self.loading_screen
            self.loading_screen = None
            modal.mark_complete(total)
        try:
            self.table_widget.focus()
        except Exception:
            pass
        self.footer_bar.set_log(f"VCF file indexing complete: {total:,} total variants.")

    def on_variant_split_view_variant_selected(self, message: VariantSplitView.VariantSelected):
        """Update sidebar and split-pane when user moves cursor."""
        rec = message.record
        sample_id = message.sample_id
        
        self.sidebar_panel.update_selection(rec, sample_id)
        if not self.stats_pane.is_collapsed:
            self.stats_pane.update_stats(rec)
        else:
            self.stats_pane.current_record = rec

        sample_info = f" | Sample: {sample_id}" if sample_id else ""
        drug_note = f" [{rec.drug_annotation.drug} Resistance]" if rec.drug_annotation else ""

        row_num = getattr(message, "row_index", 0) + 1
        total = getattr(self.header_bar, "total_variants", None)
        if total is None and hasattr(self, "table_widget") and getattr(self.table_widget, "total_records_count", None):
            total = self.table_widget.total_records_count

        if isinstance(total, int) and total > 0:
            pct = min(100.0, (row_num / total) * 100.0)
            pos_label = f"Variant #{row_num:,} / {total:,} ({pct:.1f}%)"
        else:
            pos_label = f"Variant #{row_num:,}"

        self.footer_bar.set_log(f"{pos_label} │ {rec.chrom}:{rec.pos:,} ({rec.gene}){drug_note}{sample_info}")

    def action_set_tag_gt(self):
        self.table_widget.set_format_tag("GT")
        self.header_bar.format_tag = "GT"
        self.footer_bar.set_log("Switched sample matrix to Genotype (GT) view.")

    def action_set_tag_dp(self):
        self.table_widget.set_format_tag("DP")
        self.header_bar.format_tag = "DP"
        self.footer_bar.set_log("Switched sample matrix to Read Depth (DP) view.")

    def action_set_tag_ad(self):
        self.table_widget.set_format_tag("AD")
        self.header_bar.format_tag = "AD"
        self.footer_bar.set_log("Switched sample matrix to Allelic Depths (AD: REF, ALT1...) view.")

    def action_set_tag_gq(self):
        self.table_widget.set_format_tag("GQ")
        self.header_bar.format_tag = "GQ"
        self.footer_bar.set_log("Switched sample matrix to Genotype Quality (GQ) view.")

    def action_cycle_view(self):
        new_mode = self.table_widget.cycle_view_mode()
        self.header_bar.view_mode = new_mode
        self.footer_bar.set_log(f"Switched fixed variant columns to [{new_mode}] view.")

    def action_toggle_split(self):
        expanded = self.stats_pane.toggle_pane()
        state_str = "Expanded" if expanded else "Collapsed"
        self.footer_bar.set_log(f"Cohort Statistics split-pane {state_str} ({self.stats_pane.current_height} rows).")

    def action_resize_split_up(self):
        new_h = self.stats_pane.resize_by(1)
        self.footer_bar.set_log(f"Cohort Statistics split-pane resized to {new_h} rows (+).")

    def action_resize_split_down(self):
        new_h = self.stats_pane.resize_by(-1)
        self.footer_bar.set_log(f"Cohort Statistics split-pane resized to {new_h} rows (-).")

    def action_open_cohort_manager(self):
        def on_dismiss(saved: bool | None):
            if saved:
                self.sidebar_panel.cohort_widget.refresh()
                if self.table_widget.records:
                    self.stats_pane.update_stats(self.table_widget.records[0])
                self.footer_bar.set_log("Cohort updates saved and applied successfully.")
            try:
                self.table_widget.focus()
            except Exception:
                pass

        self.push_screen(CohortManagerScreen(self.cohort_manager), on_dismiss)

    def action_toggle_cohort(self):
        cohort_keys = [k for k in self.cohort_manager.cohorts.keys() if k != "All Samples"]
        if cohort_keys:
            target = cohort_keys[0]
            for k in cohort_keys:
                if self.cohort_manager.cohorts[k].active:
                    target = k
                    break
            new_state = self.cohort_manager.toggle_cohort(target)
            state_label = "ACTIVE" if new_state else "INACTIVE"
            self.footer_bar.set_log(f"Cohort [{target}] toggled to {state_label}.")
            self.sidebar_panel.cohort_widget.refresh()
            if self.table_widget.records:
                self.stats_pane.update_stats(self.table_widget.records[0])
        else:
            self.footer_bar.set_log("No custom cohorts defined. Press 'c' to open Cohort Manager.")

    def action_toggle_filter(self):
        filters = ["ALL", "DRUG_RESISTANT", "INDEL", "SNP"]
        curr_idx = filters.index(self.current_filter) if self.current_filter in filters else 0
        self.current_filter = filters[(curr_idx + 1) % len(filters)]

        if self.current_filter == "ALL":
            try:
                initial_records = self.reader.get_slice(0, 150, allow_placeholder=True)
            except TypeError:
                initial_records = self.reader.get_slice(0, 150)
            self.table_widget.set_records(initial_records, is_main_stream=True)
            total = self.reader.get_total_variants_async() if hasattr(self.reader, "get_total_variants_async") else None
            if total is None and getattr(self.reader, "total_variants_ready", False):
                total = self.reader.total_variants
            self.header_bar.total_variants = total
            self.sidebar_panel.cohort_widget.set_filter(self.current_filter)
            total_str = f"{total:,}" if isinstance(total, int) else "streaming"
            self.footer_bar.set_log(f"Filter set to [ALL]. Displaying {total_str} variants.")
        else:
            filtered_records = self.reader.filter_records(variant_type=self.current_filter)
            self.table_widget.set_records(filtered_records, is_main_stream=False)
            self.header_bar.total_variants = len(filtered_records)
            self.sidebar_panel.cohort_widget.set_filter(self.current_filter)
            self.footer_bar.set_log(f"Filter set to [{self.current_filter}]. Displaying {len(filtered_records)} variants.")

    def action_toggle_theme(self):
        """Toggle between Dark and Light mode."""
        if "theme-light" in self.classes:
            self.remove_class("theme-light")
            try:
                if self.screen:
                    self.screen.remove_class("theme-light")
            except Exception:
                pass
            self.dark = True
            self.footer_bar.set_log("Switched theme to [DARK] mode.")
        else:
            self.add_class("theme-light")
            try:
                if self.screen:
                    self.screen.add_class("theme-light")
            except Exception:
                pass
            self.dark = False
            self.footer_bar.set_log("Switched theme to [LIGHT] mode.")

    def action_jump_region(self):
        """Open genomic locus jumper modal dialog."""
        def on_dismiss(target):
            if target:
                chrom, pos = target
                ok = self.table_widget.jump_to_region(chrom, pos)
                if ok:
                    self.footer_bar.set_log(f"Jumped to genomic locus {chrom}:{pos:,}")
                else:
                    self.footer_bar.set_log(f"No variants found near {chrom}:{pos:,}")
            try:
                self.table_widget.focus()
            except Exception:
                pass

        self.push_screen(JumpRegionScreen(), on_dismiss)

    def action_show_help(self):
        self.footer_bar.set_log(
            "Hotkeys: 1=GT, 2=DP, 3=AD, 4=GQ, v=View, g=Jump Locus, s=Split, +/-=Resize, c=Cohorts, f=Filter, t=Theme, q=Quit"
        )


# Backward compatibility alias
MalariaVcfApp = VcfscapeApp
