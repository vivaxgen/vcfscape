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
    """Left anchored passive table displaying variant metadata columns (commanded by VariantSplitView)."""

    can_focus = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.peer_table: Optional[DataTable] = None
        self.split_view: Optional[Any] = None
        self._syncing_scroll: bool = False

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Disable live mouse pointer tracking over fixed variant table."""
        event.stop()

    def on_enter(self, event: events.Enter) -> None:
        event.stop()

    def on_leave(self, event: events.Leave) -> None:
        event.stop()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "_arm_click_sync"):
            sv._arm_click_sync()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        event.prevent_default()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=3)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        event.prevent_default()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=-3)

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.stop()
        event.prevent_default()

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.stop()
        event.prevent_default()

    def on_key(self, event: events.Key) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_navigation_key"):
            if sv.handle_navigation_key(event.key):
                event.stop()
                event.prevent_default()

    def action_cursor_down(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "navigate_rows"):
            sv = sv.parent
        if sv is not None and hasattr(sv, "navigate_rows"):
            sv.navigate_rows(1)

    def action_cursor_up(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "navigate_rows"):
            sv = sv.parent
        if sv is not None and hasattr(sv, "navigate_rows"):
            sv.navigate_rows(-1)

    def action_cursor_left(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "advance_sample"):
            sv.advance_sample(forward=False)

    def action_cursor_right(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "advance_sample"):
            sv.advance_sample(forward=True)

    def action_page_down(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "navigate_page"):
            sv.navigate_page(forward=True)

    def action_page_up(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "navigate_page"):
            sv.navigate_page(forward=False)

    def action_scroll_home(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_home"):
            sv.scroll_samples_home()

    def action_scroll_end(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_end"):
            sv.scroll_samples_end()

    def action_scroll_top(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_home"):
            sv.scroll_samples_home()

    def action_scroll_bottom(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_end"):
            sv.scroll_samples_end()

    def action_scroll_up(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=-1)

    def action_scroll_down(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=1)


class SampleMatrixTable(DataTable):
    """Right horizontally scrollable passive table displaying sample genotype cells (commanded by VariantSplitView)."""

    can_focus = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.peer_table: Optional[DataTable] = None
        self.split_view: Optional[Any] = None

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Disable live mouse pointer tracking over sample matrix table."""
        event.stop()

    def on_enter(self, event: events.Enter) -> None:
        event.stop()

    def on_leave(self, event: events.Leave) -> None:
        event.stop()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "_arm_click_sync"):
            sv._arm_click_sync()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        event.prevent_default()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=3)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        event.prevent_default()
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=-3)

    def on_key(self, event: events.Key) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_navigation_key"):
            if sv.handle_navigation_key(event.key):
                event.stop()
                event.prevent_default()

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
        if sv is not None and hasattr(sv, "advance_sample"):
            sv.advance_sample(forward=True)

    def action_cursor_left(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "advance_sample"):
            sv.advance_sample(forward=False)

    def action_cursor_down(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "navigate_rows"):
            sv = sv.parent
        if sv is not None and hasattr(sv, "navigate_rows"):
            sv.navigate_rows(1)

    def action_cursor_up(self) -> None:
        sv = getattr(self, "split_view", None) or self.parent
        while sv is not None and not hasattr(sv, "navigate_rows"):
            sv = sv.parent
        if sv is not None and hasattr(sv, "navigate_rows"):
            sv.navigate_rows(-1)

    def action_page_down(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "navigate_page"):
            sv.navigate_page(forward=True)

    def action_page_up(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "navigate_page"):
            sv.navigate_page(forward=False)

    def action_scroll_home(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_home"):
            sv.scroll_samples_home()

    def action_scroll_end(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_end"):
            sv.scroll_samples_end()

    def action_scroll_top(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_home"):
            sv.scroll_samples_home()

    def action_scroll_bottom(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "scroll_samples_end"):
            sv.scroll_samples_end()

    def action_scroll_up(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=-1)

    def action_scroll_down(self) -> None:
        sv = getattr(self, "split_view", None)
        if sv is not None and hasattr(sv, "handle_mouse_scroll"):
            sv.handle_mouse_scroll(delta=1)


class VariantSplitView(Widget):
    """
    Top-level Split Table Controller:
    - Holds focus and captures Up/Down/PageUp/PageDown/Left/Right/Home/End and mouse wheel.
    - Commands Left (FixedVariantTable) and Right (SampleMatrixTable) in strict lockstep.
    - Mouse wheel scrolls only the vertical viewport without moving the active row cursor.
    - Home/End scroll horizontally to the first/last sample column without moving vertical scroll/row.
    """

    can_focus = True

    class VariantSelected(Message):
        """Dispatched when cursor moves to a new variant row or sample cell."""
        def __init__(self, record: VariantRecord, sample_id: Optional[str] = None, row_index: int = 0):
            super().__init__()
            self.record = record
            self.sample_id = sample_id
            self.row_index = row_index

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
        scrollbar-size-vertical: 0;
        overflow-y: hidden;
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

    #fixed_table > .datatable--hover,
    #sample_table > .datatable--hover {
        background: transparent;
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
        self.records = list(records)
        self.samples = samples
        self._is_internal_update = False
        self._syncing_cursor = False
        self._accept_next_highlight = False
        self._click_timer: Optional[Any] = None
        self.current_row_idx = 0
        self.current_sample_idx = 0
        self._viewport_scroll_y = 0
        self._last_notified: Optional[Tuple[int, int]] = None

        # Sample column virtualization state: visible viewport + buffer window
        self.max_sample_columns = 50
        self.sample_window_size = min(len(samples), self.max_sample_columns) if samples else 0
        self.sample_window_start = 0

        # Continuous dynamic append row state
        self.window_size = 150
        self.buffer_start = 0
        self._is_fetching_more = False
        self._is_main_stream_view = True
        if self.reader:
            if hasattr(self.reader, "get_total_variants_async") and self.reader.get_total_variants_async() is not None:
                self.total_records_count = self.reader.get_total_variants_async()
            elif hasattr(self.reader, "total_variants_ready") and self.reader.total_variants_ready:
                self.total_records_count = self.reader.total_variants
            else:
                self.total_records_count = None
        else:
            self.total_records_count = len(records)

        self._rebuilding = False

        # 1. Left Fixed Table (passive slave)
        self.fixed_table = FixedVariantTable(id="fixed_table", cursor_type="row", zebra_stripes=True)
        self.fixed_table.show_cursor = True

        # 2. Divider - locked to 1 column width to prevent pushing sample_table off-screen
        self.divider = Static("│", id="table_divider")
        self.divider.styles.width = 1
        self.divider.styles.min_width = 1
        self.divider.styles.max_width = 1
        self.divider.styles.height = "100%"

        # 3. Right Horizontally Scrollable Sample Table (passive slave)
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

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Disable live mouse pointer tracking across split view container."""
        event.stop()

    def _arm_click_sync(self) -> None:
        """Allow the next mouse-initiated RowHighlighted/CellHighlighted and return focus to split view."""
        self._accept_next_highlight = True
        if self._click_timer is not None:
            try:
                self._click_timer.stop()
            except Exception:
                pass
            self._click_timer = None
        try:
            self._click_timer = self.set_timer(0.3, self._disarm_click_sync)
        except Exception:
            pass

    def _disarm_click_sync(self) -> None:
        self._accept_next_highlight = False
        if self._click_timer is not None:
            try:
                self._click_timer.stop()
            except Exception:
                pass
            self._click_timer = None
        try:
            self.focus()
        except Exception:
            pass

    def _get_visible_row_count(self) -> int:
        """Compute common visible row count across both tables (respecting horizontal scrollbar)."""
        heights: List[int] = []
        for tbl in (self.fixed_table, self.sample_table):
            try:
                scr = getattr(tbl, "scrollable_content_region", None)
                if scr is not None and getattr(scr, "height", 0) > 1:
                    hdr_h = getattr(tbl, "header_height", 1) if getattr(tbl, "show_header", True) else 0
                    heights.append(max(1, scr.height - hdr_h))
                    continue
                size_obj = getattr(tbl, "size", None)
                if size_obj is not None and getattr(size_obj, "height", 0) > 2:
                    hdr_h = getattr(tbl, "header_height", 1) if getattr(tbl, "show_header", True) else 0
                    heights.append(max(1, size_obj.height - hdr_h - 1))
            except Exception:
                pass
        return min(heights) if heights else 15

    def _get_max_scroll_y(self) -> int:
        """Maximum vertical scroll offset shared cleanly across both tables."""
        visible_rows = self._get_visible_row_count()
        content_max = max(0, len(self.records) - visible_rows)
        table_maxes: List[int] = []
        for tbl in (self.fixed_table, self.sample_table):
            try:
                m = getattr(tbl, "max_scroll_y", None)
                if m is not None and m >= 0:
                    table_maxes.append(int(m))
            except Exception:
                pass
        if table_maxes:
            return max(0, min(content_max, min(table_maxes)))
        return content_max

    def _move_table_cursor_noscroll(self, table: DataTable, row: int, column: Optional[int] = None) -> None:
        """Move DataTable cursor without triggering Textual's async _scroll_cursor_into_view."""
        try:
            if column is None:
                table.move_cursor(row=row, animate=False, scroll=False)
            else:
                table.move_cursor(row=row, column=column, animate=False, scroll=False)
        except TypeError:
            if column is None:
                table.move_cursor(row=row, animate=False)
            else:
                table.move_cursor(row=row, column=column, animate=False)

    def _command_tables_scroll_y(self, target_y: int) -> None:
        """Command both FixedVariantTable and SampleMatrixTable to the exact same vertical scroll offset."""
        max_y = self._get_max_scroll_y()
        clamped_y = max(0, min(max_y, int(target_y)))
        self._viewport_scroll_y = clamped_y

        batch_ctx = None
        if hasattr(self, "app") and hasattr(self.app, "batch_update"):
            try:
                batch_ctx = self.app.batch_update()
            except Exception:
                batch_ctx = None

        def _apply():
            try:
                self.fixed_table.scroll_to(y=clamped_y, animate=False, force=True)
            except Exception:
                pass
            try:
                self.sample_table.scroll_to(y=clamped_y, animate=False, force=True)
            except Exception:
                pass

        if batch_ctx is not None:
            with batch_ctx:
                _apply()
        else:
            _apply()

    def on_key(self, event: events.Key) -> None:
        """Top-level key interception for VariantSplitView."""
        if self.handle_navigation_key(event.key):
            event.stop()
            event.prevent_default()

    def handle_navigation_key(self, key: str) -> bool:
        """Single authoritative keyboard navigation dispatcher."""
        if key == "up":
            self.navigate_rows(-1)
            return True
        if key == "down":
            self.navigate_rows(1)
            return True
        if key == "pageup":
            self.navigate_page(forward=False)
            return True
        if key == "pagedown":
            self.navigate_page(forward=True)
            return True
        if key == "left":
            self.advance_sample(forward=False)
            return True
        if key == "right":
            self.advance_sample(forward=True)
            return True
        if key == "home":
            self.scroll_samples_home()
            return True
        if key == "end":
            self.scroll_samples_end()
            return True
        return False

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        event.prevent_default()
        self.handle_mouse_scroll(delta=3)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        event.prevent_default()
        self.handle_mouse_scroll(delta=-3)

    def handle_mouse_scroll(self, delta: int) -> None:
        """
        Scroll ONLY the vertical viewport of both tables in lockstep.
        Leaves active highlighted row cursor and sidebar selection untouched.
        """
        if not self.records:
            return
        visible_rows = self._get_visible_row_count()
        target_y = max(0, self._viewport_scroll_y + delta)

        if delta > 0 and self._is_main_stream_view:
            while target_y + visible_rows >= len(self.records) - 15:
                if not self.fetch_more_rows(100):
                    break

        self._command_tables_scroll_y(target_y)

    def on_master_scroll_y(self, new_value: float) -> None:
        """Backward-compatible helper aligning both tables to new_value."""
        self._command_tables_scroll_y(int(new_value))

    def navigate_rows(self, delta: int) -> None:
        """Centralized row navigation for Up/Down/PageUp/PageDown keys."""
        if not self.records:
            return
        target = self.current_row_idx + delta
        if delta > 0 and self.total_records_count is not None and target >= self.total_records_count:
            target = max(0, self.total_records_count - 1)
        if target < 0:
            target = 0
        self.set_active_row(target, sync_fixed=True, sync_sample=True)

    def navigate_page(self, forward: bool, page_size: Optional[int] = None) -> None:
        """Centralized PageUp / PageDown navigation sized to visible viewport."""
        step = page_size if page_size is not None else max(1, self._get_visible_row_count() - 1)
        delta = step if forward else -step
        self.navigate_rows(delta)

    def navigate_scroll(self, delta: int) -> None:
        """Backward-compatible helper delegating mouse wheel scroll to lockstep viewport scroller."""
        self.handle_mouse_scroll(delta)

    def scroll_samples_home(self) -> None:
        """Home key: scroll horizontally to the first sample column without changing vertical position."""
        if not self.samples:
            return
        self.set_active_sample(0, force_center=False, horizontal_align="home")

    def scroll_samples_end(self) -> None:
        """End key: scroll horizontally to the last sample column without changing vertical position."""
        if not self.samples:
            return
        self.set_active_sample(len(self.samples) - 1, force_center=False, horizontal_align="end")

    def _sync_both_tables_cursor(self, row: int, col: int) -> None:
        self._is_internal_update = True
        batch_ctx = None
        if hasattr(self, "app") and hasattr(self.app, "batch_update"):
            try:
                batch_ctx = self.app.batch_update()
            except Exception:
                batch_ctx = None

        def _apply():
            try:
                self._move_table_cursor_noscroll(self.fixed_table, row=row)
            except Exception:
                pass
            try:
                local_col = max(0, min(self.sample_window_size - 1, col - self.sample_window_start)) if self.sample_window_size > 0 else 0
                self._move_table_cursor_noscroll(self.sample_table, row=row, column=local_col)
            except Exception:
                pass
            try:
                self.fixed_table.scroll_to(y=self._viewport_scroll_y, animate=False, force=True)
                self.sample_table.scroll_to(y=self._viewport_scroll_y, animate=False, force=True)
            except Exception:
                pass

        try:
            if batch_ctx is not None:
                with batch_ctx:
                    _apply()
            else:
                _apply()
        finally:
            self._is_internal_update = False

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

    def set_active_sample(
        self,
        global_col: int,
        force_center: bool = False,
        horizontal_align: Optional[str] = None,
    ) -> None:
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
        self._is_internal_update = True
        try:
            self._move_table_cursor_noscroll(self.sample_table, row=self.current_row_idx, column=local_col)
        except Exception:
            pass
        finally:
            self._is_internal_update = False

        if horizontal_align == "home":
            try:
                self.sample_table.scroll_to(x=0, animate=False, force=True)
            except Exception:
                pass
        elif horizontal_align == "end":
            try:
                max_x = getattr(self.sample_table, "max_scroll_x", None)
                if max_x is not None and max_x >= 0:
                    self.sample_table.scroll_to(x=max_x, animate=False, force=True)
                else:
                    self.sample_table.scroll_column_centered(local_col, force=True)
            except Exception:
                pass
        else:
            self.sample_table.scroll_column_centered(local_col, force=force_center)

        self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def fetch_more_rows(self, batch_size: int = 100) -> bool:
        """Dynamically appends more rows to both tables as user scrolls down."""
        if not self.reader or self._is_fetching_more or not self._is_main_stream_view:
            return False

        current_loaded = len(self.records)
        if self.total_records_count is not None and current_loaded >= self.total_records_count:
            return False

        self._is_fetching_more = True
        try:
            try:
                new_slice = self.reader.get_slice(current_loaded, batch_size, allow_placeholder=True)
            except TypeError:
                new_slice = self.reader.get_slice(current_loaded, batch_size)

            if not new_slice:
                if self.total_records_count is None:
                    self.total_records_count = current_loaded
                return False

            cols_fixed = self._get_fixed_columns()
            visible_samples = self.get_visible_samples()

            batch_ctx = None
            if hasattr(self, "app") and hasattr(self.app, "batch_update"):
                try:
                    batch_ctx = self.app.batch_update()
                except Exception:
                    batch_ctx = None

            def _append():
                existing_rows = getattr(self.fixed_table, "row_count", 0)
                for r in new_slice:
                    r_idx = len(self.records)
                    self.records.append(r)
                    row_key = f"row_{r_idx}"

                    if r_idx < existing_rows:
                        self._update_fixed_row_cells(row_key, r)
                        self._update_sample_row_cells(row_key, r)
                        continue

                    # Fixed table row
                    cells_dict = self._get_fixed_row_cells(r)
                    row_cells_fixed = [cells_dict[f"f_{col}"] for col in cols_fixed]
                    self.fixed_table.add_row(*row_cells_fixed, key=row_key)

                    # Sample table row
                    samples_loaded = getattr(r, "samples_loaded", True)
                    row_cells_sample = []
                    for s in visible_samples:
                        if not samples_loaded:
                            row_cells_sample.append(Text("...", style="dim bright_black"))
                        else:
                            s_dict = r.sample_data.get(s, {})
                            cell_val = str(s_dict.get(self.format_tag, "."))
                            row_cells_sample.append(self._style_sample_cell(cell_val, self.format_tag))
                    self.sample_table.add_row(*row_cells_sample, key=row_key)

            if batch_ctx is not None:
                with batch_ctx:
                    _append()
            else:
                _append()

            if len(new_slice) < batch_size and self.total_records_count is None:
                self.total_records_count = len(self.records)

            # Re-align both tables to authoritative vertical scroll offset
            try:
                self.fixed_table.scroll_to(y=self._viewport_scroll_y, animate=False, force=True)
                self.sample_table.scroll_to(y=self._viewport_scroll_y, animate=False, force=True)
            except Exception:
                pass

            return True
        finally:
            self._is_fetching_more = False

    def hydrate_rows(self, row_indices: List[int]) -> None:
        """Update placeholder sample cells in place when Handle 2 hydrates sample payloads."""
        if not self.reader or not self._is_main_stream_view:
            return
        if not hasattr(self.reader, "get_hydrated_record"):
            return

        updated_current = False
        batch_ctx = None
        if hasattr(self, "app") and hasattr(self.app, "batch_update"):
            try:
                batch_ctx = self.app.batch_update()
            except Exception:
                batch_ctx = None

        def _update_cells():
            nonlocal updated_current
            for idx in row_indices:
                if 0 <= idx < len(self.records):
                    hydrated = self.reader.get_hydrated_record(idx)
                    if hydrated is not None and getattr(hydrated, "samples_loaded", False):
                        self.records[idx] = hydrated
                        self._update_sample_row_cells(f"row_{idx}", hydrated)
                        if idx == self.current_row_idx:
                            updated_current = True

        if batch_ctx is not None:
            with batch_ctx:
                _update_cells()
        else:
            _update_cells()

        if updated_current and 0 <= self.current_row_idx < len(self.records):
            self._last_notified = None
            self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def can_advance_row(self, forward: bool) -> bool:
        if forward:
            if self.total_records_count is not None:
                return self.current_row_idx < self.total_records_count - 1
            return True
        return self.current_row_idx > 0

    def advance_row(self, forward: bool) -> None:
        """Advance cursor by 1 row across continuously loaded rows without snapback."""
        self.navigate_rows(1 if forward else -1)

    def set_active_row(self, target_row: int, sync_fixed: bool = True, sync_sample: bool = True) -> None:
        """Sets active variant row and commands both tables' cursor and vertical scroll in lockstep."""
        if target_row < 0:
            target_row = 0
        if self.total_records_count is not None and target_row >= self.total_records_count:
            target_row = max(0, self.total_records_count - 1)

        if self.reader and self._is_main_stream_view and hasattr(self.reader, "set_focus_row"):
            self.reader.set_focus_row(target_row)

        while self._is_main_stream_view and len(self.records) <= target_row + 25:
            needed = max(100, target_row - len(self.records) + 50)
            if not self.fetch_more_rows(needed):
                break

        if target_row >= len(self.records):
            target_row = max(0, len(self.records) - 1)

        self.current_row_idx = target_row

        # Compute authoritative shared vertical scroll offset only if target_row leaves visible viewport
        visible_rows = self._get_visible_row_count()
        target_y = self._viewport_scroll_y
        if target_row < target_y:
            target_y = target_row
        elif target_row >= target_y + visible_rows:
            target_y = target_row - visible_rows + 1
        max_y = self._get_max_scroll_y()
        target_y = max(0, min(max_y, target_y))
        self._viewport_scroll_y = target_y

        self._is_internal_update = True
        batch_ctx = None
        if hasattr(self, "app") and hasattr(self.app, "batch_update"):
            try:
                batch_ctx = self.app.batch_update()
            except Exception:
                batch_ctx = None

        def _apply():
            if sync_fixed and getattr(self.fixed_table, "row_count", 0) > target_row:
                try:
                    self._move_table_cursor_noscroll(self.fixed_table, row=target_row)
                except Exception:
                    pass

            if sync_sample and getattr(self.sample_table, "row_count", 0) > target_row:
                try:
                    local_col = max(0, min(self.sample_window_size - 1, self.current_sample_idx - self.sample_window_start)) if self.sample_window_size > 0 else 0
                    self._move_table_cursor_noscroll(self.sample_table, row=target_row, column=local_col)
                except Exception:
                    pass

            try:
                self.fixed_table.scroll_to(y=target_y, animate=False, force=True)
                self.sample_table.scroll_to(y=target_y, animate=False, force=True)
            except Exception:
                pass

        try:
            if batch_ctx is not None:
                with batch_ctx:
                    _apply()
            else:
                _apply()
        finally:
            self._is_internal_update = False

        self._notify_selection(target_row, self.current_sample_idx)

    def request_scroll_shift(self, forward: bool = True, step: int = 40) -> None:
        """Backward-compatible helper: appends more rows when scrolling forward."""
        if forward:
            self.fetch_more_rows(max(100, step * 2))

    def shift_buffer(self, new_start: int, target_cursor_row: Optional[int] = None) -> None:
        """Backward-compatible helper: ensures records are loaded up to target."""
        target = new_start + (target_cursor_row if target_cursor_row is not None else 0)
        self.set_active_row(target)

    def _apply_buffer_slice(self, new_start: int, target_global: int) -> None:
        """Backward-compatible helper: loads rows up to target_global and sets cursor."""
        self.set_active_row(target_global)

    def jump_to_region(self, chrom: str, pos: int) -> bool:
        """Seek and center table directly on target genomic coordinates."""
        if not self.reader:
            return False

        records = self.reader.query_region(chrom, pos, pos + 500000, limit=self.window_size)
        if not records:
            records = self.reader.query_region(chrom, max(0, pos - 100000), pos + 100000, limit=self.window_size)

        if records:
            self.set_records(records, is_main_stream=False)
            return True
        return False

    def compose(self):
        with Horizontal(id="split_container"):
            yield self.fixed_table
            yield self.divider
            yield self.sample_table

    def on_mount(self):
        self.rebuild_tables()
        try:
            self.focus()
        except Exception:
            pass

    def set_records(self, records: List[VariantRecord], is_main_stream: bool = False):
        self._is_main_stream_view = is_main_stream
        self.records = list(records)
        self.current_row_idx = 0
        self.buffer_start = 0
        self._viewport_scroll_y = 0
        if is_main_stream and self.reader:
            if hasattr(self.reader, "get_total_variants_async") and self.reader.get_total_variants_async() is not None:
                self.total_records_count = self.reader.get_total_variants_async()
            elif hasattr(self.reader, "total_variants_ready") and self.reader.total_variants_ready:
                self.total_records_count = self.reader.total_variants
            else:
                self.total_records_count = None
        else:
            self.total_records_count = len(self.records)
        self._ensure_row_capacity()
        self._update_all_rows_in_place()
        self._command_tables_scroll_y(0)
        self._last_notified = None
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
        samples_loaded = getattr(r, "samples_loaded", True)
        for j, s in enumerate(visible):
            col_k = f"col_{j}"
            if not samples_loaded:
                styled = Text("...", style="dim bright_black")
            else:
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
            samples_loaded = getattr(r, "samples_loaded", True)
            row_cells = []
            for s in visible:
                if not samples_loaded:
                    row_cells.append(Text("...", style="dim bright_black"))
                else:
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
        """Dynamically fetch more rows when cursor approaches bottom edge."""
        if not self.reader or self._is_fetching_more or self._rebuilding:
            return
        buffer_len = len(self.records)
        if target_row >= buffer_len - 25:
            self.fetch_more_rows(100)

    def _check_sample_window_boundary(self, local_col: int) -> None:
        """Backward compatibility stub for horizontal sample navigation."""
        pass

    # Click-only highlight sync (delayed programmatic move_cursor echoes are ignored)
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._rebuilding or self._is_fetching_more or self._is_internal_update:
            return
        if not self._accept_next_highlight:
            return
        self._disarm_click_sync()
        if event.data_table.id == "fixed_table":
            target_row = event.cursor_row
            self.set_active_row(target_row, sync_fixed=False, sync_sample=True)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if self._rebuilding or self._is_fetching_more or self._is_internal_update:
            return
        if not self._accept_next_highlight:
            return
        self._disarm_click_sync()
        if event.data_table.id == "sample_table":
            target_row = event.coordinate.row
            local_col = event.coordinate.column
            global_col = self.sample_window_start + local_col
            self.current_sample_idx = global_col
            self.sample_table.scroll_column_centered(local_col, force=False)
            self.set_active_row(target_row, sync_fixed=True, sync_sample=False)

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
            self.post_message(self.VariantSelected(rec, sample_id, row_index=row_idx))
