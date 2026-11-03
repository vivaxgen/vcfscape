"""
Central Variant Split Table for Malaria VCF TUI.
Provides a true vertical split between:
1. Fixed variant information columns (toggleable between Raw, Normal, Compact, Essential)
2. Vertical divider
3. Horizontally scrollable sample matrix columns fitted to active FORMAT tag
With guaranteed bidirectional vertical scroll and cursor synchronization.
"""

from typing import List, Optional, Tuple
from textual import events
from textual.widget import Widget
from textual.widgets import DataTable, Static
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from vcfscape.core.vcf_reader import VariantRecord


class FixedVariantTable(DataTable):
    """Left anchored table displaying variant metadata columns."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.peer_table: Optional[DataTable] = None
        self._syncing_scroll: bool = False

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if self.peer_table is not None and not self._syncing_scroll:
            if abs(self.peer_table.scroll_y - new_value) > 0.5:
                self.peer_table._syncing_scroll = True
                try:
                    self.peer_table.scroll_to(y=new_value, animate=False, force=True)
                finally:
                    self.peer_table._syncing_scroll = False

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.scroll_down(animate=False)
        if self.peer_table is not None:
            self.peer_table.scroll_to(y=self.scroll_y, animate=False, force=True)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.scroll_up(animate=False)
        if self.peer_table is not None:
            self.peer_table.scroll_to(y=self.scroll_y, animate=False, force=True)

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.stop()
        self.scroll_left(animate=False)

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.stop()
        self.scroll_right(animate=False)

    def action_cursor_left(self) -> None:
        if self.scroll_x > 0:
            self.scroll_left(animate=False)
        else:
            super().action_cursor_left()

    def action_cursor_right(self) -> None:
        if self.scroll_x < self.max_scroll_x:
            self.scroll_right(animate=False)
        else:
            super().action_cursor_right()


class SampleMatrixTable(DataTable):
    """Right horizontally scrollable table displaying sample genotype cells."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.peer_table: Optional[DataTable] = None
        self._syncing_scroll: bool = False

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if self.peer_table is not None and not self._syncing_scroll:
            if abs(self.peer_table.scroll_y - new_value) > 0.5:
                self.peer_table._syncing_scroll = True
                try:
                    self.peer_table.scroll_to(y=new_value, animate=False, force=True)
                finally:
                    self.peer_table._syncing_scroll = False

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.scroll_down(animate=False)
        if self.peer_table is not None:
            self.peer_table.scroll_to(y=self.scroll_y, animate=False, force=True)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.scroll_up(animate=False)
        if self.peer_table is not None:
            self.peer_table.scroll_to(y=self.scroll_y, animate=False, force=True)


