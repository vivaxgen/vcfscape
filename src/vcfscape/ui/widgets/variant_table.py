"""
Central Variant Split Table for VCFscape backed by Dual PyArrow ArrowBackends:
1. FixedVariantTable (passive virtualized ScrollView backed by FixedArrowBuffer)
2. Vertical divider (1ch │)
3. SampleMatrixTable (passive virtualized ScrollView backed by fixed-viewport SampleArrowBuffer)
With VariantSplitView as the top-level focused widget capturing Up/Down/PageUp/PageDown/
Left/Right/Home/End keys and mouse wheel events to command both child tables in lockstep.
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Any, Callable, Dict, List, Optional, Tuple
from textual import events
from textual.coordinate import Coordinate
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.strip import Strip
from textual.widgets import Static
from textual.containers import Horizontal
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

try:
    from textual.scroll_view import ScrollView
except ImportError:
    from textual.widgets import ScrollView  # type: ignore

try:
    from textual._context import NoActiveAppError
except ImportError:
    NoActiveAppError = LookupError  # type: ignore

try:
    from textual_fastdatatable import ArrowBackend
except ImportError:
    try:
        from textual_fastdatatable.backends.arrow import ArrowBackend
    except ImportError:
        try:
            from textual_fastdatatable.backend import ArrowBackend  # type: ignore
        except ImportError:
            ArrowBackend = object  # type: ignore

from vcfscape.core.vcf_reader import VariantRecord
from vcfscape.core.arrow_buffer import (
    FixedArrowBuffer,
    SampleArrowBuffer,
    HAS_PYARROW,
    HAS_FASTDATATABLE,
)


FIXED_COLUMN_WIDTHS: Dict[str, int] = {
    "CHROM": 11,
    "POS": 9,
    "ID": 11,
    "REF": 4,
    "ALT": 5,
    "QUAL": 5,
    "FILTER": 6,
    "GENE": 10,
    "INFO": 16,
    "FORMAT": 9,
}


class StyledArrowBackend(ArrowBackend):  # type: ignore[misc]
    """
    ArrowBackend extension supporting:
    - Lazy viewport-only Rich Text styling on visible cells/rows.
    - Live row/cell providers so background sample hydration and Handle 1 site streaming
      update cells in place without replacing table.backend or disturbing scroll state.
    """

    def __init__(
        self,
        table: Any,
        row_styler: Optional[Callable[[int, List[Any]], List[Any]]] = None,
        cell_styler: Optional[Callable[[int, int, Any], Any]] = None,
        live_row_provider: Optional[Callable[[int], List[Any]]] = None,
        live_cell_provider: Optional[Callable[[int, int], Any]] = None,
    ):
        if ArrowBackend is not object:
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
            raw_row = (
                self._live_row_provider(row)
                if self._live_row_provider is not None
                else list(super().get_row_at(row))
            )
            styled = self._row_styler(row, raw_row)
            if 0 <= column < len(styled):
                return styled[column]
        return val


def _clear_table_render_caches(table: Any) -> None:
    """Invalidate cached line strips if present before repainting."""
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


def _truncate_text_to_width(val: Any, width: int) -> Tuple[str, Optional[Style]]:
    """Convert cell value (str or Rich Text) into a padded/truncated string + base style."""
    if isinstance(val, Text):
        raw = val.plain
        base_style: Optional[Style] = val.style if isinstance(val.style, Style) else None
        if base_style is None and val.style:
            try:
                base_style = Style.parse(str(val.style))
            except Exception:
                base_style = None
        if base_style is None and val._spans:
            sp_style = val._spans[0].style
            if isinstance(sp_style, Style):
                base_style = sp_style
            elif sp_style:
                try:
                    base_style = Style.parse(str(sp_style))
                except Exception:
                    base_style = None
    else:
        raw = "." if val is None else str(val)
        base_style = None

    if len(raw) > width:
        if width >= 2:
            raw = raw[: width - 1] + "…"
        else:
            raw = raw[:width]
    if len(raw) < width:
        raw = raw.ljust(width)
    return raw, base_style


class _PassiveSplitTable(ScrollView):
    """
    Virtualized passive ScrollView grid reading directly from StyledArrowBackend:
    - Sticky 1-line header at y == 0
    - O(visible_rows * visible_cols) render_line(y) with bisect column clipping
    - Deterministic cursor_coordinate and horizontal scroll_to(x=...) without opaque caches
    """

    can_focus = False

    DEFAULT_CSS = """
    _PassiveSplitTable {
        overflow-x: auto;
        overflow-y: auto;
    }
    """

    def __init__(
        self,
        backend: Any = None,
        column_labels: Optional[List[str]] = None,
        cursor_type: str = "cell",
        zebra_stripes: bool = True,
        show_row_labels: bool = False,
        show_cursor: bool = True,
        null_rep: str = ".",
        live_row_count_provider: Optional[Callable[[], int]] = None,
        is_fixed_pane: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.peer_table: Optional["_PassiveSplitTable"] = None
        self.split_view: Optional["VariantSplitView"] = None
        self.backend = backend
        self.cursor_type = cursor_type
        self.zebra_stripes = zebra_stripes
        self.show_row_labels = show_row_labels
        self.show_cursor = show_cursor
        self.null_rep = null_rep
        self.header_height = 1
        self.show_header = True
        self._is_fixed_pane = is_fixed_pane
        self._live_row_count_provider = live_row_count_provider
        self._cursor_coord = Coordinate(0, 0)

        if column_labels is not None:
            self._column_labels = list(column_labels)
        else:
            pa_tbl = getattr(backend, "pa_table", None)
            if pa_tbl is not None and hasattr(pa_tbl, "column_names"):
                self._column_labels = list(pa_tbl.column_names)
            else:
                self._column_labels = []

        self._col_widths: List[int] = []
        self._col_offsets: List[int] = []
        self._total_width: int = 1
        self._recompute_column_geometry()
        self.sync_dimensions()

    @property
    def row_count(self) -> int:
        if self._live_row_count_provider is not None:
            try:
                return max(0, int(self._live_row_count_provider()))
            except Exception:
                pass
        if self.backend is not None:
            pa_tbl = getattr(self.backend, "pa_table", None)
            if pa_tbl is not None and hasattr(pa_tbl, "num_rows"):
                return int(pa_tbl.num_rows)
            rc = getattr(self.backend, "row_count", 0)
            return int(rc)
        return 0

    @property
    def column_count(self) -> int:
        if self._column_labels:
            return len(self._column_labels)
        if self.backend is not None:
            pa_tbl = getattr(self.backend, "pa_table", None)
            if pa_tbl is not None and hasattr(pa_tbl, "num_columns"):
                return int(pa_tbl.num_columns)
            return int(getattr(self.backend, "column_count", 0))
        return 0

    @property
    def cursor_coordinate(self) -> Coordinate:
        return self._cursor_coord

    @cursor_coordinate.setter
    def cursor_coordinate(self, coord: Coordinate) -> None:
        max_r = max(0, self.row_count - 1)
        max_c = max(0, self.column_count - 1)
        clamped = Coordinate(
            max(0, min(max_r, int(coord.row))),
            max(0, min(max_c, int(coord.column))),
        )
        if clamped != self._cursor_coord:
            self._cursor_coord = clamped
            try:
                self.refresh()
            except Exception:
                pass

    def _recompute_column_geometry(self) -> None:
        widths: List[int] = []
        offsets: List[int] = []
        x_pos = 0
        for label in self._column_labels:
            if self._is_fixed_pane:
                w = FIXED_COLUMN_WIDTHS.get(label, max(6, len(label) + 1))
            else:
                w = max(8, min(16, len(label) + 2))
            offsets.append(x_pos)
            widths.append(w)
            x_pos += w + 1  # 1ch separator gap between columns
        self._col_widths = widths
        self._col_offsets = offsets
        self._total_width = max(1, x_pos - 1 if widths else 1)

    def sync_dimensions(self) -> None:
        hdr_h = self.header_height if self.show_header else 0
        extra_pad = 1 if self._is_fixed_pane else 0
        total_h = max(1, self.row_count + hdr_h + extra_pad)
        total_w = max(1, self._total_width)
        self.virtual_size = Size(total_w, total_h)
        max_r = max(0, self.row_count - 1)
        max_c = max(0, self.column_count - 1)
        if self._cursor_coord.row > max_r or self._cursor_coord.column > max_c:
            self._cursor_coord = Coordinate(
                min(self._cursor_coord.row, max_r),
                min(self._cursor_coord.column, max_c),
            )

    def apply_arrow_backend(
        self,
        new_backend: Any,
        column_labels: Optional[List[str]] = None,
    ) -> None:
        sv = self.split_view
        if getattr(sv, "_split_view_closing", False):
            return
        if new_backend is None:
            return
        self.backend = new_backend
        if column_labels is not None:
            self._column_labels = list(column_labels)
        else:
            pa_tbl = getattr(new_backend, "pa_table", None)
            if pa_tbl is not None and hasattr(pa_tbl, "column_names"):
                self._column_labels = list(pa_tbl.column_names)
        self._recompute_column_geometry()
        self.sync_dimensions()
        try:
            self.refresh(layout=True)
        except Exception:
            try:
                self.refresh()
            except Exception:
                pass

    def _viewport_width(self) -> int:
        try:
            scr = self.scrollable_content_region
            if scr is not None and scr.width > 0:
                return scr.width
        except Exception:
            pass
        try:
            if self.size.width > 0:
                return self.size.width
        except Exception:
            pass
        return 40

    def _viewport_height(self) -> int:
        try:
            scr = self.scrollable_content_region
            if scr is not None and scr.height > 0:
                return scr.height
        except Exception:
            pass
        try:
            if self.size.height > 0:
                return self.size.height
        except Exception:
            pass
        return 26

    def get_current_scroll_x(self) -> float:
        sx = getattr(self, "scroll_x", 0.0) or 0.0
        stx = getattr(self, "scroll_target_x", sx)
        return float(stx if stx is not None else sx)

    def get_effective_max_scroll_x(self) -> int:
        try:
            msx = int(self.max_scroll_x)
            if msx > 0:
                return msx
        except Exception:
            pass
        return max(0, self._total_width - self._viewport_width())

    def scroll_to_safe(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
    ) -> None:
        try:
            self.scroll_to(x=x, y=y, animate=False, force=True, immediate=True)
        except TypeError:
            try:
                self.scroll_to(x=x, y=y, animate=False, force=True)
            except Exception:
                pass
        except Exception:
            pass

    def scroll_cursor_into_view(
        self,
        horizontal: bool = True,
        vertical: bool = False,
    ) -> None:
        target_x: Optional[float] = None
        target_y: Optional[float] = None

        if horizontal and self._col_offsets:
            col = max(0, min(len(self._col_offsets) - 1, self._cursor_coord.column))
            col_x0 = self._col_offsets[col]
            col_x1 = col_x0 + self._col_widths[col]
            vp_w = self._viewport_width()
            cur_x = int(self.get_current_scroll_x())
            max_x = self.get_effective_max_scroll_x()
            if col_x1 > cur_x + vp_w:
                target_x = max(0, min(max_x, col_x1 - vp_w))
            elif col_x0 < cur_x:
                target_x = max(0, min(max_x, col_x0))

        if vertical and not self._is_fixed_pane:
            target_y = 0
        elif vertical and self._is_fixed_pane:
            hdr = self.header_height if self.show_header else 0
            vis_rows = max(1, self._viewport_height() - hdr)
            cur_y = int(getattr(self, "scroll_y", 0) or 0)
            row = self._cursor_coord.row
            if row < cur_y:
                target_y = row
            elif row >= cur_y + vis_rows:
                target_y = row - vis_rows + 1

        if target_x is not None or target_y is not None:
            self.scroll_to_safe(x=target_x, y=target_y)

    def move_cursor(
        self,
        *,
        row: Optional[int] = None,
        column: Optional[int] = None,
        animate: bool = False,
        scroll: bool = True,
    ) -> None:
        max_r = max(0, self.row_count - 1)
        max_c = max(0, self.column_count - 1)
        target_r = self._cursor_coord.row if row is None else max(0, min(max_r, int(row)))
        target_c = self._cursor_coord.column if column is None else max(0, min(max_c, int(column)))
        self._cursor_coord = Coordinate(target_r, target_c)
        if scroll:
            self.scroll_cursor_into_view(
                horizontal=(column is not None),
                vertical=self._is_fixed_pane,
            )
        try:
            self.refresh()
        except Exception:
            pass

    def _is_light_theme(self) -> bool:
        try:
            app_obj = self.app
            if app_obj is not None and "theme-light" in getattr(app_obj, "classes", ()):
                return True
        except Exception:
            pass
        return False

    def render_line(self, y: int) -> Strip:
        vp_w = self._viewport_width()
        if vp_w <= 0:
            return Strip.blank(0)
        is_light = self._is_light_theme()

        if is_light:
            bg_hex = "#ffffff"
            zebra_hex = "#f1f5f9"
            hdr_bg_hex = "#e2e8f0"
            hdr_fg_hex = "#0f172a"
            cursor_bg_hex = "#2563eb"
            cursor_fg_hex = "#ffffff"
            default_fg_hex = "#0f172a"
            sep_fg_hex = "#cbd5e1"
        else:
            bg_hex = "#0b0f17"
            zebra_hex = "#111827"
            hdr_bg_hex = "#161e2e"
            hdr_fg_hex = "#38bdf8" if self._is_fixed_pane else "#f8fafc"
            cursor_bg_hex = "#1d4ed8"
            cursor_fg_hex = "#f8fafc"
            default_fg_hex = "#e2e8f0"
            sep_fg_hex = "#1e293b"

        bg_style = Style(bgcolor=bg_hex, color=default_fg_hex)
        if not self._column_labels or not self._col_offsets:
            return Strip.blank(vp_w, bg_style)

        scroll_x = max(0, int(getattr(self, "scroll_x", 0) or 0))
        scroll_y = 0 if not self._is_fixed_pane else max(0, int(getattr(self, "scroll_y", 0) or 0))

        first_col = max(0, bisect_right(self._col_offsets, scroll_x) - 1)
        start_x = self._col_offsets[first_col]
        end_x = scroll_x + vp_w

        if self.show_header and y == 0:
            hdr_style = Style(bgcolor=hdr_bg_hex, color=hdr_fg_hex, bold=True)
            hdr_sep_style = Style(bgcolor=hdr_bg_hex, color=sep_fg_hex)
            segments: List[Segment] = []
            num_cols = len(self._column_labels)
            for col_idx in range(first_col, num_cols):
                col_x = self._col_offsets[col_idx]
                if col_x >= end_x:
                    break
                col_w = self._col_widths[col_idx]
                cell_txt, _ = _truncate_text_to_width(self._column_labels[col_idx], col_w)
                segments.append(Segment(cell_txt, hdr_style))
                if col_idx < num_cols - 1:
                    segments.append(Segment(" ", hdr_sep_style))
            strip = Strip(segments)
            crop_start = max(0, scroll_x - start_x)
            if crop_start >= strip.cell_length:
                return Strip.blank(vp_w, hdr_style)
            return strip.crop(crop_start, crop_start + vp_w).adjust_cell_length(vp_w, hdr_style)

        data_row = (y - (self.header_height if self.show_header else 0)) + scroll_y
        if data_row < 0 or data_row >= self.row_count:
            return Strip.blank(vp_w, bg_style)

        is_zebra = self.zebra_stripes and (data_row % 2 == 1)
        row_bg = zebra_hex if is_zebra else bg_hex
        row_base_style = Style(bgcolor=row_bg, color=default_fg_hex)
        sep_style = Style(bgcolor=row_bg, color=sep_fg_hex)
        cursor_style = Style(bgcolor=cursor_bg_hex, color=cursor_fg_hex, bold=True)

        is_active_row = self.show_cursor and (data_row == self._cursor_coord.row)
        row_highlight = is_active_row and self.cursor_type == "row"

        segments = []
        num_cols = len(self._column_labels)
        backend = self.backend
        for col_idx in range(first_col, num_cols):
            col_x = self._col_offsets[col_idx]
            if col_x >= end_x:
                break
            col_w = self._col_widths[col_idx]
            if backend is not None and hasattr(backend, "get_cell_at"):
                try:
                    raw_val = backend.get_cell_at(data_row, col_idx)
                except Exception:
                    raw_val = self.null_rep
            else:
                raw_val = self.null_rep

            cell_txt, cell_fg_style = _truncate_text_to_width(raw_val, col_w)
            cell_highlight = row_highlight or (
                is_active_row and self.cursor_type == "cell" and col_idx == self._cursor_coord.column
            )
            if cell_highlight:
                st = cursor_style
            elif cell_fg_style is not None:
                st = Style(
                    color=cell_fg_style.color,
                    bgcolor=row_bg,
                    bold=cell_fg_style.bold,
                    dim=cell_fg_style.dim,
                )
            else:
                st = row_base_style
            segments.append(Segment(cell_txt, st))
            if col_idx < num_cols - 1:
                segments.append(Segment(" ", cursor_style if row_highlight else sep_style))

        strip = Strip(segments)
        crop_start = max(0, scroll_x - start_x)
        fill_style = cursor_style if row_highlight else row_base_style
        if crop_start >= strip.cell_length:
            return Strip.blank(vp_w, fill_style)
        return strip.crop(crop_start, crop_start + vp_w).adjust_cell_length(vp_w, fill_style)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        event.stop()

    def on_enter(self, event: events.Enter) -> None:
        event.stop()

    def on_leave(self, event: events.Leave) -> None:
        event.stop()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        sv = self.split_view
        if sv is None:
            return
        vp_w = self._viewport_width()
        vp_h = self._viewport_height()
        if event.x < 0 or event.x >= vp_w or event.y < 0 or event.y >= vp_h:
            return
        hdr = self.header_height if self.show_header else 0
        if event.y < hdr:
            return
        scroll_y = 0 if not self._is_fixed_pane else max(0, int(getattr(self, "scroll_y", 0) or 0))
        data_row = scroll_y + (event.y - hdr)
        if not (0 <= data_row < self.row_count):
            return

        content_x = max(0, int(getattr(self, "scroll_x", 0) or 0)) + event.x
        col_idx = max(0, min(self.column_count - 1, bisect_right(self._col_offsets, content_x) - 1)) if self._col_offsets else 0
        sv._handle_table_click(self, data_row, col_idx)

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
    """Left anchored passive ScrollView table displaying variant metadata columns."""

    DEFAULT_CSS = """
    FixedVariantTable {
        overflow-x: hidden;
        overflow-y: auto;
    }
    """

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.stop()
        event.prevent_default()

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.stop()
        event.prevent_default()


class SampleMatrixTable(_PassiveSplitTable):
    """Right horizontally scrollable passive ScrollView table displaying sample cells."""

    DEFAULT_CSS = """
    SampleMatrixTable {
        overflow-x: auto;
        overflow-y: auto;
    }
    """


class VariantSplitView(Horizontal):
    """
    Top-level Split Table Controller backed by Dual PyArrow ArrowBackends:
    - Holds focus (`can_focus=True`) and captures Up/Down/PageUp/PageDown/Left/Right/Home/End
      plus vertical mouse wheel events, commanding both passive tables in lockstep.
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
        self._split_view_closing = False
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
        sample_cols = self.samples if self.samples else ["Samples"]

        self.fixed_table = FixedVariantTable(
            id="fixed_table",
            backend=fixed_backend,
            column_labels=self._get_fixed_columns(),
            cursor_type="row",
            zebra_stripes=True,
            show_row_labels=False,
            show_cursor=True,
            null_rep=".",
            live_row_count_provider=self._get_active_row_count,
            is_fixed_pane=True,
        )
        self.fixed_table.show_vertical_scrollbar = False
        self.fixed_table.show_horizontal_scrollbar = False
        self.fixed_table.styles.width = self.FIXED_WIDTHS.get(self.view_mode, 56)

        self.divider = Static("│", id="table_divider")
        self.divider.styles.width = 1
        self.divider.styles.min_width = 1
        self.divider.styles.max_width = 1
        self.divider.styles.height = "100%"

        self.sample_table = SampleMatrixTable(
            id="sample_table",
            backend=sample_backend,
            column_labels=sample_cols,
            cursor_type="cell",
            zebra_stripes=True,
            show_row_labels=False,
            show_cursor=True,
            null_rep="...",
            live_row_count_provider=lambda: len(self.records),
            is_fixed_pane=False,
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
        self.fixed_table.sync_dimensions()
        self.sample_table.sync_dimensions()
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
                saved_x=self.sample_table.get_current_scroll_x(),
            )
            self.fixed_table.scroll_to_safe(y=self._viewport_scroll_y)

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
        """Pull newly streamed Handle 1 sites into FixedArrowBuffer without heavy UI rebuilds."""
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
            saved_x = self.sample_table.get_current_scroll_x()
            saved_y = self._viewport_scroll_y
            active_count = self._get_active_row_count()
            safe_row = min(self.current_row_idx, active_count - 1) if active_count else 0
            self.current_row_idx = safe_row

            self._is_internal_update = True
            try:
                if getattr(self.fixed_table, "backend", None) is None:
                    self._refresh_fixed_backend()
                else:
                    self.fixed_table.sync_dimensions()
                    self.fixed_table.refresh()
                if active_count:
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                self.fixed_table.scroll_to_safe(y=saved_y)
            except Exception:
                pass
            finally:
                self._is_internal_update = False

            if len(self.records) < self._get_visible_row_count():
                self._sync_sample_viewport_window(saved_y, saved_x=saved_x)

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

    def stop_timers(self) -> None:
        self._split_view_closing = True

    def on_unmount(self) -> None:
        self.stop_timers()

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
        table: _PassiveSplitTable,
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
            table.cursor_coordinate = Coordinate(row, col)

    def _sync_sample_viewport_window(
        self,
        viewport_top: int,
        saved_x: Optional[float] = None,
        force_rebind: bool = False,
    ) -> None:
        """
        Manually fill SampleMatrixTable's fixed viewport buffer for display rows
        [viewport_top, viewport_top + viewport_rows). Keeps sample_table.scroll_y pinned at 0
        and never replaces sample_table.backend during steady scrolling or resize.
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

        prev_backend = getattr(self.sample_table, "backend", None)
        x_to_keep = self.sample_table.get_current_scroll_x() if saved_x is None else saved_x
        local_row = self._get_local_sample_cursor_row()
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0

        self.sample_buffer.reset(self.records, samples=self.samples)

        self._is_internal_update = True
        try:
            if force_rebind or prev_backend is None:
                self._refresh_sample_backend()
            else:
                _clear_table_render_caches(self.sample_table)
                self.sample_table.sync_dimensions()
            if self.records:
                self._move_table_cursor(self.sample_table, row=local_row, column=safe_col, scroll=False)
            self.sample_table.scroll_to_safe(x=x_to_keep, y=0)
            self.sample_table.refresh()
        finally:
            self._is_internal_update = False

        if (
            unhydrated_global_indices
            and self.reader is not None
            and self.samples
            and self._subset_records is None
        ):
            if hasattr(self.reader, "request_sample_indices"):
                self.reader.request_sample_indices(unhydrated_global_indices)
            elif hasattr(self.reader, "request_sample_hydration"):
                req_start = min(unhydrated_global_indices)
                req_span = max(unhydrated_global_indices) - req_start + 1
                self.reader.request_sample_hydration(req_start, req_span)

    def _command_tables_scroll_y(self, target_y: int) -> None:
        """Align FixedVariantTable scroll_y and SampleMatrixTable fixed viewport window to target_y."""
        max_y = self._get_max_scroll_y()
        clamped_y = max(0, min(max_y, int(target_y)))
        saved_x = self.sample_table.get_current_scroll_x()

        self._sync_sample_viewport_window(clamped_y, saved_x=saved_x)

        self._is_internal_update = True
        try:
            self.fixed_table.scroll_to_safe(y=clamped_y)
            self.sample_table.scroll_to_safe(x=saved_x, y=0)
        finally:
            self._is_internal_update = False

    def _request_viewport_hydration(self, start_row: int) -> None:
        """Ask Handle 2 to hydrate only global rows mapped to the visible viewport."""
        if not self.reader or not self.samples or self._subset_records is not None:
            return
        missing_global = [
            self._sample_window_global_indices[i]
            for i, rec in enumerate(self.records)
            if i < len(self._sample_window_global_indices) and not getattr(rec, "samples_loaded", True)
        ]
        if missing_global:
            if hasattr(self.reader, "request_sample_indices"):
                self.reader.request_sample_indices(missing_global)
            elif hasattr(self.reader, "request_sample_hydration"):
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

        if self._is_main_stream_view and self._active_global_indices is None:
            while self._get_active_row_count() <= target_row + 25:
                needed = max(100, target_row - self._get_active_row_count() + 50)
                if not self.fetch_more_rows(needed):
                    break

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

        saved_x = self.sample_table.get_current_scroll_x()
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

        try:
            if sync_fixed and getattr(self.fixed_table, "row_count", 0) > target_row:
                self._move_table_cursor(self.fixed_table, row=target_row, scroll=False)
            if sync_sample and getattr(self.sample_table, "row_count", 0) > local_row:
                self._move_table_cursor(self.sample_table, row=local_row, column=safe_col, scroll=False)
            self.fixed_table.scroll_to_safe(y=target_y)
            self.sample_table.scroll_to_safe(x=saved_x, y=0)
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
        """Move sample cursor horizontally across SampleMatrixTable and scroll viewport deterministically."""
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
                    scroll=(horizontal_align is None),
                )
            if horizontal_align == "home":
                self.sample_table.scroll_to_safe(x=0, y=0)
            elif horizontal_align == "end":
                max_x = self.sample_table.get_effective_max_scroll_x()
                self.sample_table.scroll_to_safe(x=max_x, y=0)
            else:
                if getattr(self.sample_table, "scroll_y", 0) != 0:
                    self.sample_table.scroll_to_safe(y=0)
        finally:
            self._is_internal_update = False

        self._notify_selection(self.current_row_idx, self.current_sample_idx)

    # --- Data Loading, Filtering, View Modes, and In-Place Hydration ---

    def fetch_more_rows(self, batch_size: int = 100) -> bool:
        """Pull newly streamed site rows into FixedArrowBuffer without blocking the UI event loop."""
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
            saved_x = self.sample_table.get_current_scroll_x()
            saved_y = self._viewport_scroll_y
            active_count = self._get_active_row_count()
            safe_row = min(self.current_row_idx, active_count - 1) if active_count else 0

            try:
                if getattr(self.fixed_table, "backend", None) is None:
                    self._refresh_fixed_backend()
                else:
                    self.fixed_table.sync_dimensions()
                    self.fixed_table.refresh()
                if active_count:
                    self._move_table_cursor(self.fixed_table, row=safe_row, scroll=False)
                self.fixed_table.scroll_to_safe(y=saved_y)
            finally:
                self._is_internal_update = False

            if len(self.records) < self._get_visible_row_count():
                self._sync_sample_viewport_window(saved_y, saved_x=saved_x)

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
        if getattr(self, "is_attached", False):
            try:
                if getattr(self.app, "_vcfscape_closing", False):
                    return
            except (NoActiveAppError, LookupError):
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
                self.sample_table.refresh()

        if fixed_meta_changed:
            _clear_table_render_caches(self.fixed_table)
            self.fixed_table.refresh()

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
            self.fixed_table.scroll_to_safe(y=0)
        finally:
            self._is_internal_update = False

        self._sync_sample_viewport_window(0, saved_x=0)
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
            self.fixed_table.scroll_to_safe(y=0)
        finally:
            self._is_internal_update = False

        self._sync_sample_viewport_window(0, saved_x=0)
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
            self.fixed_table.scroll_to_safe(y=saved_y)
        finally:
            self._is_internal_update = False

    def set_format_tag(self, tag: str):
        self.format_tag = tag.upper()
        saved_x = self.sample_table.get_current_scroll_x()
        local_row = self._get_local_sample_cursor_row()
        safe_col = max(0, min(len(self.samples) - 1, self.current_sample_idx)) if self.samples else 0
        _clear_table_render_caches(self.sample_table)
        if getattr(self.sample_table, "backend", None) is None:
            self._refresh_sample_backend()
        if self.records:
            self._move_table_cursor(self.sample_table, row=local_row, column=safe_col, scroll=False)
        self.sample_table.scroll_to_safe(x=saved_x, y=0)
        try:
            self.sample_table.refresh()
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
                saved_x=self.sample_table.get_current_scroll_x(),
            )

    def _handle_table_click(
        self,
        table: _PassiveSplitTable,
        data_row: int,
        col_idx: int,
    ) -> None:
        if self._rebuilding or self._is_fetching_more or self._is_internal_update:
            return
        if table.id == "fixed_table":
            self.set_active_row(int(data_row), sync_fixed=True, sync_sample=True)
        elif table.id == "sample_table":
            target_display_row = self._sample_window_start + int(data_row)
            if self.samples:
                self.current_sample_idx = max(0, min(len(self.samples) - 1, int(col_idx)))
            self.set_active_row(target_display_row, sync_fixed=True, sync_sample=True)
        try:
            self.focus()
        except Exception:
            pass

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
