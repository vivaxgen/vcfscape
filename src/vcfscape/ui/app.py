"""
Main Textual Application for VCFscape - VCF inspector part of vivaxGEN Project.
"""

import asyncio
import os
import signal
import threading
from typing import Optional, List, Set
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.binding import Binding

from vcfscape.core.vcf_reader import VcfReader
from vcfscape.core.cohorts import CohortManager
from vcfscape.ui.widgets.header_bar import HeaderBar
from vcfscape.ui.widgets.variant_table import VariantSplitView
from vcfscape.ui.widgets.sidebar import SidebarPanel
from vcfscape.ui.widgets.cohort_stats_pane import CohortStatsPane
from vcfscape.ui.widgets.footer_bar import FooterBar
from vcfscape.ui.screens.cohort_manager_screen import CohortManagerScreen
from vcfscape.ui.screens.jump_region_screen import JumpRegionScreen


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
        self._vcfscape_closing = False
        self._callbacks_hooked = False
        self._pending_hydrated_indices: Set[int] = set()
        self._hydration_timer: Optional[object] = None
        self._ui_loop: Optional[asyncio.AbstractEventLoop] = None

        provisional_variants = self.reader.get_total_variants_async()
        self.header_bar = HeaderBar(
            filename=os.path.basename(vcf_path),
            total_variants=provisional_variants,
            total_samples=self.reader.total_samples,
        )
        self.header_bar.backend = self.reader.backend

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

    def compose(self) -> ComposeResult:
        yield self.header_bar
        with Horizontal(id="main_container"):
            yield self.table_widget
            yield self.sidebar_panel
        yield self.stats_pane
        yield self.footer_bar

    def _hook_reader_callbacks(self) -> None:
        if self._callbacks_hooked:
            return
        self._callbacks_hooked = True
        if hasattr(self.reader, "add_hydration_callback"):
            self.reader.add_hydration_callback(self._on_samples_hydrated)
        if not self.reader.total_variants_ready:
            self.reader.add_progress_callback(self._on_progress_update)
            self.reader.add_total_variants_callback(self._on_total_variants_ready)

    def on_mount(self) -> None:
        try:
            self._ui_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._ui_loop = None

        self._hook_reader_callbacks()
        try:
            self.table_widget.focus()
        except Exception:
            pass

        if hasattr(self.table_widget, "hydrate_rows") and self.table_widget.records:
            buf = getattr(self.table_widget, "sample_buffer", None)
            if buf is not None and hasattr(buf, "is_row_hydrated"):
                pending = [
                    i for i in range(len(self.table_widget.records))
                    if not buf.is_row_hydrated(i)
                ]
            else:
                pending = list(range(len(self.table_widget.records)))
            if pending:
                self.table_widget.hydrate_rows(pending)

        if self.reader.total_variants_ready:
            total = self.reader.get_total_variants_async()
            if total is not None:
                self.header_bar.total_variants = total
                self.table_widget.update_total_variants(total)
        else:
            self.footer_bar.set_log("Indexing variants in background...")

    def _stop_hydration_timer(self) -> None:
        if self._hydration_timer is not None:
            try:
                self._hydration_timer.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._hydration_timer = None
        self._pending_hydrated_indices.clear()

    def _begin_shutdown(self) -> None:
        self._vcfscape_closing = True
        self._stop_hydration_timer()
        if hasattr(self, "table_widget") and hasattr(self.table_widget, "stop_timers"):
            try:
                self.table_widget.stop_timers()
            except Exception:
                pass
        if hasattr(self.reader, "close"):
            try:
                self.reader.close(wait=False)
            except TypeError:
                try:
                    self.reader.close()
                except Exception:
                    pass
            except Exception:
                pass

    def on_unmount(self) -> None:
        self._begin_shutdown()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+c", "q"):
            event.stop()
            event.prevent_default()
            self._begin_shutdown()
            self.exit()

    async def action_quit(self) -> None:
        self._begin_shutdown()
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
        if (
            self._vcfscape_closing
            or getattr(self.reader, "_stop_workers", False)
            or not getattr(self, "is_running", False)
        ):
            return

        def _guarded_call() -> None:
            if (
                self._vcfscape_closing
                or getattr(self.reader, "_stop_workers", False)
                or not getattr(self, "is_running", False)
            ):
                return
            try:
                fn(*args)
            except Exception:
                pass

        try:
            if threading.get_ident() == getattr(self, "_thread_id", None):
                _guarded_call()
            else:
                loop = self._ui_loop or getattr(self, "_loop", None)
                if loop is not None and loop.is_running() and not loop.is_closed():
                    loop.call_soon_threadsafe(_guarded_call)
        except Exception:
            pass

    def _on_samples_hydrated(self, indices: List[int]) -> None:
        self._invoke_on_ui(self._apply_samples_hydrated, indices)

    def _apply_samples_hydrated(self, indices: List[int]) -> None:
        if self._vcfscape_closing or not indices:
            return
        self._pending_hydrated_indices.update(indices)
        if self._hydration_timer is None:
            try:
                self._hydration_timer = self.set_timer(0.05, self._flush_hydrated_rows)
            except Exception:
                self._flush_hydrated_rows()

    def _flush_hydrated_rows(self) -> None:
        self._hydration_timer = None
        if self._vcfscape_closing or not self._pending_hydrated_indices:
            return
        batch = sorted(self._pending_hydrated_indices)
        self._pending_hydrated_indices.clear()
        if hasattr(self, "table_widget") and hasattr(self.table_widget, "hydrate_rows"):
            self.table_widget.hydrate_rows(batch)

    def _on_progress_update(self, count: int) -> None:
        self._invoke_on_ui(self._apply_progress_update, count)

    def _apply_progress_update(self, count: int) -> None:
        if self._vcfscape_closing:
            return
        self.header_bar.counting_progress = count
        if hasattr(self.table_widget, "update_counting_progress"):
            self.table_widget.update_counting_progress(count)
        self.footer_bar.set_log(f"Indexing variants in background: {count:,} sites...")

    def _on_total_variants_ready(self, total: int) -> None:
        self._invoke_on_ui(self._apply_total_variants, total)

    def _apply_total_variants(self, total: int) -> None:
        if self._vcfscape_closing:
            return
        self.header_bar.counting_progress = total
        self.header_bar.total_variants = total
        self.table_widget.update_total_variants(total)
        self.footer_bar.set_log(f"VCF file indexing complete: {total:,} total variants.")

    def on_variant_split_view_variant_selected(self, message: VariantSplitView.VariantSelected):
        """Update sidebar and split-pane when user moves cursor."""
        if self._vcfscape_closing:
            return
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
                active_rec = (
                    self.table_widget.get_record_at_display_row(self.table_widget.current_row_idx)
                    if hasattr(self.table_widget, "get_record_at_display_row")
                    else (self.table_widget.records[0] if self.table_widget.records else None)
                )
                if active_rec is not None:
                    self.stats_pane.update_stats(active_rec)
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
            active_rec = (
                self.table_widget.get_record_at_display_row(self.table_widget.current_row_idx)
                if hasattr(self.table_widget, "get_record_at_display_row")
                else (self.table_widget.records[0] if self.table_widget.records else None)
            )
            if active_rec is not None:
                self.stats_pane.update_stats(active_rec)
        else:
            self.footer_bar.set_log("No custom cohorts defined. Press 'c' to open Cohort Manager.")

    def action_toggle_filter(self):
        filters = ["ALL", "DRUG_RESISTANT", "INDEL", "SNP"]
        curr_idx = filters.index(self.current_filter) if self.current_filter in filters else 0
        self.current_filter = filters[(curr_idx + 1) % len(filters)]

        if self.current_filter == "ALL":
            if hasattr(self.table_widget, "apply_filter"):
                self.table_widget.apply_filter(variant_type="ALL")
            else:
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
            if hasattr(self.table_widget, "apply_filter"):
                matched_count = self.table_widget.apply_filter(variant_type=self.current_filter)
            else:
                filtered_records = self.reader.filter_records(variant_type=self.current_filter)
                self.table_widget.set_records(filtered_records, is_main_stream=False)
                matched_count = len(filtered_records)
            self.header_bar.total_variants = matched_count
            self.sidebar_panel.cohort_widget.set_filter(self.current_filter)
            self.footer_bar.set_log(f"Filter set to [{self.current_filter}]. Displaying {matched_count:,} variants.")

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
