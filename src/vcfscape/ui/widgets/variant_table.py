"""
Central Variant Split Table for Malaria VCF TUI.
Provides a true vertical split between:
1. Fixed variant information columns (toggleable between Raw, Normal, Compact, Essential)
2. Vertical divider
3. Horizontally scrollable sample matrix columns fitted to active FORMAT tag
With guaranteed bidirectional vertical scroll and cursor synchronization,
in-place virtual row buffer updates (zero clear() during scroll), and
native horizontal sample column navigation.
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
        peer = self.peer_table
        if peer is not None and not self._syncing_scroll and not getattr(peer, "_syncing_scroll", False):
            if abs(getattr(peer, "scroll_y", 0) - new_value) >= 1.0:
                self._syncing_scroll = True
                peer._syncing_scroll = True
                try:
                    peer.scroll_to(y=new_value, animate=False, force=True)
                except Exception:
                    pass
                finally:
                    peer._syncing_scroll = False
                    self._syncing_scroll = False

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.scroll_down(animate=False)
        peer = self.peer_table
        if peer is not None:
            try:
                peer.scroll_to(y=self.scroll_y, animate=False, force=True)
            except Exception:
                pass
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y >= self.max_scroll_y:
            sv.request_scroll_shift(forward=True, step=25)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.scroll_up(animate=False)
        peer = self.peer_table
        if peer is not None:
            try:
                peer.scroll_to(y=self.scroll_y, animate=False, force=True)
            except Exception:
                pass
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y <= 0:
            sv.request_scroll_shift(forward=False, step=25)

    def action_cursor_down(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "advance_row"):
            sv = sv.parent

        old_row = self.cursor_row
        if sv is not None and hasattr(sv, "can_advance_row") and sv.can_advance_row(forward=True):
            if self.cursor_row >= self.row_count - 1 or self.cursor_row == old_row:
                sv.advance_row(forward=True)
                return

        super().action_cursor_down()
        if sv is not None:
            if self.cursor_row >= self.row_count - 1 or self.cursor_row == old_row:
                sv.advance_row(forward=True)

    def action_cursor_up(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "advance_row"):
            sv = sv.parent

        old_row = self.cursor_row
        if sv is not None and hasattr(sv, "can_advance_row") and sv.can_advance_row(forward=False):
            if self.cursor_row <= 0 or self.cursor_row == old_row:
                sv.advance_row(forward=False)
                return

        super().action_cursor_up()
        if sv is not None:
            if self.cursor_row <= 0 or self.cursor_row == old_row:
                sv.advance_row(forward=False)

    def action_page_down(self) -> None:
        old_row = self.cursor_row
        super().action_page_down()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "request_scroll_shift"):
            if self.cursor_row >= self.row_count - 5 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=True, step=sv.window_size // 2)

    def action_page_up(self) -> None:
        old_row = self.cursor_row
        super().action_page_up()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "request_scroll_shift"):
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
        peer = self.peer_table
        if peer is not None and not self._syncing_scroll and not getattr(peer, "_syncing_scroll", False):
            if abs(getattr(peer, "scroll_y", 0) - new_value) >= 1.0:
                self._syncing_scroll = True
                peer._syncing_scroll = True
                try:
                    peer.scroll_to(y=new_value, animate=False, force=True)
                except Exception:
                    pass
                finally:
                    peer._syncing_scroll = False
                    self._syncing_scroll = False

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.scroll_down(animate=False)
        peer = self.peer_table
        if peer is not None:
            try:
                peer.scroll_to(y=self.scroll_y, animate=False, force=True)
            except Exception:
                pass
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y >= self.max_scroll_y:
            sv.request_scroll_shift(forward=True, step=25)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.scroll_up(animate=False)
        peer = self.peer_table
        if peer is not None:
            try:
                peer.scroll_to(y=self.scroll_y, animate=False, force=True)
            except Exception:
                pass
        sv = getattr(self, "split_view", None)
        if sv is not None and self.scroll_y <= 0:
            sv.request_scroll_shift(forward=False, step=25)

    def _get_column_bounds(self, col_idx: int) -> Tuple[int, int]:
        """Compute the horizontal range (col_left, col_right) in content coordinates."""
        try:
            if hasattr(self, "_get_cell_region"):
                coord = getattr(self, "cursor_coordinate", None)
                if coord is not None and getattr(coord, "column", None) == col_idx:
                    reg = self._get_cell_region(coord)
                    return reg.x, reg.x + reg.width
        except Exception:
            pass

        col_left = 0
        col_width = 8
        try:
            cols = list(self.columns.values())
            if 0 <= col_idx < len(cols):
                def _w(c):
                    return max(4, int(getattr(c, "width", None) or getattr(c, "auto_width", None) or 8))
                col_left = sum(_w(c) for c in cols[:col_idx])
                col_width = _w(cols[col_idx])
            else:
                col_left = col_idx * 8
                col_width = 8
        except Exception:
            col_left = col_idx * 8
            col_width = 8
        return col_left, col_left + col_width

    def _get_viewport_width(self) -> int:
        """Get the visible content viewport width."""
        scr = getattr(self, "scrollable_content_region", None)
        if scr is not None and getattr(scr, "width", 0) > 0:
            return scr.width
        cs = getattr(self, "content_size", None)
        if cs is not None and getattr(cs, "width", 0) > 0:
            return cs.width
        size_obj = getattr(self, "size", None)
        if size_obj is not None:
            return getattr(size_obj, "width", 80) or 80
        return 80

    def is_column_in_viewport(self, col_idx: int) -> bool:
        """Check if column is fully visible within current horizontal viewport."""
        vp_width = self._get_viewport_width()
        col_left, col_right = self._get_column_bounds(col_idx)
        vp_left = getattr(self, "scroll_x", 0)
        vp_right = vp_left + vp_width
        return col_left >= vp_left and col_right <= vp_right

    def scroll_column_centered(self, col_idx: int, force: bool = False) -> None:
        """Auto-centers the active sample column in the visible viewport.
        Only performs auto-centering if the pointer passes the edge of the viewport
        (or if force is True).
        """
        if not force and self.is_column_in_viewport(col_idx):
            return

        vp_width = self._get_viewport_width()
        col_left, col_right = self._get_column_bounds(col_idx)
        col_center = (col_left + col_right) // 2
        target_x = max(0, col_center - (vp_width // 2))
        if abs(getattr(self, "scroll_x", 0) - target_x) > 1:
            try:
                self.scroll_to(x=target_x, animate=False, force=True)
            except Exception:
                pass

    def scroll_column_half_screen(self, col_idx: int) -> None:
        """Backward-compatible helper that auto-centers active column in viewport if out of view."""
        self.scroll_column_centered(col_idx)

    def action_cursor_right(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "can_advance_sample") and sv.can_advance_sample(forward=True):
            sv.advance_sample(forward=True)
        else:
            super().action_cursor_right()
            new_coord = getattr(self, "cursor_coordinate", None)
            new_col = new_coord.column if new_coord is not None else getattr(self, "cursor_column", 0)
            self.scroll_column_centered(new_col)

    def action_cursor_left(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "can_advance_sample") and sv.can_advance_sample(forward=False):
            sv.advance_sample(forward=False)
        else:
            super().action_cursor_left()
            new_coord = getattr(self, "cursor_coordinate", None)
            new_col = new_coord.column if new_coord is not None else getattr(self, "cursor_column", 0)
            self.scroll_column_centered(new_col)

    def action_cursor_down(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "advance_row"):
            sv = sv.parent

        old_row = self.cursor_row
        if sv is not None and hasattr(sv, "can_advance_row") and sv.can_advance_row(forward=True):
            if self.cursor_row >= self.row_count - 1 or self.cursor_row == old_row:
                sv.advance_row(forward=True)
                return

        super().action_cursor_down()
        if sv is not None:
            if self.cursor_row >= self.row_count - 1 or self.cursor_row == old_row:
                sv.advance_row(forward=True)

    def action_cursor_up(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "advance_row"):
            sv = sv.parent

        old_row = self.cursor_row
        if sv is not None and hasattr(sv, "can_advance_row") and sv.can_advance_row(forward=False):
            if self.cursor_row <= 0 or self.cursor_row == old_row:
                sv.advance_row(forward=False)
                return

        super().action_cursor_up()
        if sv is not None:
            if self.cursor_row <= 0 or self.cursor_row == old_row:
                sv.advance_row(forward=False)

    def action_page_down(self) -> None:
        old_row = self.cursor_row
        super().action_page_down()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "request_scroll_shift"):
            if self.cursor_row >= self.row_count - 5 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=True, step=sv.window_size // 2)

    def action_page_up(self) -> None:
        old_row = self.cursor_row
        super().action_page_up()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "request_scroll_shift"):
            if self.cursor_row <= 5 or self.cursor_row == old_row:
                sv.request_scroll_shift(forward=False, step=sv.window_size // 2)


class VariantSplitView(Widget):
    """
    Split table container:
    - Left: FixedVariantTable for variant info columns (frozen horizontally)
    - Center: Vertical divider line
    - Right: SampleMatrixTable for sample genotype matrix (horizontally scrollable across all samples)
    - Both tables stay in lockstep vertically during all scrolling and keyboard events.
    - Buffer window uses in-place row cell updates without clear() during scrolling.
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

        # Sample column virtualization state: visible viewport + buffer window
        self.max_sample_columns = 50
        self.sample_window_size = min(len(samples), self.max_sample_columns) if samples else 0
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
                self.total_records_count = None
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

    def _sync_both_tables_cursor(self, row: int, col: int) -> None:
        self._syncing_cursor = True
        try:
            try:
                self.fixed_table.move_cursor(row=row, animate=False)
            except Exception:
                pass

            try:
                local_col = max(0, min(self.sample_window_size - 1, col - self.sample_window_start))
                self.sample_table.move_cursor(row=row, column=local_col, animate=False)
            except Exception:
                pass
        finally:
            self._syncing_cursor = False

    def can_advance_sample(self, forward: bool) -> bool:
        if not self.samples:
            return False
        if forward:
            return self.current_sample_idx < len(self.samples) - 1
        return self.current_sample_idx > 0

    def advance_sample(self, forward: bool) -> None:
        if not self.samples:
            return
        if forward:
            target = min(len(self.samples) - 1, self.current_sample_idx + 1)
        else:
            target = max(0, self.current_sample_idx - 1)

        if target == self.current_sample_idx:
            return

        self.set_active_sample(target)

    def set_active_sample(self, global_col: int, force_center: bool = False) -> None:
        """Sets active sample column across virtualized cohort sample columns."""
        if not self.samples:
            return
        global_col = max(0, min(len(self.samples) - 1, global_col))
        self.current_sample_idx = global_col

        # Check if horizontal sample window needs to slide
        if len(self.samples) > self.sample_window_size:
            local_col = global_col - self.sample_window_start
            margin = 6
            new_start = self.sample_window_start
            if local_col < margin and self.sample_window_start > 0:
                new_start = max(0, global_col - margin)
            elif (
                local_col >= self.sample_window_size - margin
                and self.sample_window_start + self.sample_window_size < len(self.samples)
            ):
                new_start = min(
                    len(self.samples) - self.sample_window_size,
                    global_col - self.sample_window_size + margin + 1,
                )

            if new_start != self.sample_window_start:
                self.sample_window_start = new_start
                # Update column labels in place
                visible = self.get_visible_samples()
                for j, s in enumerate(visible):
                    col_k = f"col_{j}"
                    if hasattr(self.sample_table, "columns") and col_k in self.sample_table.columns:
                        try:
                            self.sample_table.columns[col_k].label = Text(s, style="bold bright_white")
                        except Exception:
                            pass
                # Update row cells in place without clearing
                for r_idx, r in enumerate(self.records):
                    self._update_sample_row_cells(f"row_{r_idx}", r)
                try:
                    self.sample_table.refresh()
                except Exception:
                    pass

        local_col = max(0, min(self.sample_window_size - 1, global_col - self.sample_window_start))
        try:
            self.sample_table.move_cursor(row=self.current_row_idx, column=local_col, animate=False)
        except Exception:
            pass
        self.sample_table.scroll_column_centered(local_col, force=force_center)
        self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def can_advance_row(self, forward: bool) -> bool:
        if not self.reader:
            return False
        curr_global = self.buffer_start + self.current_row_idx
        if forward:
            if self.total_records_count is not None:
                return curr_global < self.total_records_count - 1
            return True
        return curr_global > 0

    def advance_row(self, forward: bool) -> None:
        """Advance cursor by 1 row across buffer window boundaries without snapback."""
        curr_global = self.buffer_start + self.current_row_idx
        if forward:
            target_global = curr_global + 1
            if self.total_records_count is not None and target_global >= self.total_records_count:
                return
        else:
            target_global = max(0, curr_global - 1)

        self.set_active_row(target_global)

    def set_active_row(self, target_global: int) -> None:
        """Sets active variant row by global index, sliding buffer in-place when approaching edges."""
        if target_global < 0:
            return
        if self.total_records_count is not None and target_global >= self.total_records_count:
            return

        local_row = target_global - self.buffer_start
        margin = 15
        needs_shift = (
            local_row < margin and self.buffer_start > 0
        ) or (
            local_row >= len(self.records) - margin and (
                self.total_records_count is None or (self.buffer_start + len(self.records)) < self.total_records_count
            )
        )

        if not needs_shift and 0 <= local_row < len(self.records):
            # Target is inside current slice: move cursor directly without buffer rebuild
            self.current_row_idx = local_row
            self._sync_both_tables_cursor(local_row, self.current_sample_idx)
            self._notify_selection(local_row, self.current_sample_idx)
            return

        # Calculate new buffer start
        shift_step = 40
        if local_row >= len(self.records) - margin:
            new_start = self.buffer_start + shift_step
            if self.total_records_count is not None:
                max_start = max(0, self.total_records_count - self.window_size)
                new_start = min(max_start, new_start)
        else:
            new_start = max(0, self.buffer_start - shift_step)

        if new_start == self.buffer_start:
            local_row = max(0, min(len(self.records) - 1, target_global - self.buffer_start))
            self.current_row_idx = local_row
            self._sync_both_tables_cursor(local_row, self.current_sample_idx)
            self._notify_selection(local_row, self.current_sample_idx)
            return

        self._apply_buffer_slice(new_start, target_global)

    def request_scroll_shift(self, forward: bool = True, step: int = 40) -> None:
        """Called by child tables when cursor or scroll reaches the buffer boundary."""
        if not self.reader or self._is_shifting or self._rebuilding:
            return

        curr_global = self.buffer_start + self.current_row_idx
        if forward:
            target_global = curr_global + step
            new_start = self.buffer_start + step
            if self.total_records_count is not None:
                max_start = max(0, self.total_records_count - self.window_size)
                new_start = min(max_start, new_start)
                target_global = min(self.total_records_count - 1, target_global)
        else:
            target_global = max(0, curr_global - step)
            new_start = max(0, self.buffer_start - step)

        if new_start != self.buffer_start:
            self._apply_buffer_slice(new_start, target_global)

    def shift_buffer(self, new_start: int, target_cursor_row: Optional[int] = None) -> None:
        """Shifts live row buffer window dynamically while pinning cursor and viewport."""
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

        if target_cursor_row is not None:
            target_global = new_start + target_cursor_row
        else:
            target_global = self.buffer_start + self.current_row_idx

        self._apply_buffer_slice(new_start, target_global)

    def _apply_buffer_slice(self, new_start: int, target_global: int) -> None:
        """Updates virtual row buffer in place without clear() or DOM node recreation."""
        if not self.reader or self._is_shifting:
            return

        new_records = self.reader.get_slice(new_start, self.window_size)
        if not new_records:
            if self.total_records_count is None:
                self.total_records_count = self.buffer_start + len(self.records)
            return

        old_scroll_y = getattr(self.fixed_table, "scroll_y", 0)
        screen_y_offset = max(0, self.current_row_idx - old_scroll_y)

        self._is_shifting = True
        try:
            self.buffer_start = new_start
            self.records = new_records
            if len(new_records) < self.window_size and self.total_records_count is None:
                self.total_records_count = new_start + len(new_records)

            # Ensure row capacity and update all row cells in place
            self._ensure_row_capacity()
            self._update_all_rows_in_place()

            new_local_row = max(0, min(len(self.records) - 1, target_global - new_start))
            self.current_row_idx = new_local_row

            # Preserve exact visual screen line
            target_scroll_y = max(0, new_local_row - screen_y_offset)
            try:
                self.fixed_table.scroll_to(y=target_scroll_y, animate=False, force=True)
                self.sample_table.scroll_to(y=target_scroll_y, animate=False, force=True)
            except Exception:
                pass

            self._sync_both_tables_cursor(new_local_row, self.current_sample_idx)
            self._notify_selection(new_local_row, self.current_sample_idx)
        finally:
            self._is_shifting = False

    def jump_to_region(self, chrom: str, pos: int) -> bool:
        """Seek and center table directly on target genomic coordinates."""
        if not self.reader:
            return False

        records = self.reader.query_region(chrom, pos, pos + 500000, limit=self.window_size)
        if not records:
            records = self.reader.query_region(chrom, max(0, pos - 100000), pos + 100000, limit=self.window_size)

        if records:
            self.records = records
            self.buffer_start = 0
            self.current_row_idx = 0
            self._ensure_row_capacity()
            self._update_all_rows_in_place()
            try:
                self.fixed_table.scroll_to(y=0, animate=False, force=True)
                self.sample_table.scroll_to(y=0, animate=False, force=True)
            except Exception:
                pass
            self._sync_both_tables_cursor(0, self.current_sample_idx)
            self._notify_selection(0, self.current_sample_idx)
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
        self.buffer_start = 0
        self._ensure_row_capacity()
        self._update_all_rows_in_place()
        try:
            self.fixed_table.scroll_to(y=0, animate=False, force=True)
            self.sample_table.scroll_to(y=0, animate=False, force=True)
        except Exception:
            pass
        self._sync_both_tables_cursor(0, self.current_sample_idx)
        self._notify_selection(0, self.current_sample_idx)

    def set_view_mode(self, mode: str):
        self.view_mode = mode.lower()
        self.rebuild_fixed_table()
        self._sync_both_tables_cursor(self.current_row_idx, self.current_sample_idx)

    def set_format_tag(self, tag: str):
        self.format_tag = tag.upper()
        # In-place update of sample cells without clearing table or columns
        for r_idx, r in enumerate(self.records):
            self._update_sample_row_cells(f"row_{r_idx}", r)

    def cycle_view_mode(self) -> str:
        modes = ["normal", "compact", "essential", "raw"]
        curr_idx = modes.index(self.view_mode) if self.view_mode in modes else 0
        new_mode = modes[(curr_idx + 1) % len(modes)]
        self.set_view_mode(new_mode)
        return new_mode.capitalize()

    def rebuild_tables(self):
        """Constructs both fixed and sample tables initially."""
        self._rebuilding = True
        try:
            self._last_notified = None
            self.rebuild_fixed_table()
            self.rebuild_sample_table()
            self._notify_selection(self.current_row_idx, self.current_sample_idx)
        finally:
            self._rebuilding = False

    def _get_fixed_columns(self) -> List[str]:
        if self.view_mode == "raw":
            return ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
        elif self.view_mode == "compact":
            return ["CHROM", "POS", "REF", "ALT"]
        elif self.view_mode == "essential":
            return ["CHROM", "POS"]
        return ["CHROM", "POS", "REF", "ALT", "QUAL", "FILTER", "GENE"]

    def _get_fixed_row_cells(self, r: VariantRecord) -> Dict[str, Any]:
        chrom_display = r.chrom
        if self.view_mode == "raw":
            qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
            info_short = f"GENE={r.gene};MUT={r.mutation}"
            return {
                "f_CHROM": chrom_display,
                "f_POS": str(r.pos),
                "f_ID": r.var_id,
                "f_REF": r.ref,
                "f_ALT": r.alt_str,
                "f_QUAL": qual_str,
                "f_FILTER": r.filter,
                "f_INFO": info_short,
                "f_FORMAT": ":".join(r.format_keys[:3]),
            }
        elif self.view_mode == "compact":
            return {
                "f_CHROM": chrom_display,
                "f_POS": str(r.pos),
                "f_REF": r.ref,
                "f_ALT": r.alt_str,
            }
        elif self.view_mode == "essential":
            return {
                "f_CHROM": chrom_display,
                "f_POS": str(r.pos),
            }
        else:  # "normal"
            qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
            filter_styled = Text(r.filter, style="green" if r.filter == "PASS" else "red")
            gene_styled = Text(r.gene, style="bold yellow" if r.drug_annotation else "white")
            return {
                "f_CHROM": chrom_display,
                "f_POS": str(r.pos),
                "f_REF": r.ref,
                "f_ALT": r.alt_str,
                "f_QUAL": qual_str,
                "f_FILTER": filter_styled,
                "f_GENE": gene_styled,
            }

    def _update_fixed_row_cells(self, row_key: str, r: VariantRecord) -> None:
        cells = self._get_fixed_row_cells(r)
        for col_k, val in cells.items():
            try:
                self.fixed_table.update_cell(row_key, col_k, val)
            except Exception:
                pass

    def _update_sample_row_cells(self, row_key: str, r: VariantRecord) -> None:
        visible = self.get_visible_samples()
        for j, s in enumerate(visible):
            col_k = f"col_{j}"
            s_dict = r.sample_data.get(s, {})
            raw_val = str(s_dict.get(self.format_tag, "."))
            styled = self._style_sample_cell(raw_val, self.format_tag)
            try:
                self.sample_table.update_cell(row_key, col_k, styled)
            except Exception:
                pass

    def _ensure_row_capacity(self) -> None:
        needed = len(self.records)
        fixed_count = getattr(self.fixed_table, "row_count", 0)
        if fixed_count < needed:
            cols_fixed = self._get_fixed_columns()
            visible_count = len(self.get_visible_samples())
            for r_idx in range(fixed_count, needed):
                row_key = f"row_{r_idx}"
                self.fixed_table.add_row(*([""] * len(cols_fixed)), key=row_key)
                self.sample_table.add_row(*([""] * visible_count), key=row_key)

    def _update_all_rows_in_place(self) -> None:
        """Updates cell contents for all current records in place using update_cell."""
        for r_idx, r in enumerate(self.records):
            row_key = f"row_{r_idx}"
            self._update_fixed_row_cells(row_key, r)
            self._update_sample_row_cells(row_key, r)

        # Blank out remaining rows if file ends before window capacity
        fixed_count = getattr(self.fixed_table, "row_count", 0)
        if fixed_count > len(self.records):
            cols_fixed = self._get_fixed_columns()
            visible_count = len(self.get_visible_samples())
            for r_idx in range(len(self.records), fixed_count):
                row_key = f"row_{r_idx}"
                for col_name in cols_fixed:
                    try:
                        self.fixed_table.update_cell(row_key, f"f_{col_name}", "")
                    except Exception:
                        pass
                for j in range(visible_count):
                    try:
                        self.sample_table.update_cell(row_key, f"col_{j}", Text(""))
                    except Exception:
                        pass

    def rebuild_fixed_table(self):
        """Constructs left fixed variant columns and sets width with intact chromosome names."""
        self.fixed_table.clear(columns=True)

        target_width = self.FIXED_WIDTHS.get(self.view_mode, 56)
        self.fixed_table.styles.width = target_width

        cols = self._get_fixed_columns()
        for col in cols:
            self.fixed_table.add_column(Text(col, style="bold cyan"), key=f"f_{col}")

        for r_idx, r in enumerate(self.records):
            cells_dict = self._get_fixed_row_cells(r)
            row_cells = [cells_dict[f"f_{col}"] for col in cols]
            self.fixed_table.add_row(*row_cells, key=f"row_{r_idx}")

    def get_visible_samples(self) -> List[str]:
        return self.samples[self.sample_window_start : self.sample_window_start + self.sample_window_size]

    def rebuild_sample_table(self):
        """Constructs right horizontally scrollable sample columns across visible window."""
        self.sample_table.clear(columns=True)
        visible = self.get_visible_samples()
        for j, s in enumerate(visible):
            self.sample_table.add_column(Text(s, style="bold bright_white"), key=f"col_{j}")

        for r_idx, r in enumerate(self.records):
            row_cells = []
            for s in visible:
                s_dict = r.sample_data.get(s, {})
                cell_val = str(s_dict.get(self.format_tag, "."))
                row_cells.append(self._style_sample_cell(cell_val, self.format_tag))
            self.sample_table.add_row(*row_cells, key=f"row_{r_idx}")

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
        if target_row >= buffer_len - 15 or (target_row <= 15 and self.buffer_start > 0):
            target_global = self.buffer_start + target_row
            self.set_active_row(target_global)

    def _check_sample_window_boundary(self, local_col: int) -> None:
        """Backward compatibility stub for horizontal sample navigation."""
        pass

    # Synchronize Cursor Movement (Arrow Up/Down, Cell Selection)
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._rebuilding or self._is_shifting or self._syncing_cursor:
            return
        if event.data_table.id == "fixed_table":
            target_row = event.cursor_row
            if self.sample_table.cursor_row != target_row:
                self._syncing_cursor = True
                try:
                    local_col = max(0, min(self.sample_window_size - 1, self.current_sample_idx - self.sample_window_start))
                    self.sample_table.move_cursor(row=target_row, column=local_col, animate=False)
                except Exception:
                    pass
                finally:
                    self._syncing_cursor = False

            if self.current_row_idx != target_row:
                self.current_row_idx = target_row
                self._notify_selection(self.current_row_idx, self.current_sample_idx)
                self._check_buffer_boundary(target_row)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if self._rebuilding or self._is_shifting or self._syncing_cursor:
            return
        if event.data_table.id == "sample_table":
            target_row = event.coordinate.row
            local_col = event.coordinate.column
            global_col = self.sample_window_start + local_col

            if self.fixed_table.cursor_row != target_row:
                self._syncing_cursor = True
                try:
                    self.fixed_table.move_cursor(row=target_row, animate=False)
                except Exception:
                    pass
                finally:
                    self._syncing_cursor = False

            if self.current_row_idx != target_row or self.current_sample_idx != global_col:
                self.current_row_idx = target_row
                self.current_sample_idx = global_col
                self.sample_table.scroll_column_centered(local_col, force=False)
                self._notify_selection(self.current_row_idx, self.current_sample_idx)
                self._check_buffer_boundary(target_row)

    def _notify_selection(self, row_idx: int, sample_col_idx: int) -> None:
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
