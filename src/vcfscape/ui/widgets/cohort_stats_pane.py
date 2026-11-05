"""
Cohort Statistics Split-Pane Widget for Malaria VCF TUI.
Resizable/collapsible panel positioned between central table and footer,
displaying multi-allelic allele frequencies, mean read depths, and missingness
stratified across all active sample cohorts. Supports mouse drag resizing,
keyboard resize (+/-), and click/hotkey collapse/expand (s).
"""

from typing import Dict, Optional
from textual import events
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text
from rich.table import Table
from vcfscape.core.cohorts import CohortStats, CohortManager
from vcfscape.core.vcf_reader import VariantRecord


class CohortStatsHandle(Static):
    """Interactive drag handle bar to resize the CohortStatsPane with mouse or click."""

    def __init__(self, parent_pane: "CohortStatsPane", **kwargs):
        super().__init__(**kwargs)
        self.parent_pane = parent_pane
        self._dragging = False
        self._drag_start_y = 0
        self._start_height = 8

    def _get_event_y(self, event) -> int:
        if hasattr(event, "screen_y"):
            return event.screen_y
        if hasattr(event, "y"):
            return event.y
        return 0

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:
            self._dragging = True
            self._drag_start_y = self._get_event_y(event)
            self._start_height = self.parent_pane.current_height
            if hasattr(self, "capture_mouse"):
                self.capture_mouse()
            event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging:
            curr_y = self._get_event_y(event)
            # Dragging up increases height of bottom pane; dragging down decreases it
            delta = self._drag_start_y - curr_y
            new_height = self._start_height + delta
            self.parent_pane.set_height(new_height)
            event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            if hasattr(self, "release_mouse"):
                self.release_mouse()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        # If clicked while collapsed, expand immediately
        if self.parent_pane.is_collapsed:
            self.parent_pane.toggle_pane()
            event.stop()

    def render(self) -> Text:
        if self.parent_pane.is_collapsed:
            return Text(
                " [s] COHORT STATISTICS (SPLIT-PANE: COLLAPSED - Click or press 's' to expand) ",
                style="bold bright_black on #1e293b",
            )

        t = Text()
        t.append("─── ≡ ", style="bold yellow")
        t.append("COHORT STATISTICS (SPLIT-PANE) ", style="bold bright_white")
        t.append("[Drag ▲▼ or +/- to resize | 's' to collapse] ", style="bold cyan")
        t.append(f"({self.parent_pane.current_height} rows) ", style="dim bright_black")
        t.append("───", style="bold yellow")
        return t


class CohortStatsContent(Static):
    """Scrollable table content displaying cohort-stratified metrics."""

    def __init__(self, parent_pane: "CohortStatsPane", **kwargs):
        super().__init__(**kwargs)
        self.parent_pane = parent_pane

    def render(self):
        return self.parent_pane._render_table()


