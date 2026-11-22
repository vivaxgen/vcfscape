"""
Dual Buffered PyArrow Backends for FastDataTable:
1. FixedArrowBuffer: Columnar PyArrow buffer fed by Handle 1 (cyvcf2 samples=[]) for
   FixedVariantTable, supporting zero-copy view-mode column projections.
2. SampleArrowBuffer: Lightweight single-tag PyArrow buffer fed by Handle 2 (full-sample
   LRU hydrator) for SampleMatrixTable, supporting "..." unhydrated placeholders,
   in-place row hydration without backend swaps, and lazy switching across GT / DP / AD / GQ.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from vcfscape.core.vcf_reader import VariantRecord

try:
    import pyarrow as pa
    HAS_PYARROW = True
except ImportError:
    pa = None  # type: ignore
    HAS_PYARROW = False

try:
    from textual_fastdatatable import ArrowBackend
    HAS_FASTDATATABLE = True
except ImportError:
    try:
        from textual_fastdatatable.backends.arrow import ArrowBackend
        HAS_FASTDATATABLE = True
    except ImportError:
        try:
            from textual_fastdatatable.backend import ArrowBackend
            HAS_FASTDATATABLE = True
        except ImportError:
            ArrowBackend = None  # type: ignore
            HAS_FASTDATATABLE = False


FIXED_ALL_COLUMNS = [
    "CHROM",
    "POS",
    "ID",
    "REF",
    "ALT",
    "QUAL",
    "FILTER",
    "INFO",
    "FORMAT",
    "GENE",
]

FIXED_VIEW_MODE_COLUMNS: Dict[str, List[str]] = {
    "normal": ["CHROM", "POS", "REF", "ALT", "QUAL", "FILTER", "GENE"],
    "compact": ["CHROM", "POS", "REF", "ALT"],
    "essential": ["CHROM", "POS"],
    "raw": ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"],
}

SAMPLE_FORMAT_TAGS = ("GT", "DP", "AD", "GQ")


def _extract_fixed_columns(records: List[VariantRecord]) -> Dict[str, List[Any]]:
    cols: Dict[str, List[Any]] = {name: [] for name in FIXED_ALL_COLUMNS}
    for r in records:
        qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
        info_short = f"GENE={r.gene};MUT={r.mutation}"
        fmt_short = ":".join(r.format_keys[:3]) if r.format_keys else "GT"
        cols["CHROM"].append(r.chrom)
        cols["POS"].append(int(r.pos))
        cols["ID"].append(r.var_id or ".")
        cols["REF"].append(r.ref)
        cols["ALT"].append(r.alt_str)
        cols["QUAL"].append(qual_str)
        cols["FILTER"].append(r.filter)
        cols["INFO"].append(info_short)
        cols["FORMAT"].append(fmt_short)
        cols["GENE"].append(r.gene)
    return cols


class FixedArrowBuffer:
    """
    Buffered PyArrow table for FixedVariantTable (Handle 1 site metadata).
    Accumulates streaming site chunks and exposes zero-copy PyArrow column projections
    for Normal, Compact, Essential, and Raw view modes.
    """

    def __init__(self, records: Optional[List[VariantRecord]] = None):
        self._columns: Dict[str, List[Any]] = {name: [] for name in FIXED_ALL_COLUMNS}
        self._table: Optional[Any] = None
        if records:
            self.append_records(records)
        else:
            self._rebuild_empty_table()

    @property
    def row_count(self) -> int:
        return len(self._columns["CHROM"])

    def _rebuild_empty_table(self) -> None:
        if not HAS_PYARROW:
            self._table = None
            return
        arrays = {
            "CHROM": pa.array([], type=pa.string()),
            "POS": pa.array([], type=pa.int64()),
            "ID": pa.array([], type=pa.string()),
            "REF": pa.array([], type=pa.string()),
            "ALT": pa.array([], type=pa.string()),
            "QUAL": pa.array([], type=pa.string()),
            "FILTER": pa.array([], type=pa.string()),
            "INFO": pa.array([], type=pa.string()),
            "FORMAT": pa.array([], type=pa.string()),
            "GENE": pa.array([], type=pa.string()),
        }
        self._table = pa.table(arrays)

    def reset(self, records: List[VariantRecord]) -> None:
        self._columns = {name: [] for name in FIXED_ALL_COLUMNS}
        self._table = None
        if records:
            self.append_records(records)
        else:
            self._rebuild_empty_table()

    def append_records(self, records: List[VariantRecord]) -> None:
        if not records:
            if self._table is None:
                self._rebuild_empty_table()
            return

        batch_cols = _extract_fixed_columns(records)
        for col_name, values in batch_cols.items():
            self._columns[col_name].extend(values)

        if HAS_PYARROW:
            batch_arrays = {
                "CHROM": pa.array(batch_cols["CHROM"], type=pa.string()),
                "POS": pa.array(batch_cols["POS"], type=pa.int64()),
                "ID": pa.array(batch_cols["ID"], type=pa.string()),
                "REF": pa.array(batch_cols["REF"], type=pa.string()),
                "ALT": pa.array(batch_cols["ALT"], type=pa.string()),
                "QUAL": pa.array(batch_cols["QUAL"], type=pa.string()),
                "FILTER": pa.array(batch_cols["FILTER"], type=pa.string()),
                "INFO": pa.array(batch_cols["INFO"], type=pa.string()),
                "FORMAT": pa.array(batch_cols["FORMAT"], type=pa.string()),
                "GENE": pa.array(batch_cols["GENE"], type=pa.string()),
            }
            chunk_table = pa.table(batch_arrays)
            if self._table is None or self._table.num_rows == 0:
                self._table = chunk_table
            else:
                self._table = pa.concat_tables([self._table, chunk_table])

    def get_columns_for_mode(self, view_mode: str) -> List[str]:
        return list(FIXED_VIEW_MODE_COLUMNS.get(view_mode.lower(), FIXED_VIEW_MODE_COLUMNS["normal"]))

    def get_arrow_table(self, view_mode: str = "normal") -> Optional[Any]:
        if not HAS_PYARROW:
            return None
        if self._table is None:
            self._rebuild_empty_table()
        cols = self.get_columns_for_mode(view_mode)
        return self._table.select(cols)

    def create_backend(self, view_mode: str = "normal") -> Optional[Any]:
        if not (HAS_PYARROW and HAS_FASTDATATABLE):
            return None
        tbl = self.get_arrow_table(view_mode)
        return ArrowBackend(tbl) if tbl is not None else None


class SampleArrowBuffer:
    """
    Lightweight single-active-tag PyArrow buffer for SampleMatrixTable.
    Tracks loaded records and hydrated row indices without eagerly duplicating
    4 FORMAT tag column sets across every sample, and provides direct O(1) cell/row
    accessors for in-place StyledArrowBackend rendering during hydration.
    """

    def __init__(
        self,
        samples: Optional[List[str]] = None,
        records: Optional[List[VariantRecord]] = None,
        visible_samples: Optional[List[str]] = None,
    ):
        resolved = samples if samples is not None else visible_samples
        self.visible_samples: List[str] = list(resolved or [])
        self._records: List[VariantRecord] = []
        self._hydrated_rows: set[int] = set()
        self._cached_tag: Optional[str] = None
        self._cached_table: Optional[Any] = None
        if records:
            self.append_records(records)

    @property
    def samples(self) -> List[str]:
        return self.visible_samples

    @property
    def row_count(self) -> int:
        return len(self._records)

    def is_row_hydrated(self, row_idx: int) -> bool:
        return row_idx in self._hydrated_rows

    def get_cell_value(self, row_idx: int, col_idx: int, format_tag: str = "GT") -> str:
        if not self.visible_samples:
            return "-"
        if not (0 <= row_idx < len(self._records)) or not (0 <= col_idx < len(self.visible_samples)):
            return "."
        rec = self._records[row_idx]
        if not getattr(rec, "samples_loaded", True):
            return "..."
        tag_key = format_tag.upper() if format_tag.upper() in SAMPLE_FORMAT_TAGS else "GT"
        sample_id = self.visible_samples[col_idx]
        return str(rec.sample_data.get(sample_id, {}).get(tag_key, "."))

    def get_row_values(self, row_idx: int, format_tag: str = "GT") -> List[str]:
        if not self.visible_samples:
            return ["-"]
        if not (0 <= row_idx < len(self._records)):
            return ["." for _ in self.visible_samples]
        rec = self._records[row_idx]
        if not getattr(rec, "samples_loaded", True):
            return ["..." for _ in self.visible_samples]
        tag_key = format_tag.upper() if format_tag.upper() in SAMPLE_FORMAT_TAGS else "GT"
        sdata = rec.sample_data
        return [str(sdata.get(s, {}).get(tag_key, ".")) for s in self.visible_samples]

    def reset(
        self,
        records: List[VariantRecord],
        samples: Optional[List[str]] = None,
        visible_samples: Optional[List[str]] = None,
    ) -> None:
        resolved = samples if samples is not None else visible_samples
        if resolved is not None:
            self.visible_samples = list(resolved)
        self._records = []
        self._hydrated_rows.clear()
        self._cached_tag = None
        self._cached_table = None
        if records:
            self.append_records(records)

    def set_visible_samples(self, visible_samples: List[str], records: List[VariantRecord]) -> None:
        self.reset(records, visible_samples=visible_samples)

    def append_records(self, records: List[VariantRecord]) -> None:
        if not records:
            return
        start_idx = len(self._records)
        self._records.extend(records)
        for offset, rec in enumerate(records):
            if getattr(rec, "samples_loaded", True):
                self._hydrated_rows.add(start_idx + offset)
        self._cached_tag = None
        self._cached_table = None

    def hydrate_rows(self, row_indices: List[int], records_by_idx: Dict[int, VariantRecord]) -> bool:
        """Record newly hydrated VariantRecords in place without rebuilding full multi-tag tables."""
        updated = False
        for row_idx in row_indices:
            if not (0 <= row_idx < len(self._records)) or row_idx in self._hydrated_rows:
                continue
            rec = records_by_idx.get(row_idx)
            if rec is None or not getattr(rec, "samples_loaded", False):
                continue
            self._records[row_idx] = rec
            self._hydrated_rows.add(row_idx)
            updated = True
        if updated:
            # Invalidate cached Arrow table lazily; live StyledArrowBackend reads updated rows immediately.
            self._cached_table = None
        return updated

    def get_arrow_table(self, format_tag: str = "GT") -> Optional[Any]:
        if not HAS_PYARROW:
            return None
        tag_key = format_tag.upper() if format_tag.upper() in SAMPLE_FORMAT_TAGS else "GT"
        if self._cached_table is not None and self._cached_tag == tag_key:
            return self._cached_table

        row_count = len(self._records)
        if not self.visible_samples:
            self._cached_table = pa.table(
                {"Samples": pa.array(["-"] * row_count, type=pa.string())}
            )
            self._cached_tag = tag_key
            return self._cached_table

        col_lists: Dict[str, List[str]] = {s: [] for s in self.visible_samples}
        for row_idx in range(row_count):
            vals = self.get_row_values(row_idx, tag_key)
            for col_idx, s in enumerate(self.visible_samples):
                col_lists[s].append(vals[col_idx])

        arrays = {s: pa.array(col_lists[s], type=pa.string()) for s in self.visible_samples}
        self._cached_table = pa.table(arrays)
        self._cached_tag = tag_key
        return self._cached_table

    def create_backend(self, format_tag: str = "GT") -> Optional[Any]:
        if not (HAS_PYARROW and HAS_FASTDATATABLE):
            return None
        tbl = self.get_arrow_table(format_tag)
        return ArrowBackend(tbl) if tbl is not None else None
