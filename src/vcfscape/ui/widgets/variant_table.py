"""
Central Variant Split Table for VCFscape powered by textual-fastdatatable.
Provides a true vertical split between:
1. FixedVariantTable (passive FastDataTable backed by FixedArrowBuffer)
2. Vertical divider (1ch │)
3. SampleMatrixTable (passive FastDataTable backed by SampleArrowBuffer across all samples)
With VariantSplitView as the top-level focused widget capturing Up/Down/PageUp/PageDown/
Left/Right/Home/End keys and mouse wheel events to command both child tables in lockstep.
"""

from __future__ import annotations

import dataclasses
from functools import cached_property
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple
from textual import events, on
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text

try:
    from textual_fastdatatable import DataTable as FastDataTable
except ImportError:
    from textual_fastdatatable import FastDataTable  # type: ignore

try:
    from textual_fastdatatable import ArrowBackend
except ImportError:
    try:
        from textual_fastdatatable.backends.arrow import ArrowBackend
    except ImportError:
        from textual_fastdatatable.backend import ArrowBackend  # type: ignore

from vcfscape.core.vcf_reader import VariantRecord
from vcfscape.core.arrow_buffer import (
    FixedArrowBuffer,
    SampleArrowBuffer,
    HAS_PYARROW,
    HAS_FASTDATATABLE,
)


class StyledArrowBackend(ArrowBackend):
    """
    ArrowBackend extension supporting:
    - Lazy viewport-only Rich Text styling on visible cells/rows.
    - Optional live row/cell providers so background sample hydration updates cells
      in place without calling set_backend() or disturbing cursor/scroll state.
    """

    def __init__(
        self,
        table: Any,
        row_styler: Optional[Callable[[int, List[Any]], List[Any]]] = None,
        cell_styler: Optional[Callable[[int, int, Any], Any]] = None,
        live_row_provider: Optional[Callable[[int], List[Any]]] = None,
        live_cell_provider: Optional[Callable[[int, int], Any]] = None,
    ):
        super().__init__(table)
        self.pa_table = table
        self._row_styler = row_styler
        self._cell_styler = cell_styler
        self._live_row_provider = live_row_provider
        self._live_cell_provider = live_cell_provider

    def get_row_at(self, row: int) -> List[Any]:
        if self._live_row_provider is not None:
            values = self._live_row_provider(row)
        else:
            values = list(super().get_row_at(row))
        if self._row_styler is not None:
            return self._row_styler(row, values)
        return values

    def get_cell_at(self, row: int, column: int) -> Any:
        if self._live_cell_provider is not None:
            val = self._live_cell_provider(row, column)
        elif hasattr(super(), "get_cell_at"):
            val = super().get_cell_at(row, column)
        else:
            val = super().get_row_at(row)[column]
        if self._cell_styler is not None:
            return self._cell_styler(row, column, val)
        if self._row_styler is not None:
            styled = self._row_styler(row, self.get_row_at(row) if self._live_row_provider else list(super().get_row_at(row)))
            if 0 <= column < len(styled):
                return styled[column]
        return val


def _clear_table_render_caches(table: FastDataTable) -> None:
    """Clear lightweight render/line caches on a FastDataTable before repainting."""
    for cache_attr in (
        "_row_cache",
        "_line_cache",
        "_row_render_cache",
        "_cell_render_cache",
        "_styled_cell_cache",
        "_updated_cells",
    ):
        cache_obj = getattr(table, cache_attr, None)
        if hasattr(cache_obj, "clear"):
            try:
                cache_obj.clear()
            except Exception:
                pass


