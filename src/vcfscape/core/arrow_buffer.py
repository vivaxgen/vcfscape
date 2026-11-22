"""
Dual Buffered PyArrow Backends for FastDataTable:
1. FixedArrowBuffer: Columnar PyArrow buffer fed by Handle 1 (cyvcf2 samples=[]) for
   FixedVariantTable, supporting zero-copy view-mode column projections.
2. SampleArrowBuffer: Lightweight single-tag PyArrow buffer fed by Handle 2 (full-sample
   LRU hydrator) for SampleMatrixTable, supporting "..." unhydrated placeholders,
   in-place row hydration without backend swaps, and lazy switching across GT / DP / AD / GQ.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from vcfscape.core.malaria_db import MalariaAnnotationDB
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


class FixedArrowBuffer:
    """
    Full-VCF Columnar PyArrow buffer for FixedVariantTable (fed by Handle 1 sites):
    - Stores core Handle 1 fields across all streamed rows without giant per-row INFO/FORMAT dicts.
    - Tracks lazy INFO/FORMAT/GENE overrides populated only for visible/hydrated rows.
    - Exposes zero-copy PyArrow projections, filtered `.take(indices)` subsets, and fast
      in-memory filtering / genomic region lookups directly on loaded columnar arrays.
    """

    def __init__(self, records: Optional[Sequence[Any]] = None):
        self._columns: Dict[str, List[Any]] = {name: [] for name in FIXED_ALL_COLUMNS}
        self._qual_values: List[Optional[float]] = []
        self._is_indel: List[bool] = []
        self._is_multiallelic: List[bool] = []
        self._is_drug: List[bool] = []
        self._lazy_info: Dict[int, str] = {}
        self._lazy_format: Dict[int, str] = {}
        self._lazy_gene: Dict[int, str] = {}
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

    def reset(self, records: Sequence[Any]) -> None:
        self._columns = {name: [] for name in FIXED_ALL_COLUMNS}
        self._qual_values = []
        self._is_indel = []
        self._is_multiallelic = []
        self._is_drug = []
        self._lazy_info.clear()
        self._lazy_format.clear()
        self._lazy_gene.clear()
        self._table = None
        if records:
            self.append_records(records)
        else:
            self._rebuild_empty_table()

    def append_records(self, records: Sequence[Any]) -> None:
        if not records:
            if self._table is None:
                self._rebuild_empty_table()
            return

        start_idx = self.row_count
        batch_cols: Dict[str, List[Any]] = {name: [] for name in FIXED_ALL_COLUMNS}
        batch_qual: List[Optional[float]] = []
        batch_indel: List[bool] = []
        batch_multi: List[bool] = []
        batch_drug: List[bool] = []

        lookup = MalariaAnnotationDB.lookup

        for offset, r in enumerate(records):
            row_idx = start_idx + offset
            qual_val = r.qual
            qual_str = f"{qual_val:.0f}" if qual_val is not None else "."
            alt_str = r.alt_str if hasattr(r, "alt_str") else ",".join(r.alt)

            if isinstance(r, VariantRecord):
                gene = r.gene
                is_drug = bool(r.drug_annotation)
                info_short = f"GENE={gene};MUT={r.mutation}" if r.info or is_drug else "."
                fmt_short = ":".join(r.format_keys[:3]) if r.format_keys else "GT"
                if r.info or r.samples_loaded:
                    self._lazy_info[row_idx] = info_short
                if r.format_keys:
                    self._lazy_format[row_idx] = fmt_short
                if gene != ".":
                    self._lazy_gene[row_idx] = gene
            else:
                ann = lookup(r.chrom, r.pos, r.ref, alt_str)
                is_drug = ann is not None
                gene = ann.gene if ann is not None else "."
                info_short = "."
                fmt_short = "GT"

            batch_cols["CHROM"].append(r.chrom)
            batch_cols["POS"].append(int(r.pos))
            batch_cols["ID"].append(r.var_id or ".")
            batch_cols["REF"].append(r.ref)
            batch_cols["ALT"].append(alt_str)
            batch_cols["QUAL"].append(qual_str)
            batch_cols["FILTER"].append(r.filter)
            batch_cols["INFO"].append(info_short)
            batch_cols["FORMAT"].append(fmt_short)
            batch_cols["GENE"].append(gene)

            batch_qual.append(qual_val)
            batch_indel.append(bool(r.is_indel))
            batch_multi.append(bool(r.is_multiallelic))
            batch_drug.append(is_drug)

        for col_name, values in batch_cols.items():
            self._columns[col_name].extend(values)
        self._qual_values.extend(batch_qual)
        self._is_indel.extend(batch_indel)
        self._is_multiallelic.extend(batch_multi)
        self._is_drug.extend(batch_drug)

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

    def update_row_metadata(self, row_idx: int, rec: VariantRecord) -> bool:
        """Lazily update INFO/FORMAT/GENE metadata for a hydrated visible row."""
        if not (0 <= row_idx < self.row_count):
            return False
        changed = False
        gene = rec.gene
        info_short = f"GENE={gene};MUT={rec.mutation}"
        fmt_short = ":".join(rec.format_keys[:3]) if rec.format_keys else "GT"
        if self._lazy_info.get(row_idx) != info_short:
            self._lazy_info[row_idx] = info_short
            changed = True
        if self._lazy_format.get(row_idx) != fmt_short:
            self._lazy_format[row_idx] = fmt_short
            changed = True
        if gene != "." and self._columns["GENE"][row_idx] != gene:
            self._columns["GENE"][row_idx] = gene
            self._lazy_gene[row_idx] = gene
            changed = True
        if rec.drug_annotation and not self._is_drug[row_idx]:
            self._is_drug[row_idx] = True
            changed = True
        return changed

    def is_drug_row(self, row_idx: int) -> bool:
        return 0 <= row_idx < len(self._is_drug) and self._is_drug[row_idx]

    def get_columns_for_mode(self, view_mode: str) -> List[str]:
        return list(FIXED_VIEW_MODE_COLUMNS.get(view_mode.lower(), FIXED_VIEW_MODE_COLUMNS["normal"]))

    def get_cell_value(self, row_idx: int, col_name: str) -> Any:
        if not (0 <= row_idx < self.row_count):
            return "."
        if col_name == "INFO":
            return self._lazy_info.get(row_idx, self._columns["INFO"][row_idx])
        if col_name == "FORMAT":
            return self._lazy_format.get(row_idx, self._columns["FORMAT"][row_idx])
        if col_name == "GENE":
            return self._lazy_gene.get(row_idx, self._columns["GENE"][row_idx])
        col_data = self._columns.get(col_name)
        return col_data[row_idx] if col_data is not None else "."

    def get_row_values(self, row_idx: int, view_mode: str = "normal") -> List[Any]:
        cols = self.get_columns_for_mode(view_mode)
        if not (0 <= row_idx < self.row_count):
            return ["." for _ in cols]
        return [self.get_cell_value(row_idx, col) for col in cols]

    def filter_indices(
        self,
        min_qual: Optional[float] = None,
        variant_type: Optional[str] = None,
        filter_status: Optional[str] = None,
        search_query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[int]:
        """Filter directly across in-memory FixedArrowBuffer columns and return matching row indices."""
        n = self.row_count
        if n == 0:
            return []

        chroms = self._columns["CHROM"]
        pos_list = self._columns["POS"]
        var_ids = self._columns["ID"]
        refs = self._columns["REF"]
        alts = self._columns["ALT"]
        filters = self._columns["FILTER"]
        genes = self._columns["GENE"]
        quals = self._qual_values
        indels = self._is_indel
        multis = self._is_multiallelic
        drugs = self._is_drug

        vtype = variant_type.upper() if variant_type else "ALL"
        check_type = vtype != "ALL"
        check_filter = bool(filter_status and filter_status != "ALL")
        q_lower = search_query.lower() if search_query else None

        matched: List[int] = []
        for i in range(n):
            if min_qual is not None:
                qv = quals[i]
                if qv is not None and qv < min_qual:
                    continue
            if check_type:
                if vtype == "SNP" and indels[i]:
                    continue
                if vtype == "INDEL" and not indels[i]:
                    continue
                if vtype == "MULTI_ALLELIC" and not multis[i]:
                    continue
                if vtype == "DRUG_RESISTANT" and not drugs[i]:
                    continue
            if check_filter and filters[i] != filter_status:
                continue
            if q_lower is not None:
                gene_val = self._lazy_gene.get(i, genes[i]).lower()
                if (
                    q_lower in chroms[i].lower()
                    or q_lower in str(pos_list[i])
                    or q_lower in var_ids[i].lower()
                    or q_lower in gene_val
                ):
                    pass
                else:
                    ann = MalariaAnnotationDB.lookup(chroms[i], pos_list[i], refs[i], alts[i])
                    if ann is None or (
                        q_lower not in ann.drug.lower()
                        and q_lower not in ann.mutation.lower()
                        and q_lower not in ann.gene.lower()
                    ):
                        continue
            matched.append(i)
            if limit is not None and len(matched) >= limit:
                break
        return matched

    def find_region_indices(
        self,
        chrom: str,
        start: int,
        end: int,
        limit: Optional[int] = 500,
    ) -> List[int]:
        """Find matching global row indices for chrom:start-end directly from core columns."""
        n = self.row_count
        if n == 0:
            return []
        chroms = self._columns["CHROM"]
        pos_list = self._columns["POS"]
        matched: List[int] = []
        for i in range(n):
            if chroms[i] == chrom and start <= pos_list[i] <= end:
                matched.append(i)
                if limit is not None and len(matched) >= limit:
                    break
        return matched

    def get_arrow_table(
        self,
        view_mode: str = "normal",
        row_indices: Optional[List[int]] = None,
    ) -> Optional[Any]:
        if not HAS_PYARROW:
            return None
        if self._table is None:
            self._rebuild_empty_table()
        cols = self.get_columns_for_mode(view_mode)
        projected = self._table.select(cols)
        if row_indices is not None:
            if not row_indices:
                return projected.slice(0, 0)
            return projected.take(row_indices)
        return projected

    def create_backend(
        self,
        view_mode: str = "normal",
        row_indices: Optional[List[int]] = None,
    ) -> Optional[Any]:
        if not (HAS_PYARROW and HAS_FASTDATATABLE):
            return None
        tbl = self.get_arrow_table(view_mode, row_indices=row_indices)
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
