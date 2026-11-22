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

    #sample_table.no-vertical-scrollbar {
        scrollbar-size-vertical: 0;
    }
    """

    VERTICAL_SCROLLBAR_HIDE_THRESHOLD = 1000

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
        self.samples = list(samples)
        self._is_internal_update = False
        self._accept_next_highlight = False
        self._split_view_closing = False
        self._click_timer: Optional[Any] = None
        self.current_row_idx = 0
        self.current_sample_idx = 0
        self._viewport_scroll_y = 0
        self._sample_window_start = 0
        self._sample_window_global_indices: List[int] = []
        self._last_viewport_rows = 25
        self._last_notified: Optional[Tuple[int, int]] = None

        self.window_size = 150
        self._is_fetching_more = False
        self._is_main_stream_view = True
        self._subset_records: Optional[List[VariantRecord]] = None
        self._active_global_indices: Optional[List[int]] = None
        self._record_cache: Dict[int, VariantRecord] = {
            idx: rec for idx, rec in enumerate(records)
        }

        if self.reader:
            if hasattr(self.reader, "get_total_variants_async") and self.reader.get_total_variants_async() is not None:
                self.total_records_count = self.reader.get_total_variants_async()
            elif hasattr(self.reader, "total_variants_ready") and self.reader.total_variants_ready:
                self.total_records_count = self.reader.total_variants
            else:
                self.total_records_count = None
        else:
            self.total_records_count = len(records)

        self._observed_variant_count = self.total_records_count if self.total_records_count is not None else len(records)
        self._rebuilding = False

        # Populate FixedArrowBuffer with all initial core site rows (and any already-streamed Handle 1 rows)
        self.fixed_buffer = FixedArrowBuffer(records)
        if self.reader is not None and hasattr(self.reader, "get_site_slice"):
            extra_sites = self.reader.get_site_slice(self.fixed_buffer.row_count)
            if extra_sites:
                self.fixed_buffer.append_records(extra_sites)
                self._observed_variant_count = max(self._observed_variant_count, self.fixed_buffer.row_count)

        # Populate SampleArrowBuffer with ONLY the initial visible viewport slice
        initial_vp_rows = 25
        initial_slice = list(records[:initial_vp_rows])
        self._sample_window_start = 0
        self._sample_window_global_indices = list(range(len(initial_slice)))
        self.records = initial_slice
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
        self._sync_sample_vertical_scrollbar()

    def compose(self):
        yield self.fixed_table
        yield self.divider
        yield self.sample_table

    def on_mount(self):
        self._sync_sample_vertical_scrollbar()
        self.sync_fixed_buffer_from_reader()
        if getattr(self.fixed_table, "backend", None) is None or getattr(self.sample_table, "backend", None) is None:
            self.rebuild_tables()
        else:
            self._notify_selection(self.current_row_idx, self.current_sample_idx)
        try:
            self.call_after_refresh(self._adjust_mounted_viewport)
        except Exception:
            pass
        try:
            self.focus()
        except Exception:
            pass

    def _adjust_mounted_viewport(self) -> None:
        if self._split_view_closing or self._rebuilding:
            return
        vp_rows = self._get_visible_row_count()
        active_count = self._get_active_row_count()
        if active_count > 0 and (
            vp_rows != self._last_viewport_rows or len(self.records) != min(vp_rows, active_count)
        ):
            self._last_viewport_rows = vp_rows
            self._sync_sample_viewport_window(
                self._viewport_scroll_y,
                saved_x=getattr(self.sample_table, "scroll_x", 0),
            )
            try:
                self.fixed_table.scroll_to(y=self._viewport_scroll_y, animate=False, force=True)
            except Exception:
                pass

    def _style_fixed_cell_value(self, row_idx: int, col_idx: int, val: Any) -> Any:
        cols = self._get_fixed_columns()
        col_name = cols[col_idx] if 0 <= col_idx < len(cols) else ""
        sval = "." if val is None else str(val)
        if col_name == "FILTER":
            return Text(sval, style="green" if sval == "PASS" else "red")
        if col_name == "GENE":
            global_idx = self._display_to_global_row(row_idx)
            if global_idx is not None and self._subset_records is None:
                is_drug = self.fixed_buffer.is_drug_row(global_idx)
            else:
                is_drug = self.fixed_buffer.is_drug_row(row_idx)
            return Text(sval, style="bold yellow" if is_drug else "white")
        return sval

    def _style_fixed_row_values(self, row_idx: int, values: List[Any]) -> List[Any]:
        cols = self._get_fixed_columns()
        global_idx = self._display_to_global_row(row_idx)
        if global_idx is not None and self._subset_records is None:
            is_drug = self.fixed_buffer.is_drug_row(global_idx)
        else:
            is_drug = self.fixed_buffer.is_drug_row(row_idx)
        styled: List[Any] = []
        for col_name, val in zip(cols, values):
            sval = "." if val is None else str(val)
            if col_name == "FILTER":
                styled.append(Text(sval, style="green" if sval == "PASS" else "red"))
            elif col_name == "GENE":
                styled.append(Text(sval, style="bold yellow" if is_drug else "white"))
            else:
                styled.append(sval)
        return styled

    def _live_fixed_row(self, row_idx: int) -> List[Any]:
        buf_idx = self._display_to_buffer_row(row_idx)
        return self.fixed_buffer.get_row_values(buf_idx, self.view_mode)

    def _live_fixed_cell(self, row_idx: int, col_idx: int) -> Any:
        cols = self._get_fixed_columns()
        col_name = cols[col_idx] if 0 <= col_idx < len(cols) else ""
        buf_idx = self._display_to_buffer_row(row_idx)
        return self.fixed_buffer.get_cell_value(buf_idx, col_name)

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
        row_indices = self._active_global_indices if self._subset_records is None else None
        pa_tbl = self.fixed_buffer.get_arrow_table(view_mode, row_indices=row_indices)
        if pa_tbl is None:
            return None
        return StyledArrowBackend(
            pa_tbl,
            row_styler=self._style_fixed_row_values,
            cell_styler=self._style_fixed_cell_value,
            live_row_provider=self._live_fixed_row,
            live_cell_provider=self._live_fixed_cell,
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

    def _display_to_global_row(self, display_row: int) -> Optional[int]:
        if self._subset_records is not None:
            return display_row if 0 <= display_row < len(self._subset_records) else None
        if self._active_global_indices is not None:
            if 0 <= display_row < len(self._active_global_indices):
                return self._active_global_indices[display_row]
            return None
        return display_row if 0 <= display_row < self.fixed_buffer.row_count else None

    def _display_to_buffer_row(self, display_row: int) -> int:
        if self._subset_records is not None:
            return display_row
        if self._active_global_indices is not None:
            if 0 <= display_row < len(self._active_global_indices):
                return self._active_global_indices[display_row]
            return -1
        return display_row

    def _get_active_row_count(self) -> int:
        if self._subset_records is not None:
            return len(self._subset_records)
        if self._active_global_indices is not None:
            return len(self._active_global_indices)
        return self.fixed_buffer.row_count

    def _get_known_total_count(self) -> Optional[int]:
        if self._subset_records is not None:
            return len(self._subset_records)
        if self._active_global_indices is not None:
            return len(self._active_global_indices)
        return self.total_records_count

    def _get_record_for_global_idx(self, global_idx: int) -> Optional[VariantRecord]:
        if self._subset_records is not None:
            return self._subset_records[global_idx] if 0 <= global_idx < len(self._subset_records) else None
        if self.reader is not None:
            if hasattr(self.reader, "get_hydrated_record"):
                rec = self.reader.get_hydrated_record(global_idx)
                if rec is not None:
                    self._record_cache[global_idx] = rec
                    if getattr(rec, "samples_loaded", False):
                        self.fixed_buffer.update_row_metadata(global_idx, rec)
                    return rec
            if global_idx in self._record_cache:
                return self._record_cache[global_idx]
            try:
                fetched = self.reader.get_slice(global_idx, 1, allow_placeholder=True)
            except TypeError:
                fetched = self.reader.get_slice(global_idx, 1)
            if fetched:
                self._record_cache[global_idx] = fetched[0]
                return fetched[0]
        return self._record_cache.get(global_idx)

    def get_record_at_display_row(self, display_row: int) -> Optional[VariantRecord]:
        if self._subset_records is not None:
            return self._subset_records[display_row] if 0 <= display_row < len(self._subset_records) else None
        local_idx = display_row - self._sample_window_start
        if 0 <= local_idx < len(self.records):
            return self.records[local_idx]
        global_idx = self._display_to_global_row(display_row)
        if global_idx is None:
            return None
        return self._get_record_for_global_idx(global_idx)

    def _refresh_fixed_backend(self) -> None:
        self.fixed_table.styles.width = self.FIXED_WIDTHS.get(self.view_mode, 56)
        backend = self._build_fixed_arrow_backend(self.view_mode)
        self.fixed_table.apply_arrow_backend(backend, column_labels=self._get_fixed_columns())

    def _refresh_sample_backend(self) -> None:
        backend = self._build_sample_arrow_backend(self.format_tag)
        sample_cols = self.samples if self.samples else ["Samples"]
        self.sample_table.apply_arrow_backend(backend, column_labels=sample_cols)

    def should_hide_sample_vertical_scrollbar(self) -> bool:
        effective = max(
            self._get_active_row_count(),
            self.fixed_buffer.row_count if self._is_main_stream_view else 0,
            self.total_records_count if self.total_records_count is not None else 0,
            self._observed_variant_count if self._is_main_stream_view else 0,
        )
        return effective > self.VERTICAL_SCROLLBAR_HIDE_THRESHOLD

    def _sync_sample_vertical_scrollbar(self) -> None:
        hide_v = self.should_hide_sample_vertical_scrollbar()
        try:
            self.sample_table.show_vertical_scrollbar = not hide_v
        except Exception:
            pass
        try:
            self.sample_table.show_horizontal_scrollbar = True
        except Exception:
            pass
        try:
            if hide_v:
                self.sample_table.add_class("no-vertical-scrollbar")
                self.sample_table.styles.scrollbar_size_vertical = 0
            else:
                self.sample_table.remove_class("no-vertical-scrollbar")
                self.sample_table.styles.scrollbar_size_vertical = None
        except Exception:
            pass

    def sync_fixed_buffer_from_reader(self, wait_for_stream: bool = False) -> int:
        """Pull any newly streamed Handle 1 sites into FixedArrowBuffer cleanly."""
        if not self.reader or self._subset_records is not None or self._is_fetching_more:
            return 0
        if wait_for_stream and hasattr(self.reader, "_site_thread"):
            st = getattr(self.reader, "_site_thread", None)
            if st is not None and st.is_alive():
                try:
                    st.join(timeout=2.0)
                except Exception:
                    pass

        if not hasattr(self.reader, "get_site_slice"):
            return 0

        loaded = self.fixed_buffer.row_count
        new_sites = self.reader.get_site_slice(loaded)
        if not new_sites:
            return 0

        self.fixed_buffer.append_records(new_sites)
        self._observed_variant_count = max(self._observed_variant_count, self.fixed_buffer.row_count)

        if self._is_main_stream_view and self._active_global_indices is None:
            saved_x = getattr(self.sample_table, "scroll_x", 0)
            saved_y = self._viewport_scroll_y
            active_count = self._get_active_row_count()
            safe_row = min(self.current_row_idx, active_count - 1) if active_count else 0
            self.current_row_idx = safe_row

            self._is_internal_update = True
            try:
                self._refresh_fixed_backend()
                if active_count:
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                self.fixed_table.scroll_to(y=saved_y, animate=False, force=True)
            except Exception:
                pass
            finally:
                self._is_internal_update = False

            if len(self.records) < self._get_visible_row_count():
                self._sync_sample_viewport_window(saved_y, saved_x=saved_x)
            else:
                self._schedule_fixed_post_layout_scroll(target_y=saved_y, cursor_row=safe_row)

            self._sync_sample_vertical_scrollbar()
        return len(new_sites)

    def update_counting_progress(self, count: int) -> None:
        if count > self._observed_variant_count:
            self._observed_variant_count = count
        if self._is_main_stream_view:
            self.sync_fixed_buffer_from_reader()
            self._sync_sample_vertical_scrollbar()

    def update_total_variants(self, count: int) -> None:
        self.total_records_count = count
        self._observed_variant_count = max(self._observed_variant_count, count)
        if self._is_main_stream_view:
            self.sync_fixed_buffer_from_reader()
        self._sync_sample_vertical_scrollbar()

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
        return min(heights) if heights else 25

    def _get_max_scroll_y(self) -> int:
        visible_rows = self._get_visible_row_count()
        return max(0, self._get_active_row_count() - visible_rows)

    def _get_local_sample_cursor_row(self) -> int:
        if not self.records:
            return 0
        local = self.current_row_idx - self._sample_window_start
        return max(0, min(len(self.records) - 1, local))

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

    def _schedule_fixed_post_layout_scroll(self, target_y: int, cursor_row: int) -> None:
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
                active_count = self._get_active_row_count()
                if active_count:
                    safe_row = max(0, min(active_count - 1, cursor_row))
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                clamped_y = max(0, min(self._get_max_scroll_y(), target_y))
                self.fixed_table.scroll_to(y=clamped_y, animate=False, force=True)
            except Exception:
                pass
            finally:
                self._is_internal_update = False

        try:
            self.call_after_refresh(_restore)
        except Exception:
            pass

    def _schedule_post_layout_scroll(
        self,
        target_y: int,
        target_x: Optional[float],
        cursor_row: int,
        cursor_col: int,
    ) -> None:
        """Restore exact scroll/cursor after layout passes without drifting SampleMatrixTable."""
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
                active_count = self._get_active_row_count()
                if active_count:
                    safe_row = max(0, min(active_count - 1, cursor_row))
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                clamped_y = max(0, min(self._get_max_scroll_y(), target_y))
                self._viewport_scroll_y = clamped_y
                self.fixed_table.scroll_to(y=clamped_y, animate=False, force=True)

                if self.records:
                    local_row = self._get_local_sample_cursor_row()
                    safe_col = max(0, min(len(self.samples) - 1, cursor_col)) if self.samples else 0
                    self._move_table_cursor(self.sample_table, row=local_row, column=safe_col, scroll=False)
                if target_x is not None:
                    self.sample_table.scroll_to(x=target_x, y=0, animate=False, force=True)
                else:
                    self.sample_table.scroll_to(y=0, animate=False, force=True)
            except Exception:
                pass
            finally:
                self._is_internal_update = False

        try:
            self.call_after_refresh(_restore)
        except Exception:
            pass

    def _sync_sample_viewport_window(
        self,
        viewport_top: int,
        saved_x: Optional[float] = None,
        force_rebind: bool = False,
    ) -> None:
        """
        Manually fill SampleMatrixTable's fixed viewport buffer for display rows
        [viewport_top, viewport_top + viewport_rows). Keeps sample_table.scroll_y pinned at 0
        and avoids backend swaps during steady scrolling so horizontal scroll_x stays intact.
        """
        active_count = self._get_active_row_count()
        visible_rows = max(1, self._get_visible_row_count())
        max_top = max(0, active_count - visible_rows)
        clamped_top = max(0, min(max_top, int(viewport_top)))
        self._viewport_scroll_y = clamped_top

        slice_end = min(active_count, clamped_top + visible_rows)
        window_records: List[VariantRecord] = []
        window_global_indices: List[int] = []
        unhydrated_global_indices: List[int] = []

        for d_idx in range(clamped_top, slice_end):
            g_idx = self._display_to_global_row(d_idx)
            if g_idx is None:
                continue
            window_global_indices.append(g_idx)
            rec = self._get_record_for_global_idx(g_idx)
            if rec is not None:
                window_records.append(rec)
                if not getattr(rec, "samples_loaded", True):
                    unhydrated_global_indices.append(g_idx)

        self._sample_window_start = clamped_top
        self._sample_window_global_indices = window_global_indices
        self.records = window_records

        prev_sample_rows = getattr(self.sample_table, "row_count", -1)
        prev_backend = getattr(self.sample_table, "backend", None)
        x_to_keep = getattr(self.sample_table, "scroll_x", 0) if saved_x is None else saved_x
        local_row = self._get_local_sample_cursor_row()
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0

        self.sample_buffer.reset(self.records, samples=self.samples)

        def _apply() -> None:
            if force_rebind or prev_backend is None or prev_sample_rows != len(self.records):
                self._refresh_sample_backend()
            else:
                _clear_table_render_caches(self.sample_table)
                try:
                    self.sample_table.refresh()
                except Exception:
                    pass
            if self.records:
                self._move_table_cursor(self.sample_table, row=local_row, column=safe_col, scroll=False)
            try:
                self.sample_table.scroll_to(x=x_to_keep, y=0, animate=False, force=True)
            except Exception:
                pass

        self._is_internal_update = True
        try:
            self._run_batched(_apply)
        finally:
            self._is_internal_update = False

        if (
            unhydrated_global_indices
            and self.reader is not None
            and self.samples
            and self._subset_records is None
            and hasattr(self.reader, "request_sample_hydration")
        ):
            req_start = min(unhydrated_global_indices)
            req_span = max(unhydrated_global_indices) - req_start + 1
            self.reader.request_sample_hydration(req_start, req_span)

    def _command_tables_scroll_y(self, target_y: int) -> None:
        """Align FixedVariantTable scroll_y and SampleMatrixTable fixed viewport window to target_y."""
        max_y = self._get_max_scroll_y()
        clamped_y = max(0, min(max_y, int(target_y)))
        saved_x = getattr(self.sample_table, "scroll_x", 0)

        self._sync_sample_viewport_window(clamped_y, saved_x=saved_x)

        self._is_internal_update = True
        try:
            try:
                self.fixed_table.scroll_to(y=clamped_y, animate=False, force=True)
            except Exception:
                pass
            try:
                self.sample_table.scroll_to(x=saved_x, y=0, animate=False, force=True)
            except Exception:
                pass
        finally:
            self._is_internal_update = False

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
        """Ask Handle 2 to hydrate only global rows mapped to the visible viewport."""
        if not self.reader or not self.samples or self._subset_records is not None:
            return
        if not hasattr(self.reader, "request_sample_hydration"):
            return
        missing_global = [
            self._sample_window_global_indices[i]
            for i, rec in enumerate(self.records)
            if i < len(self._sample_window_global_indices) and not getattr(rec, "samples_loaded", True)
        ]
        if missing_global:
            req_start = min(missing_global)
            req_span = max(missing_global) - req_start + 1
            self.reader.request_sample_hydration(req_start, req_span)

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
        """Slide both tables vertically in lockstep using FixedVariantTable + SampleMatrixTable viewport window."""
        if self._get_active_row_count() == 0:
            return
        visible_rows = self._get_visible_row_count()
        target_y = max(0, self._viewport_scroll_y + delta)

        if delta > 0 and self._is_main_stream_view and self._active_global_indices is None:
            self.sync_fixed_buffer_from_reader()
            while target_y + visible_rows >= self._get_active_row_count() - 15:
                if not self.fetch_more_rows(100):
                    break

        self._command_tables_scroll_y(target_y)
        self._schedule_fixed_post_layout_scroll(target_y=self._viewport_scroll_y, cursor_row=self.current_row_idx)

    # --- Vertical & Horizontal Navigation ---

    def navigate_rows(self, delta: int) -> None:
        if self._get_active_row_count() == 0:
            return
        target = self.current_row_idx + delta
        known_total = self._get_known_total_count()
        if delta > 0 and known_total is not None and target >= known_total:
            target = max(0, known_total - 1)
        if target < 0:
            target = 0
        self.set_active_row(target, sync_fixed=True, sync_sample=True)

    def navigate_page(self, forward: bool, page_size: Optional[int] = None) -> None:
        step = page_size if page_size is not None else max(1, self._get_visible_row_count() - 1)
        self.navigate_rows(step if forward else -step)

    def can_advance_row(self, forward: bool) -> bool:
        if forward:
            known_total = self._get_known_total_count()
            if known_total is not None:
                return self.current_row_idx < known_total - 1
            return True
        return self.current_row_idx > 0

    def advance_row(self, forward: bool) -> None:
        self.navigate_rows(1 if forward else -1)

    def set_active_row(self, target_row: int, sync_fixed: bool = True, sync_sample: bool = True) -> None:
        if target_row < 0:
            target_row = 0
        known_total = self._get_known_total_count()
        if known_total is not None and target_row >= known_total:
            target_row = max(0, known_total - 1)

        if self.reader and self._is_main_stream_view and self._active_global_indices is None:
            self.sync_fixed_buffer_from_reader()
            if hasattr(self.reader, "set_focus_row"):
                self.reader.set_focus_row(target_row)

        did_fetch = False
        if self._is_main_stream_view and self._active_global_indices is None:
            while self._get_active_row_count() <= target_row + 25:
                needed = max(100, target_row - self._get_active_row_count() + 50)
                if not self.fetch_more_rows(needed):
                    break
                did_fetch = True

        active_count = self._get_active_row_count()
        if active_count == 0:
            return
        if target_row >= active_count:
            target_row = active_count - 1

        self.current_row_idx = target_row

        visible_rows = self._get_visible_row_count()
        target_y = self._viewport_scroll_y
        if target_row < target_y:
            target_y = target_row
        elif target_row >= target_y + visible_rows:
            target_y = target_row - visible_rows + 1
        target_y = max(0, min(self._get_max_scroll_y(), target_y))

        saved_x = getattr(self.sample_table, "scroll_x", 0)
        needs_sample_window_refresh = (
            target_y != self._sample_window_start
            or not self.records
            or getattr(self.sample_table, "row_count", 0) == 0
        )

        if needs_sample_window_refresh:
            self._sync_sample_viewport_window(target_y, saved_x=saved_x)
        else:
            self._viewport_scroll_y = target_y

        self._is_internal_update = True
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
        local_row = self._get_local_sample_cursor_row()

        def _apply() -> None:
            if sync_fixed and getattr(self.fixed_table, "row_count", 0) > target_row:
                self._move_table_cursor(self.fixed_table, row=target_row, scroll=False)
            if sync_sample and getattr(self.sample_table, "row_count", 0) > local_row:
                self._move_table_cursor(self.sample_table, row=local_row, column=safe_col, scroll=False)
            try:
                self.fixed_table.scroll_to(y=target_y, animate=False, force=True)
                self.sample_table.scroll_to(x=saved_x, y=0, animate=False, force=True)
            except Exception:
                pass

        try:
            self._run_batched(_apply)
        finally:
            self._is_internal_update = False

        if did_fetch:
            self._schedule_fixed_post_layout_scroll(target_y=target_y, cursor_row=target_row)

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
        """Move sample cursor horizontally across SampleMatrixTable at current local viewport row."""
        if not self.samples:
            return
        global_col = max(0, min(len(self.samples) - 1, global_col))
        self.current_sample_idx = global_col
        local_row = self._get_local_sample_cursor_row()

        self._is_internal_update = True
        try:
            if getattr(self.sample_table, "row_count", 0) > local_row:
                self._move_table_cursor(
                    self.sample_table,
                    row=local_row,
                    column=global_col,
                    scroll=True,
                )
            if horizontal_align == "home":
                try:
                    self.sample_table.scroll_to(x=0, y=0, animate=False, force=True)
                except Exception:
                    pass
            elif horizontal_align == "end":
                try:
                    max_x = max(0, int(getattr(self.sample_table, "max_scroll_x", 0) or 0))
                    if max_x > 0:
                        self.sample_table.scroll_to(x=max_x, y=0, animate=False, force=True)
                except Exception:
                    pass
            else:
                try:
                    if getattr(self.sample_table, "scroll_y", 0) != 0:
                        self.sample_table.scroll_to(y=0, animate=False, force=True)
                except Exception:
                    pass
        finally:
            self._is_internal_update = False

        self._notify_selection(self.current_row_idx, self.current_sample_idx)

    # --- Data Loading, Filtering, View Modes, and In-Place Hydration ---

    def fetch_more_rows(self, batch_size: int = 100) -> bool:
        """Pull newly streamed site rows into FixedArrowBuffer (supporting both Handle 1 and MockReader)."""
        if (
            not self.reader
            or self._is_fetching_more
            or not self._is_main_stream_view
            or self._active_global_indices is not None
            or self._subset_records is not None
        ):
            return False

        if self.sync_fixed_buffer_from_reader() > 0:
            return True

        current_loaded = self.fixed_buffer.row_count
        if self.total_records_count is not None and current_loaded >= self.total_records_count:
            return False

        if hasattr(self.reader, "get_site_slice"):
            if hasattr(self.reader, "_wait_for_site_index"):
                self.reader._wait_for_site_index(current_loaded + batch_size)
                if self.sync_fixed_buffer_from_reader() > 0:
                    return True
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

            for off, rec in enumerate(new_slice):
                self._record_cache[current_loaded + off] = rec
            self.fixed_buffer.append_records(new_slice)

            if len(new_slice) < batch_size and self.total_records_count is None:
                self.total_records_count = self.fixed_buffer.row_count

            self._observed_variant_count = max(self._observed_variant_count, self.fixed_buffer.row_count)

            self._is_internal_update = True
            saved_x = getattr(self.sample_table, "scroll_x", 0)
            saved_y = self._viewport_scroll_y
            active_count = self._get_active_row_count()
            safe_row = min(self.current_row_idx, active_count - 1) if active_count else 0

            def _apply() -> None:
                self._refresh_fixed_backend()
                if active_count:
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                try:
                    self.fixed_table.scroll_to(y=saved_y, animate=False, force=True)
                except Exception:
                    pass

            try:
                self._run_batched(_apply)
            finally:
                self._is_internal_update = False

            if len(self.records) < self._get_visible_row_count():
                self._sync_sample_viewport_window(saved_y, saved_x=saved_x)
            else:
                self._schedule_fixed_post_layout_scroll(target_y=saved_y, cursor_row=safe_row)

            self._sync_sample_vertical_scrollbar()
            return True
        finally:
            self._is_fetching_more = False

    def hydrate_rows(self, row_indices: List[int]) -> None:
        """
        Map incoming global Handle 2 row indices to local viewport rows inside SampleMatrixTable
        and repaint in place without replacing sample_table.backend.
        """
        if self._split_view_closing or not self.reader or self._subset_records is not None:
            return
        try:
            if getattr(self.app, "_vcfscape_closing", False):
                return
        except Exception:
            pass
        if not hasattr(self.reader, "get_hydrated_record"):
            return

        global_to_local: Dict[int, List[int]] = {}
        for local_idx, g_idx in enumerate(self._sample_window_global_indices):
            global_to_local.setdefault(g_idx, []).append(local_idx)

        hydrated_local_map: Dict[int, VariantRecord] = {}
        updated_current = False
        fixed_meta_changed = False
        current_global = self._display_to_global_row(self.current_row_idx)

        for g_idx in row_indices:
            hydrated = self.reader.get_hydrated_record(g_idx)
            if hydrated is None or not getattr(hydrated, "samples_loaded", False):
                continue
            self._record_cache[g_idx] = hydrated
            if self.fixed_buffer.update_row_metadata(g_idx, hydrated):
                fixed_meta_changed = True
            for local_idx in global_to_local.get(g_idx, ()):
                if 0 <= local_idx < len(self.records):
                    self.records[local_idx] = hydrated
                    hydrated_local_map[local_idx] = hydrated
            if g_idx == current_global:
                updated_current = True

        if self._split_view_closing:
            return

        if hydrated_local_map:
            if self.sample_buffer.hydrate_rows(list(hydrated_local_map.keys()), hydrated_local_map):
                _clear_table_render_caches(self.sample_table)
                try:
                    self.sample_table.refresh()
                except Exception:
                    pass

        if fixed_meta_changed:
            _clear_table_render_caches(self.fixed_table)
            try:
                self.fixed_table.refresh()
            except Exception:
                pass

        if updated_current and not self._split_view_closing:
            self._last_notified = None
            self._notify_selection(self.current_row_idx, self.current_sample_idx)

    def _apply_global_indices(
        self,
        matched_indices: Optional[List[int]],
        is_main_stream: bool,
    ) -> int:
        """Switch view between full FixedArrowBuffer and a filtered/jumped global index subset."""
        self._subset_records = None
        self._active_global_indices = matched_indices
        self._is_main_stream_view = is_main_stream
        self.current_row_idx = 0
        self._viewport_scroll_y = 0

        if is_main_stream and matched_indices is None and self.reader:
            if hasattr(self.reader, "get_total_variants_async") and self.reader.get_total_variants_async() is not None:
                self.total_records_count = self.reader.get_total_variants_async()
            elif hasattr(self.reader, "total_variants_ready") and self.reader.total_variants_ready:
                self.total_records_count = self.reader.total_variants
            else:
                self.total_records_count = None
        else:
            self.total_records_count = self._get_active_row_count()

        self._observed_variant_count = (
            self.total_records_count if self.total_records_count is not None else self._get_active_row_count()
        )
        self._sync_sample_vertical_scrollbar()

        self._is_internal_update = True
        try:
            self._refresh_fixed_backend()
            if self._get_active_row_count() > 0:
                self._move_table_cursor(self.fixed_table, row=0, scroll=False)
            self.fixed_table.scroll_to(y=0, animate=False, force=True)
        except Exception:
            pass
        finally:
            self._is_internal_update = False

        self._sync_sample_viewport_window(0, saved_x=0, force_rebind=True)
        self._last_notified = None
        self._notify_selection(0, self.current_sample_idx)
        return self._get_active_row_count()

    def apply_filter(
        self,
        min_qual: Optional[float] = None,
        variant_type: Optional[str] = None,
        filter_status: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> int:
        """Filter directly in-memory against FixedArrowBuffer and hydrate only visible matches."""
        if self.reader is not None:
            self.sync_fixed_buffer_from_reader(wait_for_stream=True)

        is_all = (
            (variant_type is None or variant_type.upper() == "ALL")
            and min_qual is None
            and (filter_status is None or filter_status.upper() == "ALL")
            and not search_query
        )
        if is_all:
            return self._apply_global_indices(None, is_main_stream=True)

        matched = self.fixed_buffer.filter_indices(
            min_qual=min_qual,
            variant_type=variant_type,
            filter_status=filter_status,
            search_query=search_query,
        )
        return self._apply_global_indices(matched, is_main_stream=False)

    def jump_to_region(self, chrom: str, pos: int) -> bool:
        if self.reader is not None:
            self.sync_fixed_buffer_from_reader()
        matched = self.fixed_buffer.find_region_indices(chrom, pos, pos + 500000, limit=500)
        if not matched:
            matched = self.fixed_buffer.find_region_indices(chrom, max(0, pos - 100000), pos + 100000, limit=500)
        if matched:
            self._apply_global_indices(matched, is_main_stream=False)
            return True

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
        self._active_global_indices = None
        self.current_row_idx = 0
        self._viewport_scroll_y = 0

        if is_main_stream:
            self._subset_records = None
            self._record_cache.clear()
            for idx, rec in enumerate(records):
                self._record_cache[idx] = rec
            self.fixed_buffer.reset(records)
            if self.reader is not None:
                self.sync_fixed_buffer_from_reader()
            if self.reader:
                if hasattr(self.reader, "get_total_variants_async") and self.reader.get_total_variants_async() is not None:
                    self.total_records_count = self.reader.get_total_variants_async()
                elif hasattr(self.reader, "total_variants_ready") and self.reader.total_variants_ready:
                    self.total_records_count = self.reader.total_variants
                else:
                    self.total_records_count = None
            else:
                self.total_records_count = self.fixed_buffer.row_count
        else:
            self._subset_records = list(records)
            self.fixed_buffer.reset(self._subset_records)
            self.total_records_count = len(self._subset_records)

        self._observed_variant_count = (
            self.total_records_count if self.total_records_count is not None else self._get_active_row_count()
        )
        self._sync_sample_vertical_scrollbar()

        self._is_internal_update = True
        try:
            self._refresh_fixed_backend()
            if self._get_active_row_count() > 0:
                self._move_table_cursor(self.fixed_table, row=0, scroll=False)
            self.fixed_table.scroll_to(y=0, animate=False, force=True)
        except Exception:
            pass
        finally:
            self._is_internal_update = False

        self._sync_sample_viewport_window(0, saved_x=0, force_rebind=True)
        self._last_notified = None
        self._notify_selection(0, self.current_sample_idx)

    def set_view_mode(self, mode: str):
        self.view_mode = mode.lower()
        saved_y = self._viewport_scroll_y
        active_count = self._get_active_row_count()
        safe_row = min(self.current_row_idx, active_count - 1) if active_count else 0
        self._is_internal_update = True
        try:
            self._refresh_fixed_backend()
            if active_count:
                self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
            self.fixed_table.scroll_to(y=saved_y, animate=False, force=True)
        except Exception:
            pass
        finally:
            self._is_internal_update = False
        self._schedule_fixed_post_layout_scroll(target_y=saved_y, cursor_row=safe_row)

    def set_format_tag(self, tag: str):
        self.format_tag = tag.upper()
        saved_x = getattr(self.sample_table, "scroll_x", 0)
        local_row = self._get_local_sample_cursor_row()
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
        _clear_table_render_caches(self.sample_table)
        try:
            self.sample_table.refresh()
        except Exception:
            pass
        if getattr(self.sample_table, "backend", None) is None:
            self._refresh_sample_backend()
        if self.records:
            self._move_table_cursor(self.sample_table, row=local_row, column=safe_col, scroll=False)
        try:
            self.sample_table.scroll_to(x=saved_x, y=0, animate=False, force=True)
        except Exception:
            pass

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
            self._sync_sample_viewport_window(self._viewport_scroll_y, force_rebind=True)
            self._sync_sample_vertical_scrollbar()
            self._notify_selection(self.current_row_idx, self.current_sample_idx)
        finally:
            self._rebuilding = False

    def on_resize(self, event: events.Resize) -> None:
        if self._split_view_closing or self._rebuilding:
            return
        vp_rows = self._get_visible_row_count()
        if self._get_active_row_count() > 0 and vp_rows != self._last_viewport_rows:
            self._last_viewport_rows = vp_rows
            self._sync_sample_viewport_window(
                self._viewport_scroll_y,
                saved_x=getattr(self.sample_table, "scroll_x", 0),
            )

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
            local_row = int(event.coordinate.row)
            target_display_row = self._sample_window_start + local_row
            self.current_sample_idx = int(event.coordinate.column)
            self.set_active_row(target_display_row, sync_fixed=True, sync_sample=False)

    def _notify_selection(self, row_idx: int, sample_col_idx: int) -> None:
        if self._split_view_closing:
            return
        rec = self.get_record_at_display_row(row_idx)
        if rec is not None:
            coord = (row_idx, sample_col_idx)
            if self._last_notified == coord:
                return
            self._last_notified = coord
            sample_id = self.samples[sample_col_idx] if 0 <= sample_col_idx < len(self.samples) else None
            self.post_message(self.VariantSelected(rec, sample_id, row_index=row_idx))
