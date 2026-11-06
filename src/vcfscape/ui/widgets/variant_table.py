"""
Central Variant Split Table for Malaria VCF TUI.
Provides a true vertical split between:
1. Fixed variant information columns (toggleable between Raw, Normal, Compact, Essential)
2. Vertical divider
3. Horizontally scrollable sample matrix columns fitted to active FORMAT tag
With guaranteed bidirectional vertical scroll and cursor synchronization.
"""

from typing import Any, Dict, List, Optional, Tuple
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
        self.split_view: Optional[Any] = None
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
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y >= self.max_scroll_y:
            sv.request_scroll_shift(forward=True, step=25)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.scroll_up(animate=False)
        if self.peer_table is not None:
            self.peer_table.scroll_to(y=self.scroll_y, animate=False, force=True)
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y <= 0:
            sv.request_scroll_shift(forward=False, step=25)

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.stop()
        self.scroll_left(animate=False)

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.stop()
        self.scroll_right(animate=False)

    def action_cursor_left(self) -> None:
        if self.scroll_x > 0:
            vp_width = getattr(self.scrollable_content_region, "width", 0) or getattr(self.size, "width", 40) or 40
            half_screen = max(1, vp_width // 2)
            self.scroll_to(x=max(0, self.scroll_x - half_screen), animate=False, force=True)
        else:
            super().action_cursor_left()

    def action_cursor_right(self) -> None:
        if self.scroll_x < self.max_scroll_x:
            vp_width = getattr(self.scrollable_content_region, "width", 0) or getattr(self.size, "width", 40) or 40
            half_screen = max(1, vp_width // 2)
            self.scroll_to(x=min(self.max_scroll_x, self.scroll_x + half_screen), animate=False, force=True)
        else:
            super().action_cursor_right()

    def action_cursor_down(self) -> None:
        old_row = self.cursor_row
        super().action_cursor_down()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            # If cursor reached or exceeded bottom boundary or cannot move down further, request parent shift
            if self.cursor_row >= self.row_count - 1 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=True, step=30)

    def action_cursor_up(self) -> None:
        old_row = self.cursor_row
        super().action_cursor_up()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            # If cursor reached top boundary, request parent shift backward
            if self.cursor_row <= 0 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=False, step=30)

    def action_page_down(self) -> None:
        old_row = self.cursor_row
        super().action_page_down()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            if self.cursor_row >= self.row_count - 5 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=True, step=sv.window_size // 2)

    def action_page_up(self) -> None:
        old_row = self.cursor_row
        super().action_page_up()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            if self.cursor_row <= 5 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=False, step=sv.window_size // 2)



