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
from textual.geometry import Size
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
    ArrowBackend extension applying lazy viewport-only Rich Text styling on visible cells/rows.
    Keeps underlying storage columnar in PyArrow.
    """

    def __init__(
        self,
        table: Any,
        row_styler: Optional[Callable[[int, List[Any]], List[Any]]] = None,
        cell_styler: Optional[Callable[[int, int, Any], Any]] = None,
    ):
        super().__init__(table)
        self.pa_table = table
        self._row_styler = row_styler
        self._cell_styler = cell_styler

    def get_row_at(self, row: int) -> List[Any]:
        values = super().get_row_at(row)
        if self._row_styler is not None:
            return self._row_styler(row, list(values))
        return list(values)

    def get_cell_at(self, row: int, column: int) -> Any:
        if hasattr(super(), "get_cell_at"):
            val = super().get_cell_at(row, column)
        else:
            val = super().get_row_at(row)[column]
        if self._cell_styler is not None:
            return self._cell_styler(row, column, val)
        if self._row_styler is not None:
            styled = self._row_styler(row, list(super().get_row_at(row)))
            if 0 <= column < len(styled):
                return styled[column]
        return val


def _estimate_column_widths(backend: Any, column_labels: List[str]) -> List[int]:
    """Estimate column content widths from the first few Arrow rows."""
    widths = [max(1, len(lbl)) for lbl in column_labels]
    row_count = int(getattr(backend, "row_count", 0))
    pa_tbl = getattr(backend, "pa_table", None) or getattr(backend, "source", None)
    sample_rows = min(60, row_count)
    if pa_tbl is not None and sample_rows > 0:
        try:
            for col_idx in range(min(len(widths), pa_tbl.num_columns)):
                col_arr = pa_tbl.column(col_idx)
                for r in range(sample_rows):
                    val = col_arr[r].as_py()
                    if val is not None:
                        s_len = len(str(val))
                        if s_len > widths[col_idx]:
                            widths[col_idx] = s_len
            return widths
        except Exception:
            pass
    return widths


def _rebuild_table_columns(table: FastDataTable, new_backend: Any, column_labels: List[str]) -> None:
    """Update FastDataTable columns dict cleanly when fixed view-mode schema changes."""
    cols_obj = getattr(table, "columns", None)
    if not isinstance(cols_obj, dict) or not cols_obj:
        return

    sample_key = next(iter(cols_obj.keys()), None)
    sample_col = next(iter(cols_obj.values()), None)
    if sample_col is None:
        return

    KeyCls = type(sample_key) if sample_key is not None else None
    ColCls = type(sample_col)
    widths = _estimate_column_widths(new_backend, column_labels)

    new_keys: List[Any] = []
    new_cols_dict: Dict[Any, Any] = {}
    is_dc = dataclasses.is_dataclass(sample_col)
    dc_fields = {f.name for f in dataclasses.fields(sample_col)} if is_dc else set()

    for idx, lbl in enumerate(column_labels):
        col_key = KeyCls(lbl) if KeyCls is not None else lbl
        col_w = widths[idx] if idx < len(widths) else max(4, len(lbl))
        if is_dc:
            repl_kwargs: Dict[str, Any] = {}
            if "key" in dc_fields:
                repl_kwargs["key"] = col_key
            if "label" in dc_fields:
                repl_kwargs["label"] = Text(lbl)
            if "content_width" in dc_fields:
                repl_kwargs["content_width"] = col_w
            if "auto_width" in dc_fields:
                repl_kwargs["auto_width"] = True
                if "width" in dc_fields:
                    repl_kwargs["width"] = 0
            elif "width" in dc_fields:
                repl_kwargs["width"] = col_w
            new_col = dataclasses.replace(sample_col, **repl_kwargs)
        else:
            new_col = ColCls(key=col_key, label=Text(lbl), width=0, content_width=col_w, auto_width=True)
        new_keys.append(col_key)
        new_cols_dict[col_key] = new_col

    cols_obj.clear()
    cols_obj.update(new_cols_dict)

    locs = getattr(table, "_column_locations", None)
    if isinstance(locs, dict):
        locs.clear()
        for idx, k in enumerate(new_keys):
            locs[k] = idx

    if isinstance(getattr(table, "_ordered_columns", None), list):
        table._ordered_columns = [new_cols_dict[k] for k in new_keys]
    if isinstance(getattr(table, "_ordered_column_keys", None), list):
        table._ordered_column_keys = list(new_keys)


def _invoke_optional(fn: Any) -> None:
    if not callable(fn):
        return
    try:
        sig = inspect.signature(fn)
        required = [
            p for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if not required:
            fn()
        elif len(required) == 1:
            fn(())
    except Exception:
        pass


def _apply_arrow_backend_to_table(
    table: FastDataTable,
    new_backend: Any,
    column_labels: Optional[List[str]] = None,
) -> None:
    """Swap buffered ArrowBackend safely on a FastDataTable without corrupting internal layout state."""
    if new_backend is None:
        return
    sv = getattr(table, "split_view", None)
    if getattr(sv, "_split_view_closing", False):
        return

    if column_labels is None:
        pa_tbl = getattr(new_backend, "pa_table", None) or getattr(new_backend, "source", None)
        if pa_tbl is not None and hasattr(pa_tbl, "column_names"):
            column_labels = list(pa_tbl.column_names)

    used_native_setter = False
    if hasattr(table, "set_backend"):
        table.set_backend(new_backend)
        used_native_setter = True
    else:
        try:
            ordered = getattr(table, "ordered_columns", None)
        except Exception:
            ordered = None
        if ordered is not None:
            cur_labels = [str(getattr(c, "label", c)) for c in ordered]
        elif isinstance(getattr(table, "columns", None), dict):
            cur_labels = [str(getattr(c, "label", c)) for c in table.columns.values()]
        else:
            cur_labels = []

        table.backend = new_backend

        if column_labels is not None and cur_labels != column_labels:
            if getattr(table, "_column_labels", None) is not None:
                table._column_labels = list(column_labels)
            _rebuild_table_columns(table, new_backend, column_labels)

        for cls in type(table).__mro__:
            for prop_name, prop_obj in cls.__dict__.items():
                if isinstance(prop_obj, cached_property):
                    table.__dict__.pop(prop_name, None)

        for cache_attr in (
            "_row_cache",
            "_line_cache",
            "_row_render_cache",
            "_cell_render_cache",
            "_cell_widths",
            "_styled_cell_cache",
            "_updated_cells",
        ):
            cache_obj = getattr(table, cache_attr, None)
            if hasattr(cache_obj, "clear"):
                cache_obj.clear()

        for method_name in (
            "_reset_render_caches",
            "_clear_caches",
            "_update_column_widths",
            "_update_dimensions",
        ):
            _invoke_optional(getattr(table, method_name, None))

    new_row_count = int(getattr(new_backend, "row_count", 0))
    new_col_count = int(getattr(new_backend, "column_count", len(column_labels or [])))

    coord = getattr(table, "cursor_coordinate", None)
    if coord is not None and new_row_count > 0 and new_col_count > 0:
        safe_r = max(0, min(new_row_count - 1, coord.row))
        safe_c = max(0, min(new_col_count - 1, coord.column))
        if safe_r != coord.row or safe_c != coord.column:
            try:
                table.cursor_coordinate = Coordinate(safe_r, safe_c)
            except Exception:
                pass

    if not used_native_setter:
        try:
            table.refresh()
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
    - Mouse wheel scrolls only the vertical viewport without moving the active row cursor.
    - Home/End scroll horizontally to the first/last sample column without changing vertical position.
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

        # Dual Buffered PyArrow Backends (all samples exposed natively to SampleMatrixTable)
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
        self.stop_timers()
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

        if delta > 0 and self._is_main_stream_view:
            while target_y + visible_rows >= len(self.records) - 15:
                if not self.fetch_more_rows(100):
                    break

        self._command_tables_scroll_y(target_y)
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

        while self._is_main_stream_view and len(self.records) <= target_row + 25:
            needed = max(100, target_row - len(self.records) + 50)
            if not self.fetch_more_rows(needed):
                break

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
        """Move sample cursor across native FastDataTable columns while preserving vertical scroll."""
        if not self.samples:
            return
        global_col = max(0, min(len(self.samples) - 1, global_col))
        self.current_sample_idx = global_col

        self._is_internal_update = True
        try:
            use_native_scroll = horizontal_align is None
            self._move_table_cursor(
                self.sample_table,
                row=self.current_row_idx,
                column=global_col,
                scroll=use_native_scroll,
            )
            if horizontal_align == "home":
                try:
                    self.sample_table.scroll_to(x=0, y=self._viewport_scroll_y, animate=False, force=True)
                except Exception:
                    pass
            elif horizontal_align == "end":
                try:
                    max_x = max(0, int(getattr(self.sample_table, "max_scroll_x", 0) or 0))
                    self.sample_table.scroll_to(x=max_x, y=self._viewport_scroll_y, animate=False, force=True)
                except Exception:
                    pass
            else:
                try:
                    self.sample_table.scroll_to(y=self._viewport_scroll_y, animate=False, force=True)
                except Exception:
                    pass
        finally:
            self._is_internal_update = False

        self._notify_selection(self.current_row_idx, self.current_sample_idx)

    # --- Data Loading, View Modes, and Hydration ---

    def fetch_more_rows(self, batch_size: int = 100) -> bool:
        """Dynamically append rows to both ArrowBackends without clearing tables."""
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

            def _apply():
                self._refresh_fixed_backend()
                self._refresh_sample_backend()
                safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
                if self.records:
                    safe_row = min(self.current_row_idx, len(self.records) - 1)
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                    self._move_table_cursor(self.sample_table, row=safe_row, column=safe_col, scroll=False)
                try:
                    self.fixed_table.scroll_to(y=self._viewport_scroll_y, animate=False, force=True)
                    self.sample_table.scroll_to(x=saved_x, y=self._viewport_scroll_y, animate=False, force=True)
                except Exception:
                    pass

            try:
                self._run_batched(_apply)
            finally:
                self._is_internal_update = False

            return True
        finally:
            self._is_fetching_more = False

    def hydrate_rows(self, row_indices: List[int]) -> None:
        """Patch hydrated sample rows into SampleArrowBuffer and refresh visible matrix."""
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
            saved_x = getattr(self.sample_table, "scroll_x", 0)
            self._is_internal_update = True

            def _apply() -> None:
                if self._split_view_closing:
                    return
                self._refresh_sample_backend()
                safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
                if self.records:
                    safe_row = min(self.current_row_idx, len(self.records) - 1)
                    cur_coord = getattr(self.sample_table, "cursor_coordinate", None)
                    if cur_coord is None or cur_coord.row != safe_row or cur_coord.column != safe_col:
                        self._move_table_cursor(self.sample_table, row=safe_row, column=safe_col, scroll=False)
                cur_x = getattr(self.sample_table, "scroll_x", 0)
                cur_y = getattr(self.sample_table, "scroll_y", 0)
                if cur_x != saved_x or cur_y != self._viewport_scroll_y:
                    try:
                        self.sample_table.scroll_to(x=saved_x, y=self._viewport_scroll_y, animate=False, force=True)
                    except Exception:
                        pass

            try:
                self._run_batched(_apply)
            finally:
                self._is_internal_update = False

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
        try:
            self._refresh_fixed_backend()
            self._refresh_sample_backend()
            safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
            if self.records:
                self._move_table_cursor(self.fixed_table, row=0, scroll=False)
                self._move_table_cursor(self.sample_table, row=0, column=safe_col, scroll=False)
            self._command_tables_scroll_y(0)
        finally:
            self._is_internal_update = False

        self._last_notified = None
        self._notify_selection(0, self.current_sample_idx)

    def set_view_mode(self, mode: str):
        self.view_mode = mode.lower()
        self._is_internal_update = True
        try:
            self._refresh_fixed_backend()
            if self.records:
                self._move_table_cursor(self.fixed_table, row=self.current_row_idx, scroll=False)
            self._command_tables_scroll_y(self._viewport_scroll_y)
        finally:
            self._is_internal_update = False

    def set_format_tag(self, tag: str):
        self.format_tag = tag.upper()
        saved_x = getattr(self.sample_table, "scroll_x", 0)
        self._is_internal_update = True
        try:
            self._refresh_sample_backend()
            safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
            if self.records:
                safe_row = min(self.current_row_idx, len(self.records) - 1)
                self._move_table_cursor(self.sample_table, row=safe_row, column=safe_col, scroll=False)
            try:
                self.sample_table.scroll_to(x=saved_x, y=self._viewport_scroll_y, animate=False, force=True)
            except Exception:
                pass
        finally:
            self._is_internal_update = False

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