class CohortStatsPane(Widget):
    """Resizable split-pane showing real-time cohort-stratified population metrics."""

    MIN_HEIGHT = 3
    MAX_HEIGHT = 22
    DEFAULT_HEIGHT = 8

    is_collapsed = reactive(True)
    current_height = reactive(8)

    def __init__(self, cohort_manager: CohortManager, **kwargs):
        super().__init__(**kwargs)
        self.cohort_manager = cohort_manager
        self.current_record: Optional[VariantRecord] = None
        self.stats: Dict[str, CohortStats] = {}
        self.is_collapsed = True
        self.current_height = self.DEFAULT_HEIGHT

        self.handle = CohortStatsHandle(self, id="cohort_stats_handle")
        self.content_widget = CohortStatsContent(self, id="cohort_stats_content")

    def compose(self) -> ComposeResult:
        yield self.handle
        yield self.content_widget

    def on_mount(self) -> None:
        # Initial start: pane is collapsed, content hidden, no stats computed
        self.styles.height = 1
        self.content_widget.display = False
        self._refresh_display()

    def get_optimal_height(self) -> int:
        """Calculate the exact height needed so all rows and metrics are visible without scrolling."""
        if not self.current_record:
            return self.DEFAULT_HEIGHT

        num_alts = max(1, len(self.current_record.alt)) if self.current_record.alt else 1
        # Table rows: 1 header + 4 metrics (Called, DP, Het, REF) + ALTs
        # Total height: 1 border-top + 1 handle + table_rows + 1 buffer
        needed = 1 + 1 + (1 + 4 + num_alts) + 1
        return max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, needed))

    def set_height(self, new_height: int) -> int:
        """Sets the split-pane height clamped between MIN_HEIGHT and MAX_HEIGHT."""
        clamped = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, int(new_height)))
        self.current_height = clamped
        if self.is_collapsed:
            self.is_collapsed = False
            self.content_widget.display = True
            if self.current_record:
                self.update_stats(self.current_record)
        self.styles.height = clamped
        self._refresh_display()
        return clamped

    def resize_by(self, delta: int) -> int:
        """Adjusts the split-pane height by delta rows."""
        return self.set_height(self.current_height + delta)

    def toggle_pane(self) -> bool:
        """Toggles between expanded and collapsed state.
        When expanded via [s], recalculates optimal height and computes stats.
        """
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.styles.height = 1
            self.content_widget.display = False
        else:
            self.content_widget.display = True
            if self.current_record:
                # Calculate stats only when becoming visible
                self.update_stats(self.current_record)
                optimal_h = self.get_optimal_height()
                self.current_height = optimal_h
                self.styles.height = optimal_h
            else:
                self.styles.height = self.current_height
        self._refresh_display()
        return not self.is_collapsed

    def update_stats(self, record: VariantRecord):
        """Update cohort statistics content when user selects/scrolls variants.
        Does NOT alter height (user manually uses [s] to re-height).
        """
        self.current_record = record
        if not self.is_collapsed:
            self.stats = self.cohort_manager.calculate_variant_stats(
                {
                    "genotypes": record.genotypes,
                    "depths": record.depths,
                    "ad": record.ad,
                },
                record.num_alleles,
            )
            self._refresh_display()

    def _refresh_display(self):
        if hasattr(self, "handle"):
            self.handle.refresh()
        if hasattr(self, "content_widget"):
            self.content_widget.refresh()
        self.refresh()

    def _render_table(self):
        if not self.current_record or not self.stats:
            return Text(" No variant selected for cohort statistics.", style="dim italic")

        r = self.current_record
        table = Table(
            show_header=True,
            header_style="bold yellow",
            box=None,
            padding=(0, 1),
            expand=True,
        )

        table.add_column("METRIC / ALLELE", style="bold cyan", no_wrap=True)
        for c_name in self.stats.keys():
            table.add_column(c_name.upper(), style="bold bright_white", no_wrap=True)

        # 1. Called & Missingness
        called_cells = ["Called / Missing"]
        for c_name, s in self.stats.items():
            miss_pct = s.missingness_rate * 100
            called_cells.append(f"{s.called_samples}/{s.total_samples} ({miss_pct:.1f}% miss)")
        table.add_row(*called_cells)

        # 2. Read Depth (Mean & Range)
        dp_cells = ["Mean Read Depth (DP)"]
        for c_name, s in self.stats.items():
            dp_cells.append(f"{s.mean_depth:.1f}x [{s.min_depth} - {s.max_depth}x]")
        table.add_row(*dp_cells)

        # 3. Polygenomic / Heterozygosity Rate (MOI proxy)
        poly_cells = ["Polyclonal / Het Rate"]
        for c_name, s in self.stats.items():
            poly_pct = s.polygenomic_rate * 100
            poly_cells.append(f"{s.polygenomic_samples} isolates ({poly_pct:.1f}%)")
        table.add_row(*poly_cells)

        # 4. REF Allele 0 Frequency
        ref_cells = [f"REF [0: {r.ref}]"]
        for c_name, s in self.stats.items():
            af = s.allele_frequencies.get(0, 0.0)
            ac = s.allele_counts.get(0, 0)
            ref_cells.append(f"AF={af:.3f} (n={ac})")
        table.add_row(*ref_cells)

        # 5. ALT Allele Frequencies
        for alt_idx, alt_allele in enumerate(r.alt, start=1):
            alt_cells = [f"ALT [{alt_idx}: {alt_allele}]"]
            for c_name, s in self.stats.items():
                af = s.allele_frequencies.get(alt_idx, 0.0)
                ac = s.allele_counts.get(alt_idx, 0)
                alt_cells.append(f"AF={af:.3f} (n={ac})")
            table.add_row(*alt_cells)

        return table