class SampleMatrixTable(DataTable):
    """Right horizontally scrollable table displaying sample genotype cells."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.peer_table: Optional[DataTable] = None
        self.split_view: Optional[Any] = None
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
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y >= self.max_scroll_y:
            sv.request_scroll_shift(forward=True, step=25)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.scroll_up(animate=False)
        if self.peer_table is not None:
            self.peer_table.scroll_to(y=self.scroll_y, animate=False, force=True)
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y <= 0:
            sv.request_scroll_shift(forward=False, step=25)

    def _get_column_bounds(self, col_idx: int) -> Tuple[int, int]:
        """Compute the horizontal range (col_left, col_right) in content coordinates."""
        try:
            if hasattr(self, "_get_cell_region"):
                coord = getattr(self, "cursor_coordinate", None)
                if coord is not None:
                    reg = self._get_cell_region(coord)
                    return reg.x, reg.x + reg.width
        except Exception:
            pass

        col_left = 0
        col_width = 8
        try:
            cols = list(self.columns.values())
            if 0 <= col_idx < len(cols):
                col_left = sum(c.width for c in cols[:col_idx])
                col_width = cols[col_idx].width
        except Exception:
            col_left = col_idx * 8
            col_width = 8
        return col_left, col_left + col_width

    def _get_viewport_width(self) -> int:
        """Get the visible content viewport width."""
        if hasattr(self, "scrollable_content_region") and self.scrollable_content_region.width > 0:
            return self.scrollable_content_region.width
        if hasattr(self, "content_size") and self.content_size.width > 0:
            return self.content_size.width
        return getattr(self.size, "width", 80) or 80

    def scroll_column_half_screen(self, col_idx: int) -> None:
        """Scroll container half screen if cursor column moves beyond viewport edges."""
        vp_width = self._get_viewport_width()
        half_screen = max(1, vp_width // 2)
        scroll_x = getattr(self, "scroll_x", 0)
        viewport_left = scroll_x
        viewport_right = scroll_x + vp_width

        col_left, col_right = self._get_column_bounds(col_idx)

        if col_idx == 0:
            self.scroll_to(x=0, animate=False, force=True)
            return

        if col_right > viewport_right:
            # Cursor moved beyond the right edge: scroll half screen to the right
            target_x = scroll_x + half_screen
            target_x = max(target_x, col_right - vp_width + 2)
            self.scroll_to(x=target_x, animate=False, force=True)
        elif col_left < viewport_left:
            # Cursor moved beyond the left edge: scroll half screen to the left
            target_x = max(0, scroll_x - half_screen)
            target_x = min(target_x, col_left)
            self.scroll_to(x=target_x, animate=False, force=True)

    def action_cursor_right(self) -> None:
        old_scroll_x = getattr(self, "scroll_x", 0)
        vp_width = self._get_viewport_width()
        viewport_right = old_scroll_x + vp_width

        super().action_cursor_right()

        new_coord = getattr(self, "cursor_coordinate", None)
        new_col = new_coord.column if new_coord is not None else getattr(self, "cursor_column", 0)
        col_left, col_right = self._get_column_bounds(new_col)

        if col_right > viewport_right or getattr(self, "scroll_x", 0) > old_scroll_x:
            half_screen = max(1, vp_width // 2)
            target_x = old_scroll_x + half_screen
            target_x = max(target_x, col_right - vp_width + 2)
            self.scroll_to(x=target_x, animate=False, force=True)

    def action_cursor_left(self) -> None:
        old_scroll_x = getattr(self, "scroll_x", 0)
        vp_width = self._get_viewport_width()
        viewport_left = old_scroll_x

        super().action_cursor_left()

        new_coord = getattr(self, "cursor_coordinate", None)
        new_col = new_coord.column if new_coord is not None else getattr(self, "cursor_column", 0)

        if new_col == 0:
            self.scroll_to(x=0, animate=False, force=True)
            return

        col_left, col_right = self._get_column_bounds(new_col)

        if col_left < viewport_left or getattr(self, "scroll_x", 0) < old_scroll_x:
            half_screen = max(1, vp_width // 2)
            target_x = max(0, old_scroll_x - half_screen)
            target_x = min(target_x, col_left)
            self.scroll_to(x=target_x, animate=False, force=True)

    def action_cursor_down(self) -> None:
        old_row = self.cursor_row
        super().action_cursor_down()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            if self.cursor_row >= self.row_count - 1 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=True, step=30)

    def action_cursor_up(self) -> None:
        old_row = self.cursor_row
        super().action_cursor_up()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            if self.cursor_row <= 0 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=False, step=30)

    def action_page_down(self) -> None:
        old_row = self.cursor_row
        super().action_page_down()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            if self.cursor_row >= self.row_count - 5 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=True, step=sv.window_size // 2)

    def action_page_up(self) -> None:
        old_row = self.cursor_row
        super().action_page_up()
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "shift_buffer"):
            sv = sv.parent
        if sv is not None:
            if self.cursor_row <= 5 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=False, step=sv.window_size // 2)



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

    DEFAULT_CSS = """
    VariantSplitView {
        width: 1fr;
        height: 1fr;
        layout: horizontal;
    }

    #split_container {
        width: 1fr;
        height: 100%;
        layout: horizontal;
    }

    #fixed_table {
        height: 100%;
        background: #0b0f17;
    }

    #table_divider {
        width: 1;
        min-width: 1;
        max-width: 1;
        height: 100%;
        color: #334155;
        background: #0b0f17;
    }

    #sample_table {
        width: 1fr;
        height: 100%;
        background: #0b0f17;
    }
    """

    FIXED_WIDTHS = {
        "essential": 28,
        "compact": 36,
        "normal": 56,
        "raw": 76,
    }

    def __init__(
        self,
        records: List[VariantRecord],
        samples: List[str],
        reader: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.reader = reader
        self.records = records
        self.samples = samples
        self._syncing_cursor = False
        self.current_row_idx = 0
        self.current_sample_idx = 0
        self._last_notified: Optional[Tuple[int, int]] = None

        # Horizontal sample windowing for high sample counts (e.g. 500-2,500 samples)
        self.sample_window_size = 25
        self.sample_window_start = 0

        # Virtual windowing buffer state
        self.window_size = 150
        self.buffer_start = 0
        if self.reader:
            if hasattr(self.reader, "get_total_variants_async") and self.reader.get_total_variants_async() is not None:
                self.total_records_count = self.reader.get_total_variants_async()
            elif hasattr(self.reader, "total_variants_ready") and self.reader.total_variants_ready:
                self.total_records_count = self.reader.total_variants
            else:
                self.total_records_count = None  # None indicates background counting in progress; do NOT cap to len(records)!
        else:
            self.total_records_count = len(records)

        self._is_shifting = False
        self._rebuilding = False

        # 1. Left Fixed Table
        self.fixed_table = FixedVariantTable(id="fixed_table", cursor_type="row", zebra_stripes=True)
        self.fixed_table.show_cursor = True

        # 2. Divider - locked to 1 column width to prevent pushing sample_table off-screen
        self.divider = Static("│", id="table_divider")
        self.divider.styles.width = 1
        self.divider.styles.min_width = 1
        self.divider.styles.max_width = 1
        self.divider.styles.height = "100%"

        # 3. Right Horizontally Scrollable Sample Table
        self.sample_table = SampleMatrixTable(id="sample_table", cursor_type="cell", zebra_stripes=True)
        self.sample_table.styles.width = "1fr"
        self.sample_table.styles.height = "100%"
        self.sample_table.show_cursor = True

        # Link peers and split_view directly
        self.fixed_table.peer_table = self.sample_table
        self.sample_table.peer_table = self.fixed_table
        self.fixed_table.split_view = self
        self.sample_table.split_view = self

    def update_total_variants(self, count: int) -> None:
        """Update total variant count when background counter completes."""
        self.total_records_count = count

    def request_scroll_shift(self, forward: bool = True, step: int = 40) -> None:
        """Called by child tables when cursor or scroll reaches the buffer boundary."""
        if not self.reader or self._is_shifting or self._rebuilding:
            return

        if forward:
            # Shift forward
            if self.total_records_count is not None:
                max_start = max(0, self.total_records_count - self.window_size)
                if self.buffer_start >= max_start:
                    return
                new_start = min(max_start, self.buffer_start + step)
            else:
                new_start = self.buffer_start + step

            if new_start > self.buffer_start:
                new_cursor = max(0, min(len(self.records) - 1, self.current_row_idx - (new_start - self.buffer_start)))
                self.shift_buffer(new_start, target_cursor_row=new_cursor)
        else:
            # Shift backward
            if self.buffer_start <= 0:
                return
            new_start = max(0, self.buffer_start - step)
            if new_start < self.buffer_start:
                new_cursor = min(self.window_size - 1, self.current_row_idx + (self.buffer_start - new_start))
                self.shift_buffer(new_start, target_cursor_row=new_cursor)

    def shift_buffer(self, new_start: int, target_cursor_row: Optional[int] = None) -> None:
        """Shifts the live row buffer window dynamically without lag."""
        if not self.reader or self._is_shifting or self._rebuilding:
            return

        if self.total_records_count is not None:
            if self.total_records_count <= self.window_size:
                return
            new_start = max(0, min(new_start, self.total_records_count - self.window_size))
        else:
            new_start = max(0, new_start)

        if new_start == self.buffer_start:
            return

        self._is_shifting = True
        try:
            new_records = self.reader.get_slice(new_start, self.window_size)
            if not new_records:
                if self.total_records_count is None:
                    self.total_records_count = self.buffer_start + len(self.records)
                return
            self.buffer_start = new_start
            self.records = new_records
            if len(new_records) < self.window_size and self.total_records_count is None:
                self.total_records_count = new_start + len(new_records)

            if target_cursor_row is not None:
                self.current_row_idx = max(0, min(target_cursor_row, len(self.records) - 1))
            else:
                self.current_row_idx = max(0, min(self.current_row_idx, len(self.records) - 1))

            self.rebuild_tables()

            final_row = self.current_row_idx
            if 0 <= final_row < len(self.records):
                local_col = (
                    self.current_sample_idx
                    if len(self.samples) <= self.sample_window_size
                    else max(0, min(self.sample_window_size - 1, self.current_sample_idx - self.sample_window_start))
                )
                try:
                    self.fixed_table.move_cursor(row=final_row, animate=False)
                except (TypeError, Exception):
                    try:
                        self.fixed_table.move_cursor(row=final_row)
                    except Exception:
                        pass

                try:
                    self.sample_table.move_cursor(row=final_row, column=local_col, animate=False)
                except (TypeError, Exception):
                    try:
                        self.sample_table.move_cursor(row=final_row, column=local_col)
                    except Exception:
                        pass
        finally:
            self._is_shifting = False

    def jump_to_region(self, chrom: str, pos: int) -> bool:
        """Seek and center table directly on target genomic coordinates."""
        if not self.reader:
            return False

        records = self.reader.query_region(chrom, pos, pos + 500000, limit=self.window_size)
        if not records:
            # Fallback broader query or closest variants
            records = self.reader.query_region(chrom, max(0, pos - 100000), pos + 100000, limit=self.window_size)

        if records:
            self.records = records
            self.current_row_idx = 0
            self.rebuild_tables()
            return True
        return False

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
        self._rebuilding = True
        try:
            self._last_notified = None
            self.rebuild_fixed_table()
            self.rebuild_sample_table()
            self._notify_selection(self.current_row_idx, self.current_sample_idx)
        finally:
            self._rebuilding = False

    def rebuild_fixed_table(self):
        """Constructs left fixed variant columns and sets width with intact chromosome names."""
        self.fixed_table.clear(columns=True)

        target_width = self.FIXED_WIDTHS.get(self.view_mode, 56)
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
            # Display full exact chromosome name without normalization or substring replacement
            chrom_display = r.chrom
            if self.view_mode == "raw":
                qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
                info_short = f"GENE={r.gene};MUT={r.mutation}"
                row_cells = [
                    chrom_display, str(r.pos), r.var_id, r.ref, r.alt_str,
                    qual_str, r.filter, info_short, ":".join(r.format_keys[:3])
                ]
            elif self.view_mode == "compact":
                row_cells = [chrom_display, str(r.pos), r.ref, r.alt_str]
            elif self.view_mode == "essential":
                row_cells = [chrom_display, str(r.pos)]
            else:  # "normal"
                qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
                filter_styled = Text(r.filter, style="green" if r.filter == "PASS" else "red")
                gene_styled = Text(r.gene, style="bold yellow" if r.drug_annotation else "white")
                row_cells = [chrom_display, str(r.pos), r.ref, r.alt_str, qual_str, filter_styled, gene_styled]

            self.fixed_table.add_row(*row_cells, key=f"frow_{r_idx}")


    def get_visible_samples(self) -> List[str]:
        if len(self.samples) <= self.sample_window_size:
            return self.samples
        return self.samples[self.sample_window_start : self.sample_window_start + self.sample_window_size]

    def rebuild_sample_table(self):
        """Constructs right horizontally scrollable sample columns using dynamic windowing."""
        self.sample_table.clear(columns=True)
        visible_samples = self.get_visible_samples()

        for s in visible_samples:
            self.sample_table.add_column(Text(s, style="bold bright_white"), key=f"s_{s}")

        for r_idx, r in enumerate(self.records):
            row_cells = []
            for s in visible_samples:
                s_dict = r.sample_data.get(s, {})
                cell_val = str(s_dict.get(self.format_tag, "."))
                row_cells.append(self._style_sample_cell(cell_val, self.format_tag))
            self.sample_table.add_row(*row_cells, key=f"srow_{r_idx}")

    def _check_sample_window_boundary(self, local_col: int) -> None:
        """Dynamically shifts horizontal sample column window when cursor reaches window edge."""
        if len(self.samples) <= self.sample_window_size:
            return

        step = 8
        if local_col >= self.sample_window_size - 2 and (self.sample_window_start + self.sample_window_size) < len(self.samples):
            new_start = min(len(self.samples) - self.sample_window_size, self.sample_window_start + step)
            if new_start != self.sample_window_start:
                new_local_col = max(0, self.current_sample_idx - new_start)
                self.sample_window_start = new_start
                self.rebuild_sample_table()
                try:
                    self.sample_table.move_cursor(row=self.current_row_idx, column=new_local_col, animate=False)
                except Exception:
                    pass
        elif local_col <= 2 and self.sample_window_start > 0:
            new_start = max(0, self.sample_window_start - step)
            if new_start != self.sample_window_start:
                new_local_col = min(self.sample_window_size - 1, self.current_sample_idx - new_start)
                self.sample_window_start = new_start
                self.rebuild_sample_table()
                try:
                    self.sample_table.move_cursor(row=self.current_row_idx, column=new_local_col, animate=False)
                except Exception:
                    pass

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

    def _check_buffer_boundary(self, target_row: int) -> None:
        """Dynamically shift buffer window when cursor approaches top or bottom edge."""
        if not self.reader or self._is_shifting or self._rebuilding:
            return
        buffer_len = len(self.records)
        shift_step = 40
        if target_row >= buffer_len - 15:
            # Approaching bottom boundary
            if self.total_records_count is not None:
                max_start = max(0, self.total_records_count - self.window_size)
                if self.buffer_start >= max_start:
                    return
                new_start = min(max_start, self.buffer_start + shift_step)
            else:
                new_start = self.buffer_start + shift_step

            if new_start > self.buffer_start:
                new_cursor = max(0, min(buffer_len - 1, target_row - (new_start - self.buffer_start)))
                self.shift_buffer(new_start, target_cursor_row=new_cursor)
        elif target_row <= 15 and self.buffer_start > 0:
            # Approaching top boundary
            new_start = max(0, self.buffer_start - shift_step)
            if new_start < self.buffer_start:
                new_cursor = min(self.window_size - 1, target_row + (self.buffer_start - new_start))
                self.shift_buffer(new_start, target_cursor_row=new_cursor)


    # Synchronize Cursor Movement (Arrow Up/Down, Cell Selection)
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        if self._rebuilding or self._is_shifting:
            return
        if event.data_table.id == "fixed_table":
            target_row = event.cursor_row
            local_col = (
                self.current_sample_idx
                if len(self.samples) <= self.sample_window_size
                else max(0, min(self.sample_window_size - 1, self.current_sample_idx - self.sample_window_start))
            )
            # Only drive peer if sample_table is not already at target_row and fixed_table is active
            if self.sample_table.cursor_row != target_row:
                if self.fixed_table.has_focus or not self.sample_table.has_focus:
                    self._syncing_cursor = True
                    try:
                        try:
                            self.sample_table.move_cursor(row=target_row, column=local_col, animate=False)
                        except TypeError:
                            self.sample_table.move_cursor(row=target_row, column=local_col)
                    finally:
                        self._syncing_cursor = False

            if self.current_row_idx != target_row:
                self.current_row_idx = target_row
                self._notify_selection(self.current_row_idx, self.current_sample_idx)
                self._check_buffer_boundary(target_row)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted):
        if self._rebuilding or self._is_shifting:
            return
        if event.data_table.id == "sample_table":
            target_row = event.coordinate.row
            target_local_col = event.coordinate.column

            if len(self.samples) <= self.sample_window_size:
                global_col = target_local_col
            else:
                global_col = self.sample_window_start + target_local_col

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

            if self.current_row_idx != target_row or self.current_sample_idx != global_col:
                self.current_row_idx = target_row
                self.current_sample_idx = global_col
                self.sample_table.scroll_column_half_screen(target_local_col)
                self._notify_selection(self.current_row_idx, self.current_sample_idx)
                self._check_buffer_boundary(target_row)
                self._check_sample_window_boundary(target_local_col)

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