def _apply_arrow_backend_to_table(
    table: FastDataTable,
    new_backend: Any,
    column_labels: Optional[List[str]] = None,
) -> None:
    """Bind an ArrowBackend when schema or row count changes (never used during hydration)."""
    if new_backend is None:
        return
    sv = getattr(table, "split_view", None)
    if getattr(sv, "_split_view_closing", False):
        return

    if hasattr(table, "set_backend"):
        table.set_backend(new_backend)
        return

    if column_labels is None:
        pa_tbl = getattr(new_backend, "pa_table", None) or getattr(new_backend, "source", None)
        if pa_tbl is not None and hasattr(pa_tbl, "column_names"):
            column_labels = list(pa_tbl.column_names)

    table.backend = new_backend
    if column_labels is not None and getattr(table, "_column_labels", None) is not None:
        table._column_labels = list(column_labels)

    for cls in type(table).__mro__:
        for prop_name, prop_obj in cls.__dict__.items():
            if isinstance(prop_obj, cached_property):
                table.__dict__.pop(prop_name, None)

    _clear_table_render_caches(table)
    try:
        table.refresh(layout=True)
    except Exception:
        pass


class _PassiveSplitTable(FastDataTable):
    """Base passive FastDataTable delegating vertical wheel & keys to parent VariantSplitView."""

    can_focus = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.peer_table: Optional[FastDataTable] = None
        self.split_view: Optional["VariantSplitView"] = None

    def apply_arrow_backend(self, new_backend: Any, column_labels: Optional[List[str]] = None) -> None:
        _apply_arrow_backend_to_table(self, new_backend, column_labels=column_labels)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        event.stop()

    def on_enter(self, event: events.Enter) -> None:
        event.stop()

    def on_leave(self, event: events.Leave) -> None:
        event.stop()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self.split_view is not None:
            self.split_view._arm_click_sync()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        event.prevent_default()
        if self.split_view is not None:
            self.split_view.handle_mouse_scroll(delta=3)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        event.prevent_default()
        if self.split_view is not None:
            self.split_view.handle_mouse_scroll(delta=-3)

    def on_key(self, event: events.Key) -> None:
        if self.split_view is not None and self.split_view.handle_navigation_key(event.key):
            event.stop()
            event.prevent_default()


class FixedVariantTable(_PassiveSplitTable):
    """Left anchored passive FastDataTable displaying variant metadata columns."""

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.stop()
        event.prevent_default()

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.stop()
        event.prevent_default()


class SampleMatrixTable(_PassiveSplitTable):
    """Right horizontally scrollable passive FastDataTable displaying sample cells."""
    pass