class VariantSplitView(Widget):
    """
    Split table container:
    - Left: FixedVariantTable for variant info columns (frozen horizontally)
    - Center: Vertical divider line
    - Right: SampleMatrixTable for sample genotype matrix (horizontally scrollable)
    - Both tables stay in lockstep vertically during all scrolling and keyboard events.
    """

    class VariantSelected(Message):
        """Dispatched when cursor moves to a new variant row or sample cell."""
        def __init__(self, record: VariantRecord, sample_id: Optional[str] = None):
            super().__init__()
            self.record = record
            self.sample_id = sample_id

    view_mode = reactive("normal")
    format_tag = reactive("GT")

    FIXED_WIDTHS = {
        "essential": 18,
        "compact": 28,
        "normal": 48,
        "raw": 70,
    }

    def __init__(
        self,
        records: List[VariantRecord],
        samples: List[str],
        **kwargs
    ):
        super().__init__(**kwargs)
        self.records = records
        self.samples = samples
        self._syncing_cursor = False
        self.current_row_idx = 0
        self.current_sample_idx = 0
        self._last_notified: Optional[Tuple[int, int]] = None

        # 1. Left Fixed Table
        self.fixed_table = FixedVariantTable(id="fixed_table", cursor_type="row", zebra_stripes=True)
        self.fixed_table.show_cursor = True

        # 2. Divider
        self.divider = Static("│", id="table_divider")

        # 3. Right Horizontally Scrollable Sample Table
        self.sample_table = SampleMatrixTable(id="sample_table", cursor_type="cell", zebra_stripes=True)
        self.sample_table.show_cursor = True

        # Link peers directly
        self.fixed_table.peer_table = self.sample_table
        self.sample_table.peer_table = self.fixed_table

    def compose(self):
        with Horizontal(id="split_container"):
            yield self.fixed_table
            yield self.divider
            yield self.sample_table

    def on_mount(self):
        self.rebuild_tables()

    def set_records(self, records: List[VariantRecord]):
        self.records = records
        self.current_row_idx = 0
        self.rebuild_tables()

    def set_view_mode(self, mode: str):
        self.view_mode = mode.lower()
        self.rebuild_tables()

    def set_format_tag(self, tag: str):
        self.format_tag = tag.upper()
        self.rebuild_sample_table()

    def cycle_view_mode(self) -> str:
        modes = ["normal", "compact", "essential", "raw"]
        curr_idx = modes.index(self.view_mode) if self.view_mode in modes else 0
        new_mode = modes[(curr_idx + 1) % len(modes)]
        self.set_view_mode(new_mode)
        return new_mode.capitalize()

    def rebuild_tables(self):
        """Reconstructs both fixed and sample tables."""
        self._last_notified = None
        self.rebuild_fixed_table()
        self.rebuild_sample_table()
        self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def rebuild_fixed_table(self):
        """Constructs left fixed variant columns and sets width."""
        self.fixed_table.clear(columns=True)

        target_width = self.FIXED_WIDTHS.get(self.view_mode, 48)
        self.fixed_table.styles.width = target_width

        if self.view_mode == "raw":
            cols = ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
        elif self.view_mode == "compact":
            cols = ["CHROM", "POS", "REF", "ALT"]
        elif self.view_mode == "essential":
            cols = ["CHROM", "POS"]
        else:  # "normal"
            cols = ["CHROM", "POS", "REF", "ALT", "QUAL", "FILTER", "GENE"]

        for col in cols:
            self.fixed_table.add_column(Text(col, style="bold cyan"), key=f"f_{col}")

        for r_idx, r in enumerate(self.records):
            chrom_short = r.chrom.replace("Pf3D7_", "Pf").replace("_v3", "")
            if self.view_mode == "raw":
                qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
                info_short = f"GENE={r.gene};MUT={r.mutation}"
                row_cells = [
                    chrom_short, str(r.pos), r.var_id, r.ref, r.alt_str,
                    qual_str, r.filter, info_short, ":".join(r.format_keys[:3])
                ]
            elif self.view_mode == "compact":
                row_cells = [chrom_short, str(r.pos), r.ref, r.alt_str]
            elif self.view_mode == "essential":
                row_cells = [chrom_short, str(r.pos)]
            else:  # "normal"
                qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
                filter_styled = Text(r.filter, style="green" if r.filter == "PASS" else "red")
                gene_styled = Text(r.gene, style="bold yellow" if r.drug_annotation else "white")
                row_cells = [chrom_short, str(r.pos), r.ref, r.alt_str, qual_str, filter_styled, gene_styled]

            self.fixed_table.add_row(*row_cells, key=f"frow_{r_idx}")

    def rebuild_sample_table(self):
        """Constructs right horizontally scrollable sample columns."""
        self.sample_table.clear(columns=True)

        for s in self.samples:
            self.sample_table.add_column(Text(s, style="bold bright_white"), key=f"s_{s}")

        for r_idx, r in enumerate(self.records):
            row_cells = []
            for s in self.samples:
                s_dict = r.sample_data.get(s, {})
                cell_val = str(s_dict.get(self.format_tag, "."))
                row_cells.append(self._style_sample_cell(cell_val, self.format_tag))
            self.sample_table.add_row(*row_cells, key=f"srow_{r_idx}")

    def _style_sample_cell(self, val: str, tag: str) -> Text:
        """Styling for sample genotype/depth cells."""
        if tag == "GT":
            if val in ("0/0", "0|0", "0"):
                return Text(val, style="dim white")
            elif val in ("./.", "."):
                return Text(val, style="dim bright_black")
            elif "/" in val:
                parts = val.split("/")
                if len(set(parts)) > 1:
                    # Heterozygous / Polyclonal infection (hallmark of malaria surveillance)
                    return Text(val, style="bold bright_magenta")
                else:
                    return Text(val, style="bold bright_cyan")
            return Text(val, style="bold bright_cyan")
        elif tag == "DP":
            try:
                dp = int(val)
                if dp < 15:
                    return Text(val, style="red")
                elif dp < 40:
                    return Text(val, style="yellow")
                return Text(val, style="green")
            except ValueError:
                return Text(val, style="dim")
        elif tag == "AD":
            return Text(val, style="bright_yellow")
        elif tag == "GQ":
            try:
                gq = int(val)
                return Text(val, style="green" if gq >= 80 else "yellow")
            except ValueError:
                return Text(val, style="dim")
        return Text(val, style="white")

    # Synchronize Cursor Movement (Arrow Up/Down, Cell Selection)
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        if event.data_table.id == "fixed_table":
            target_row = event.cursor_row
            # Only drive peer if sample_table is not already at target_row and fixed_table is active
            if self.sample_table.cursor_row != target_row:
                if self.fixed_table.has_focus or not self.sample_table.has_focus:
                    self._syncing_cursor = True
                    try:
                        try:
                            self.sample_table.move_cursor(row=target_row, animate=False)
                        except TypeError:
                            self.sample_table.move_cursor(row=target_row)
                    finally:
                        self._syncing_cursor = False

            if self.current_row_idx != target_row:
                self.current_row_idx = target_row
                self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted):
        if event.data_table.id == "sample_table":
            target_row = event.coordinate.row
            target_col = event.coordinate.column
            # Only drive peer if fixed_table is not already at target_row and sample_table is active
            if self.fixed_table.cursor_row != target_row:
                if self.sample_table.has_focus or not self.fixed_table.has_focus:
                    self._syncing_cursor = True
                    try:
                        try:
                            self.fixed_table.move_cursor(row=target_row, animate=False)
                        except TypeError:
                            self.fixed_table.move_cursor(row=target_row)
                    finally:
                        self._syncing_cursor = False

            if self.current_row_idx != target_row or self.current_sample_idx != target_col:
                self.current_row_idx = target_row
                self.current_sample_idx = target_col
                self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def _notify_selection(self, row_idx: int, sample_col_idx: int):
        if 0 <= row_idx < len(self.records):
            coord = (row_idx, sample_col_idx)
            if hasattr(self, "_last_notified") and self._last_notified == coord:
                return
            self._last_notified = coord
            rec = self.records[row_idx]
            sample_id = None
            if 0 <= sample_col_idx < len(self.samples):
                sample_id = self.samples[sample_col_idx]
            self.post_message(self.VariantSelected(rec, sample_id))