class VariantSplitView(Horizontal):
    """
    Top-level Split Table Controller backed by Dual PyArrow ArrowBackends:
    - Holds focus (`can_focus=True`) and captures Up/Down/PageUp/PageDown/Left/Right/Home/End
      plus vertical mouse wheel events, commanding both passive FastDataTables in lockstep.
    - Background hydration repaints SampleMatrixTable in place via live StyledArrowBackend
      providers without replacing table.backend or resetting cursor/scroll offsets.
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
    }

    #fixed_table {
        height: 100%;
        background: #0b0f17;
        scrollbar-size-vertical: 0;
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
        self.records = list(records)
        self.samples = list(samples)
        self._is_internal_update = False
        self._accept_next_highlight = False
        self._split_view_closing = False
        self._click_timer: Optional[Any] = None
        self.current_row_idx = 0
        self.current_sample_idx = 0
        self._viewport_scroll_y = 0
        self._last_notified: Optional[Tuple[int, int]] = None

        self.window_size = 150
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

        self.fixed_buffer = FixedArrowBuffer(self.records)
        self.sample_buffer = SampleArrowBuffer(samples=self.samples, records=self.records)

        fixed_backend = self._build_fixed_arrow_backend(self.view_mode)
        sample_backend = self._build_sample_arrow_backend(self.format_tag)

        self.fixed_table = FixedVariantTable(
            id="fixed_table",
            backend=fixed_backend,
            cursor_type="row",
            zebra_stripes=True,
            show_row_labels=False,
            show_cursor=True,
            null_rep=".",
        )
        self.fixed_table.styles.width = self.FIXED_WIDTHS.get(self.view_mode, 56)

        self.divider = Static("│", id="table_divider")
        self.divider.styles.width = 1
        self.divider.styles.min_width = 1
        self.divider.styles.max_width = 1
        self.divider.styles.height = "100%"

        self.sample_table = SampleMatrixTable(
            id="sample_table",
            backend=sample_backend,
            cursor_type="cell",
            zebra_stripes=True,
            show_row_labels=False,
            show_cursor=True,
            null_rep="...",
        )
        self.sample_table.styles.width = "1fr"
        self.sample_table.styles.height = "100%"

        self.fixed_table.peer_table = self.sample_table
        self.sample_table.peer_table = self.fixed_table
        self.fixed_table.split_view = self
        self.sample_table.split_view = self

    def compose(self):
        yield self.fixed_table
        yield self.divider
        yield self.sample_table

    def on_mount(self):
        if getattr(self.fixed_table, "backend", None) is None or getattr(self.sample_table, "backend", None) is None:
            self.rebuild_tables()
        else:
            self._notify_selection(self.current_row_idx, self.current_sample_idx)
        try:
            self.focus()
        except Exception:
            pass

    def _style_fixed_cell_value(self, row_idx: int, col_idx: int, val: Any) -> Any:
        cols = self._get_fixed_columns()
        col_name = cols[col_idx] if 0 <= col_idx < len(cols) else ""
        sval = "." if val is None else str(val)
        if col_name == "FILTER":
            return Text(sval, style="green" if sval == "PASS" else "red")
        if col_name == "GENE":
            rec = self.records[row_idx] if 0 <= row_idx < len(self.records) else None
            is_drug = bool(rec and rec.drug_annotation)
            return Text(sval, style="bold yellow" if is_drug else "white")
        return sval

    def _style_fixed_row_values(self, row_idx: int, values: List[Any]) -> List[Any]:
        cols = self._get_fixed_columns()
        rec = self.records[row_idx] if 0 <= row_idx < len(self.records) else None
        styled: List[Any] = []
        for col_name, val in zip(cols, values):
            sval = "." if val is None else str(val)
            if col_name == "FILTER":
                styled.append(Text(sval, style="green" if sval == "PASS" else "red"))
            elif col_name == "GENE":
                is_drug = bool(rec and rec.drug_annotation)
                styled.append(Text(sval, style="bold yellow" if is_drug else "white"))
            else:
                styled.append(sval)
        return styled

    def _style_sample_cell(self, val: str, tag: str) -> Text:
        if tag == "GT":
            if val in ("0/0", "0|0", "0"):
                return Text(val, style="dim white")
            if val in ("./.", ".", "..."):
                return Text(val, style="dim bright_black")
            if "/" in val:
                parts = val.split("/")
                if len(set(parts)) > 1:
                    return Text(val, style="bold bright_magenta")
                return Text(val, style="bold bright_cyan")
            return Text(val, style="bold bright_cyan")
        if tag == "DP":
            if val == "...":
                return Text(val, style="dim bright_black")
            try:
                dp = int(val)
                if dp < 15:
                    return Text(val, style="red")
                if dp < 40:
                    return Text(val, style="yellow")
                return Text(val, style="green")
            except ValueError:
                return Text(val, style="dim")
        if tag == "AD":
            if val == "...":
                return Text(val, style="dim bright_black")
            return Text(val, style="bright_yellow")
        if tag == "GQ":
            if val == "...":
                return Text(val, style="dim bright_black")
            try:
                gq = int(val)
                return Text(val, style="green" if gq >= 80 else "yellow")
            except ValueError:
                return Text(val, style="dim")
        return Text(val, style="white")

    def _live_sample_row(self, row_idx: int) -> List[Any]:
        return self.sample_buffer.get_row_values(row_idx, self.format_tag)

    def _live_sample_cell(self, row_idx: int, col_idx: int) -> Any:
        return self.sample_buffer.get_cell_value(row_idx, col_idx, self.format_tag)

    def _style_sample_cell_value(self, row_idx: int, _col_idx: int, val: Any) -> Any:
        rec = self.records[row_idx] if 0 <= row_idx < len(self.records) else None
        if rec is not None and not getattr(rec, "samples_loaded", True):
            return Text("...", style="dim bright_black")
        return self._style_sample_cell("." if val is None else str(val), self.format_tag)

    def _style_sample_row_values(self, row_idx: int, values: List[Any]) -> List[Any]:
        rec = self.records[row_idx] if 0 <= row_idx < len(self.records) else None
        if rec is not None and not getattr(rec, "samples_loaded", True):
            return [Text("...", style="dim bright_black") for _ in values]
        tag = self.format_tag
        return [self._style_sample_cell("." if v is None else str(v), tag) for v in values]

    def _build_fixed_arrow_backend(self, view_mode: str) -> Optional[Any]:
        if not (HAS_PYARROW and HAS_FASTDATATABLE):
            return None
        pa_tbl = self.fixed_buffer.get_arrow_table(view_mode)
        if pa_tbl is None:
            return None
        return StyledArrowBackend(
            pa_tbl,
            row_styler=self._style_fixed_row_values,
            cell_styler=self._style_fixed_cell_value,
        )

    def _build_sample_arrow_backend(self, format_tag: str) -> Optional[Any]:
        if not (HAS_PYARROW and HAS_FASTDATATABLE):
            return None
        pa_tbl = self.sample_buffer.get_arrow_table(format_tag)
        if pa_tbl is None:
            return None
        return StyledArrowBackend(
            pa_tbl,
            row_styler=self._style_sample_row_values,
            cell_styler=self._style_sample_cell_value,
            live_row_provider=self._live_sample_row,
            live_cell_provider=self._live_sample_cell,
        )

    def _get_fixed_columns(self) -> List[str]:
        return self.fixed_buffer.get_columns_for_mode(self.view_mode)

    def get_visible_samples(self) -> List[str]:
        return list(self.samples)

    def _refresh_fixed_backend(self) -> None:
        self.fixed_table.styles.width = self.FIXED_WIDTHS.get(self.view_mode, 56)
        backend = self._build_fixed_arrow_backend(self.view_mode)
        self.fixed_table.apply_arrow_backend(backend, column_labels=self._get_fixed_columns())

    def _refresh_sample_backend(self) -> None:
        backend = self._build_sample_arrow_backend(self.format_tag)
        sample_cols = self.samples if self.samples else ["Samples"]
        self.sample_table.apply_arrow_backend(backend, column_labels=sample_cols)

    def update_total_variants(self, count: int) -> None:
        self.total_records_count = count

    def on_mouse_move(self, event: events.MouseMove) -> None:
        event.stop()

    def _arm_click_sync(self) -> None:
        if self._split_view_closing:
            return
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

    def stop_timers(self) -> None:
        self._split_view_closing = True
        self._accept_next_highlight = False
        if self._click_timer is not None:
            try:
                self._click_timer.stop()
            except Exception:
                pass
            self._click_timer = None

    def on_unmount(self) -> None:
        self.stop_timers()

    def _disarm_click_sync(self) -> None:
        self._accept_next_highlight = False
        if self._click_timer is not None:
            try:
                self._click_timer.stop()
            except Exception:
                pass
            self._click_timer = None
        if not self._split_view_closing:
            try:
                self.focus()
            except Exception:
                pass

    def _get_visible_row_count(self) -> int:
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
        visible_rows = self._get_visible_row_count()
        return max(0, len(self.records) - visible_rows)

    def _move_table_cursor(
        self,
        table: FastDataTable,
        row: int,
        column: Optional[int] = None,
        scroll: bool = False,
    ) -> None:
        col = 0 if column is None else column
        try:
            if column is None:
                table.move_cursor(row=row, animate=False, scroll=scroll)
            else:
                table.move_cursor(row=row, column=col, animate=False, scroll=scroll)
        except TypeError:
            try:
                table.cursor_coordinate = Coordinate(row, col)
            except Exception:
                pass

    def _schedule_post_layout_scroll(
        self,
        target_y: int,
        target_x: Optional[float],
        cursor_row: int,
        cursor_col: int,
    ) -> None:
        """Restore exact scroll/cursor after FastDataTable completes a layout pass from row growth."""
        if self._split_view_closing:
            return
        try:
            app_obj = self.app
            if app_obj is None or getattr(app_obj, "_vcfscape_closing", False):
                return
        except Exception:
            return

        def _restore() -> None:
            if self._split_view_closing:
                return
            self._is_internal_update = True
            try:
                if self.records:
                    safe_row = max(0, min(len(self.records) - 1, cursor_row))
                    safe_col = max(0, min(len(self.samples) - 1, cursor_col)) if self.samples else 0
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                    self._move_table_cursor(self.sample_table, row=safe_row, column=safe_col, scroll=False)
                clamped_y = max(0, min(self._get_max_scroll_y(), target_y))
                self._viewport_scroll_y = clamped_y
                self.fixed_table.scroll_to(y=clamped_y, animate=False, force=True)
                if target_x is not None:
                    self.sample_table.scroll_to(x=target_x, y=clamped_y, animate=False, force=True)
                else:
                    self.sample_table.scroll_to(y=clamped_y, animate=False, force=True)
            except Exception:
                pass
            finally:
                self._is_internal_update = False

        try:
            self.call_after_refresh(_restore)
        except Exception:
            pass

    def _command_tables_scroll_y(self, target_y: int) -> None:
        """Scroll both FixedVariantTable and SampleMatrixTable to the exact same vertical offset."""
        max_y = self._get_max_scroll_y()
        clamped_y = max(0, min(max_y, int(target_y)))
        self._viewport_scroll_y = clamped_y

        def _apply():
            saved_x = getattr(self.sample_table, "scroll_x", 0)
            try:
                self.fixed_table.scroll_to(y=clamped_y, animate=False, force=True)
            except Exception:
                pass
            try:
                self.sample_table.scroll_to(x=saved_x, y=clamped_y, animate=False, force=True)
            except Exception:
                pass

        self._run_batched(_apply)

    def _run_batched(self, fn: Callable[[], None]) -> None:
        batch_ctx = None
        try:
            app_obj = self.app
            if app_obj is not None and hasattr(app_obj, "batch_update"):
                batch_ctx = app_obj.batch_update()
        except Exception:
            batch_ctx = None
        if batch_ctx is not None:
            with batch_ctx:
                fn()
        else:
            fn()

    def _request_viewport_hydration(self, start_row: int) -> None:
        """Ask Handle 2 to hydrate only rows near the active visible viewport."""
        if not self.reader or not self.samples or not self._is_main_stream_view:
            return
        if not hasattr(self.reader, "request_sample_hydration"):
            return
        visible_rows = self._get_visible_row_count()
        win_start = max(0, start_row - 10)
        win_end = min(len(self.records), start_row + visible_rows + 20)
        has_unhydrated = any(
            not getattr(self.records[i], "samples_loaded", True)
            for i in range(win_start, win_end)
        )
        if has_unhydrated:
            self.reader.request_sample_hydration(win_start, max(1, win_end - win_start))

    # --- Top-Widget Keyboard & Mouse Wheel Capture ---

    def on_key(self, event: events.Key) -> None:
        if self.handle_navigation_key(event.key):
            event.stop()
            event.prevent_default()

    def handle_navigation_key(self, key: str) -> bool:
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
        """Scroll ONLY the vertical viewport of both tables in lockstep without moving cursor."""
        if not self.records:
            return
        visible_rows = self._get_visible_row_count()
        target_y = max(0, self._viewport_scroll_y + delta)

        did_fetch = False
        if delta > 0 and self._is_main_stream_view:
            while target_y + visible_rows >= len(self.records) - 15:
                if not self.fetch_more_rows(100):
                    break
                did_fetch = True

        self._command_tables_scroll_y(target_y)
        if did_fetch:
            safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
            self._schedule_post_layout_scroll(
                target_y=self._viewport_scroll_y,
                target_x=getattr(self.sample_table, "scroll_x", 0),
                cursor_row=self.current_row_idx,
                cursor_col=safe_col,
            )
        self._request_viewport_hydration(self._viewport_scroll_y)

    # --- Vertical & Horizontal Navigation ---

    def navigate_rows(self, delta: int) -> None:
        if not self.records:
            return
        target = self.current_row_idx + delta
        if delta > 0 and self.total_records_count is not None and target >= self.total_records_count:
            target = max(0, self.total_records_count - 1)
        if target < 0:
            target = 0
        self.set_active_row(target, sync_fixed=True, sync_sample=True)

    def navigate_page(self, forward: bool, page_size: Optional[int] = None) -> None:
        step = page_size if page_size is not None else max(1, self._get_visible_row_count() - 1)
        self.navigate_rows(step if forward else -step)

    def can_advance_row(self, forward: bool) -> bool:
        if forward:
            if self.total_records_count is not None:
                return self.current_row_idx < self.total_records_count - 1
            return True
        return self.current_row_idx > 0

    def advance_row(self, forward: bool) -> None:
        self.navigate_rows(1 if forward else -1)

    def set_active_row(self, target_row: int, sync_fixed: bool = True, sync_sample: bool = True) -> None:
        if target_row < 0:
            target_row = 0
        if self.total_records_count is not None and target_row >= self.total_records_count:
            target_row = max(0, self.total_records_count - 1)

        if self.reader and self._is_main_stream_view and hasattr(self.reader, "set_focus_row"):
            self.reader.set_focus_row(target_row)

        did_fetch = False
        while self._is_main_stream_view and len(self.records) <= target_row + 25:
            needed = max(100, target_row - len(self.records) + 50)
            if not self.fetch_more_rows(needed):
                break
            did_fetch = True

        if target_row >= len(self.records):
            target_row = max(0, len(self.records) - 1)

        self.current_row_idx = target_row

        visible_rows = self._get_visible_row_count()
        target_y = self._viewport_scroll_y
        if target_row < target_y:
            target_y = target_row
        elif target_row >= target_y + visible_rows:
            target_y = target_row - visible_rows + 1
        target_y = max(0, min(self._get_max_scroll_y(), target_y))
        self._viewport_scroll_y = target_y

        self._request_viewport_hydration(target_y)

        self._is_internal_update = True
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
        saved_x = getattr(self.sample_table, "scroll_x", 0)

        def _apply():
            if sync_fixed and getattr(self.fixed_table, "row_count", 0) > target_row:
                self._move_table_cursor(self.fixed_table, row=target_row, scroll=False)
            if sync_sample and getattr(self.sample_table, "row_count", 0) > target_row:
                self._move_table_cursor(self.sample_table, row=target_row, column=safe_col, scroll=False)
            try:
                self.fixed_table.scroll_to(y=target_y, animate=False, force=True)
                self.sample_table.scroll_to(x=saved_x, y=target_y, animate=False, force=True)
            except Exception:
                pass

        try:
            self._run_batched(_apply)
        finally:
            self._is_internal_update = False

        if did_fetch:
            self._schedule_post_layout_scroll(
                target_y=target_y,
                target_x=saved_x,
                cursor_row=target_row,
                cursor_col=safe_col,
            )

        self._notify_selection(target_row, self.current_sample_idx)

    def can_advance_sample(self, forward: bool) -> bool:
        if not self.samples:
            return False
        return self.current_sample_idx < len(self.samples) - 1 if forward else self.current_sample_idx > 0

    def advance_sample(self, forward: bool) -> None:
        if not self.samples:
            return
        target = min(len(self.samples) - 1, self.current_sample_idx + 1) if forward else max(0, self.current_sample_idx - 1)
        if target != self.current_sample_idx:
            self.set_active_sample(target)

    def scroll_samples_home(self) -> None:
        if self.samples:
            self.set_active_sample(0, horizontal_align="home")

    def scroll_samples_end(self) -> None:
        if self.samples:
            self.set_active_sample(len(self.samples) - 1, horizontal_align="end")

    def set_active_sample(
        self,
        global_col: int,
        horizontal_align: Optional[str] = None,
    ) -> None:
        """Move sample cursor across native FastDataTable columns cleanly without clobbering scroll_x."""
        if not self.samples:
            return
        global_col = max(0, min(len(self.samples) - 1, global_col))
        self.current_sample_idx = global_col

        self._is_internal_update = True
        try:
            self._move_table_cursor(
                self.sample_table,
                row=self.current_row_idx,
                column=global_col,
                scroll=True,
            )
            if horizontal_align == "home":
                try:
                    self.sample_table.scroll_to(x=0, animate=False, force=True)
                except Exception:
                    pass
            elif horizontal_align == "end":
                try:
                    max_x = max(0, int(getattr(self.sample_table, "max_scroll_x", 0) or 0))
                    if max_x > 0:
                        self.sample_table.scroll_to(x=max_x, animate=False, force=True)
                except Exception:
                    pass
        finally:
            self._is_internal_update = False

        self._notify_selection(self.current_row_idx, self.current_sample_idx)

    # --- Data Loading, View Modes, and In-Place Hydration ---

    def fetch_more_rows(self, batch_size: int = 100) -> bool:
        """Dynamically append rows to both ArrowBackends without losing scroll or cursor."""
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

            self.records.extend(new_slice)
            self.fixed_buffer.append_records(new_slice)
            self.sample_buffer.append_records(new_slice)

            if len(new_slice) < batch_size and self.total_records_count is None:
                self.total_records_count = len(self.records)

            self._is_internal_update = True
            saved_x = getattr(self.sample_table, "scroll_x", 0)
            saved_y = self._viewport_scroll_y
            safe_row = min(self.current_row_idx, len(self.records) - 1) if self.records else 0
            safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0

            def _apply():
                self._refresh_fixed_backend()
                self._refresh_sample_backend()
                if self.records:
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                    self._move_table_cursor(self.sample_table, row=safe_row, column=safe_col, scroll=False)
                try:
                    self.fixed_table.scroll_to(y=saved_y, animate=False, force=True)
                    self.sample_table.scroll_to(x=saved_x, y=saved_y, animate=False, force=True)
                except Exception:
                    pass

            try:
                self._run_batched(_apply)
            finally:
                self._is_internal_update = False

            self._schedule_post_layout_scroll(
                target_y=saved_y,
                target_x=saved_x,
                cursor_row=safe_row,
                cursor_col=safe_col,
            )
            return True
        finally:
            self._is_fetching_more = False

    def hydrate_rows(self, row_indices: List[int]) -> None:
        """
        Repaint newly hydrated sample rows in place WITHOUT calling set_backend()
        so FastDataTable preserves cursor coordinates, scroll_x, scroll_y, and virtual_size.
        """
        if self._split_view_closing or not self.reader or not self._is_main_stream_view:
            return
        try:
            if getattr(self.app, "_vcfscape_closing", False):
                return
        except Exception:
            pass
        if not hasattr(self.reader, "get_hydrated_record"):
            return

        hydrated_map: Dict[int, VariantRecord] = {}
        updated_current = False
        for idx in row_indices:
            if 0 <= idx < len(self.records) and not self.sample_buffer.is_row_hydrated(idx):
                hydrated = self.reader.get_hydrated_record(idx)
                if hydrated is not None and getattr(hydrated, "samples_loaded", False):
                    self.records[idx] = hydrated
                    hydrated_map[idx] = hydrated
                    if idx == self.current_row_idx:
                        updated_current = True

        if not hydrated_map or self._split_view_closing:
            return

        if self.sample_buffer.hydrate_rows(list(hydrated_map.keys()), hydrated_map):
            _clear_table_render_caches(self.sample_table)
            try:
                self.sample_table.refresh()
            except Exception:
                pass

        if updated_current and not self._split_view_closing and 0 <= self.current_row_idx < len(self.records):
            self._last_notified = None
            self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def jump_to_region(self, chrom: str, pos: int) -> bool:
        if not self.reader:
            return False
        records = self.reader.query_region(chrom, pos, pos + 500000, limit=self.window_size)
        if not records:
            records = self.reader.query_region(chrom, max(0, pos - 100000), pos + 100000, limit=self.window_size)
        if records:
            self.set_records(records, is_main_stream=False)
            return True
        return False

    def set_records(self, records: List[VariantRecord], is_main_stream: bool = False):
        self._is_main_stream_view = is_main_stream
        self.records = list(records)
        self.current_row_idx = 0
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

        self.fixed_buffer.reset(self.records)
        self.sample_buffer.reset(self.records, samples=self.samples)
        self._is_internal_update = True
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
        try:
            self._refresh_fixed_backend()
            self._refresh_sample_backend()
            if self.records:
                self._move_table_cursor(self.fixed_table, row=0, scroll=False)
                self._move_table_cursor(self.sample_table, row=0, column=safe_col, scroll=False)
            self._command_tables_scroll_y(0)
        finally:
            self._is_internal_update = False

        self._schedule_post_layout_scroll(
            target_y=0,
            target_x=0,
            cursor_row=0,
            cursor_col=safe_col,
        )
        self._last_notified = None
        self._notify_selection(0, self.current_sample_idx)

    def set_view_mode(self, mode: str):
        self.view_mode = mode.lower()
        saved_y = self._viewport_scroll_y
        safe_row = min(self.current_row_idx, len(self.records) - 1) if self.records else 0
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
        self._is_internal_update = True
        try:
            self._refresh_fixed_backend()
            if self.records:
                self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
            self._command_tables_scroll_y(saved_y)
        finally:
            self._is_internal_update = False
        self._schedule_post_layout_scroll(
            target_y=saved_y,
            target_x=getattr(self.sample_table, "scroll_x", 0),
            cursor_row=safe_row,
            cursor_col=safe_col,
        )

    def set_format_tag(self, tag: str):
        self.format_tag = tag.upper()
        saved_x = getattr(self.sample_table, "scroll_x", 0)
        saved_y = self._viewport_scroll_y
        safe_row = min(self.current_row_idx, len(self.records) - 1) if self.records else 0
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
        _clear_table_render_caches(self.sample_table)
        try:
            self.sample_table.refresh()
        except Exception:
            pass
        if getattr(self.sample_table, "backend", None) is None:
            self._refresh_sample_backend()
        self._schedule_post_layout_scroll(
            target_y=saved_y,
            target_x=saved_x,
            cursor_row=safe_row,
            cursor_col=safe_col,
        )

    def cycle_view_mode(self) -> str:
        modes = ["normal", "compact", "essential", "raw"]
        curr_idx = modes.index(self.view_mode) if self.view_mode in modes else 0
        new_mode = modes[(curr_idx + 1) % len(modes)]
        self.set_view_mode(new_mode)
        return new_mode.capitalize()

    def rebuild_tables(self):
        self._rebuilding = True
        try:
            self._last_notified = None
            self._refresh_fixed_backend()
            self.sample_buffer.reset(self.records, samples=self.samples)
            self._refresh_sample_backend()
            self._notify_selection(self.current_row_idx, self.current_sample_idx)
        finally:
            self._rebuilding = False

    # --- Click-only selection sync (ignores programmatic cursor moves) ---

    @on(FastDataTable.RowHighlighted)
    def on_fast_data_table_row_highlighted(self, event: FastDataTable.RowHighlighted) -> None:
        if self._rebuilding or self._is_fetching_more or self._is_internal_update or not self._accept_next_highlight:
            return
        self._disarm_click_sync()
        tbl = getattr(event, "data_table", None) or getattr(event, "control", None)
        if tbl is not None and getattr(tbl, "id", None) == "fixed_table":
            target_row = getattr(event, "cursor_row", None)
            if target_row is None and hasattr(event, "coordinate"):
                target_row = event.coordinate.row
            if target_row is not None:
                self.set_active_row(int(target_row), sync_fixed=False, sync_sample=True)

    @on(FastDataTable.CellHighlighted)
    def on_fast_data_table_cell_highlighted(self, event: FastDataTable.CellHighlighted) -> None:
        if self._rebuilding or self._is_fetching_more or self._is_internal_update or not self._accept_next_highlight:
            return
        self._disarm_click_sync()
        tbl = getattr(event, "data_table", None) or getattr(event, "control", None)
        if tbl is not None and getattr(tbl, "id", None) == "sample_table":
            target_row = event.coordinate.row
            self.current_sample_idx = event.coordinate.column
            self.set_active_row(target_row, sync_fixed=True, sync_sample=False)

    def _notify_selection(self, row_idx: int, sample_col_idx: int) -> None:
        if self._split_view_closing:
            return
        if 0 <= row_idx < len(self.records):
            coord = (row_idx, sample_col_idx)
            if self._last_notified == coord:
                return
            self._last_notified = coord
            rec = self.records[row_idx]
            sample_id = self.samples[sample_col_idx] if 0 <= sample_col_idx < len(self.samples) else None
            self.post_message(self.VariantSelected(rec, sample_id, row_index=row_idx))
