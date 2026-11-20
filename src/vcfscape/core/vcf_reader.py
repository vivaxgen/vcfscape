"""
High-performance VCF Reader with Dual cyvcf2 Handles & Pre-Open Index Guard:
1. Enforces a pre-open >100 MB unindexed file check (prompts user to create an index and exits without opening).
2. Handle 1 (Site Reader): Opens with cyvcf2.VCF(path, samples=[]) to stream site-level metadata
   for FixedVariantTable, total counting, filtering, and locus jumping at maximum C speed.
3. Handle 2 (Sample Reader): Opens full-sample cyvcf2.VCF(path) in parallel to hydrate sample
   genotypes, depths, AD, and GQ into a thread-safe LRU cache with Tabix / SparseIndex priority seeking.
"""

import os
import gzip
import time
import threading
from collections import deque
from typing import List, Dict, Any, Optional, Tuple, Callable

from vcfscape.core.malaria_db import MalariaAnnotationDB, MarkerAnnotation
from vcfscape.core.indexer import SparseVcfIndex, RecordLruCache

try:
    import cyvcf2
    HAS_CYVCF2 = True
except ImportError:
    HAS_CYVCF2 = False

LARGE_UNINDEXED_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB


class UnindexedLargeVcfError(Exception):
    """Raised before opening a VCF file when size > 100 MB and no index is available."""

    def __init__(self, filepath: str, file_size_bytes: int, suggested_command: str):
        self.filepath = os.path.abspath(filepath)
        self.file_size_bytes = file_size_bytes
        self.suggested_command = suggested_command
        size_mb = file_size_bytes / (1024 * 1024)
        super().__init__(
            f"VCF file '{os.path.basename(self.filepath)}' is {size_mb:.1f} MB (> 100 MB) and has no index.\n"
            f"Opening large unindexed VCF files is disabled to prevent UI stalls.\n"
            f"Please build an index first, e.g.:\n  {suggested_command}"
        )


def has_vcf_index(filepath: str) -> bool:
    """
    Check if an index exists for the given VCF/BCF file using filesystem checks ONLY.
    Does not open the VCF file itself.
    """
    abs_path = os.path.abspath(filepath)
    if os.path.exists(f"{abs_path}.tbi") or os.path.exists(f"{abs_path}.csi"):
        return True
    lower = abs_path.lower()
    if not (lower.endswith(".gz") or lower.endswith(".bgz") or lower.endswith(".bcf")):
        if SparseVcfIndex.has_cached_index(abs_path):
            return True
    return False


def check_vcf_index_requirement(
    filepath: str,
    max_unindexed_bytes: int = LARGE_UNINDEXED_THRESHOLD_BYTES,
) -> None:
    """
    Enforce index requirement for VCF files larger than 100 MB before opening the file.
    Raises UnindexedLargeVcfError if size > max_unindexed_bytes and no index exists.
    """
    abs_path = os.path.abspath(filepath)
    if not os.path.exists(abs_path):
        return
    file_size = os.path.getsize(abs_path)
    if file_size > max_unindexed_bytes and not has_vcf_index(abs_path):
        lower = abs_path.lower()
        if lower.endswith(".bcf"):
            cmd = f'bcftools index "{abs_path}"'
        elif lower.endswith(".gz") or lower.endswith(".bgz"):
            cmd = f'tabix -p vcf "{abs_path}"  # or: bcftools index "{abs_path}"'
        else:
            cmd = f'bgzip -c "{abs_path}" > "{abs_path}.gz" && tabix -p vcf "{abs_path}.gz"'
        raise UnindexedLargeVcfError(abs_path, file_size, cmd)


class VariantRecord:
    """Normalized internal representation of a VCF variant row."""
    __slots__ = (
        "chrom", "pos", "var_id", "ref", "alt", "qual", "filter", "info",
        "format_keys", "sample_data", "genotypes", "depths", "ad",
        "is_multiallelic", "is_indel", "var_type", "drug_annotation",
        "gene", "impact", "mutation", "drug", "samples_loaded"
    )

    def __init__(
        self,
        chrom: str,
        pos: int,
        var_id: str,
        ref: str,
        alt: List[str],
        qual: Optional[float],
        filter_str: str,
        info: Dict[str, Any],
        format_keys: List[str],
        sample_data: Dict[str, Dict[str, Any]],
        genotypes: Dict[str, Tuple[int, ...]],
        depths: Dict[str, int],
        ad: Dict[str, List[int]],
        samples_loaded: bool = True,
    ):
        self.chrom = chrom
        self.pos = pos
        self.var_id = var_id or "."
        self.ref = ref
        self.alt = alt
        self.qual = qual
        self.filter = filter_str
        self.info = info
        self.format_keys = format_keys
        self.sample_data = sample_data
        self.genotypes = genotypes
        self.depths = depths
        self.ad = ad
        self.samples_loaded = samples_loaded

        # Derived properties
        self.is_multiallelic = len(self.alt) > 1
        self.is_indel = len(self.ref) != 1 or any(len(a) != 1 for a in self.alt)

        # Variant type classification
        if self.is_multiallelic and self.is_indel:
            self.var_type = "Multi-Allelic INDEL"
        elif self.is_multiallelic:
            self.var_type = "Multi-Allelic SNP"
        elif self.is_indel:
            self.var_type = "INDEL"
        else:
            self.var_type = "SNP"

        # Annotation against malaria knowledgebase
        self.drug_annotation: Optional[MarkerAnnotation] = MalariaAnnotationDB.lookup(
            self.chrom, self.pos, self.ref, ",".join(self.alt)
        )

        # Extract Gene and Impact if present in INFO
        self.gene = str(self.info.get("GENE", (self.drug_annotation.gene if self.drug_annotation else ".")))
        self.impact = str(self.info.get("IMPACT", (self.drug_annotation.impact if self.drug_annotation else ".")))
        self.mutation = str(self.info.get("MUT", (self.drug_annotation.mutation if self.drug_annotation else ".")))
        self.drug = str(self.info.get("DRUG", (self.drug_annotation.drug if self.drug_annotation else ".")))

    def with_samples(self, payload: Dict[str, Any]) -> "VariantRecord":
        """Return a VariantRecord copy sharing site metadata with attached hydrated sample payload."""
        rec = VariantRecord.__new__(VariantRecord)
        rec.chrom = self.chrom
        rec.pos = self.pos
        rec.var_id = self.var_id
        rec.ref = self.ref
        rec.alt = self.alt
        rec.qual = self.qual
        rec.filter = self.filter
        rec.info = self.info
        rec.is_multiallelic = self.is_multiallelic
        rec.is_indel = self.is_indel
        rec.var_type = self.var_type
        rec.drug_annotation = self.drug_annotation
        rec.gene = self.gene
        rec.impact = self.impact
        rec.mutation = self.mutation
        rec.drug = self.drug

        rec.format_keys = payload.get("format_keys", self.format_keys)
        rec.sample_data = payload["sample_data"]
        rec.genotypes = payload["genotypes"]
        rec.depths = payload["depths"]
        rec.ad = payload["ad"]
        rec.samples_loaded = True
        return rec

    @property
    def alt_str(self) -> str:
        return ",".join(self.alt)

    @property
    def num_alleles(self) -> int:
        return 1 + len(self.alt)


def _parse_info_str(info_raw: str) -> Dict[str, Any]:
    info_dict: Dict[str, Any] = {}
    if info_raw and info_raw != ".":
        for item in info_raw.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                info_dict[k] = v
            else:
                info_dict[item] = True
    return info_dict


def parse_vcf_site_only(line: str) -> Optional[VariantRecord]:
    """Fast site-only line parser: splits only columns 0..8, completely skipping sample columns."""
    line = line.rstrip("\r\n")
    if not line or line.startswith("#"):
        return None

    parts = line.split("\t", 9)
    if len(parts) < 8:
        return None

    chrom = parts[0]
    try:
        pos = int(parts[1])
    except ValueError:
        return None

    var_id = parts[2]
    ref = parts[3]
    alt = parts[4].split(",") if parts[4] != "." else []
    try:
        qual = float(parts[5]) if parts[5] != "." else None
    except ValueError:
        qual = None
    filter_str = parts[6]
    info_dict = _parse_info_str(parts[7])
    format_keys = parts[8].split(":") if len(parts) > 8 and parts[8] else ["GT"]

    return VariantRecord(
        chrom=chrom,
        pos=pos,
        var_id=var_id,
        ref=ref,
        alt=alt,
        qual=qual,
        filter_str=filter_str,
        info=info_dict,
        format_keys=format_keys,
        sample_data={},
        genotypes={},
        depths={},
        ad={},
        samples_loaded=False,
    )


def parse_vcf_line(line: str, samples: List[str]) -> Optional[VariantRecord]:
    """Parse a single raw VCF line string into a full VariantRecord."""
    line = line.rstrip("\r\n")
    if not line or line.startswith("#"):
        return None

    parts = line.split("\t")
    if len(parts) < 8:
        return None

    chrom = parts[0]
    try:
        pos = int(parts[1])
    except ValueError:
        return None

    var_id = parts[2]
    ref = parts[3]
    alt = parts[4].split(",") if parts[4] != "." else []
    try:
        qual = float(parts[5]) if parts[5] != "." else None
    except ValueError:
        qual = None
    filter_str = parts[6]
    info_dict = _parse_info_str(parts[7])
    format_keys = parts[8].split(":") if len(parts) > 8 else ["GT"]

    sample_data: Dict[str, Dict[str, Any]] = {}
    genotypes: Dict[str, Tuple[int, ...]] = {}
    depths: Dict[str, int] = {}
    ad_dict: Dict[str, List[int]] = {}

    for idx, s in enumerate(samples):
        col_idx = 9 + idx
        raw_val = parts[col_idx] if col_idx < len(parts) else "./."
        sub_vals = raw_val.split(":")
        s_map = {}
        for fk_idx, fk in enumerate(format_keys):
            if fk_idx < len(sub_vals):
                s_map[fk] = sub_vals[fk_idx]
            else:
                s_map[fk] = "."
        sample_data[s] = s_map

        # Parse GT
        gt_str = s_map.get("GT", "./.")
        gt_alleles = []
        for a in gt_str.replace("|", "/").split("/"):
            try:
                gt_alleles.append(int(a))
            except ValueError:
                gt_alleles.append(-1)
        genotypes[s] = tuple(gt_alleles)

        # Parse DP
        try:
            dp_val = int(s_map.get("DP", 0))
        except ValueError:
            dp_val = 0
        depths[s] = dp_val

        # Parse AD
        ad_raw = s_map.get("AD", "")
        ad_list = []
        if ad_raw and ad_raw != ".":
            for x in ad_raw.split(","):
                try:
                    ad_list.append(int(x))
                except ValueError:
                    ad_list.append(0)
        ad_dict[s] = ad_list

    return VariantRecord(
        chrom=chrom,
        pos=pos,
        var_id=var_id,
        ref=ref,
        alt=alt,
        qual=qual,
        filter_str=filter_str,
        info=info_dict,
        format_keys=format_keys,
        sample_data=sample_data,
        genotypes=genotypes,
        depths=depths,
        ad=ad_dict,
        samples_loaded=True,
    )


def _site_record_from_cyvcf2(v: Any) -> VariantRecord:
    """Create lightweight site-only VariantRecord from a cyvcf2 variant (samples=[])."""
    alts = list(v.ALT) if v.ALT else []
    try:
        info_dict = dict(v.INFO) if v.INFO else {}
    except Exception:
        info_dict = {}
    v_format_keys = list(v.FORMAT) if v.FORMAT else ["GT"]

    return VariantRecord(
        chrom=v.CHROM,
        pos=int(v.POS),
        var_id=v.ID or ".",
        ref=v.REF,
        alt=alts,
        qual=float(v.QUAL) if v.QUAL is not None else None,
        filter_str=v.FILTER or "PASS",
        info=info_dict,
        format_keys=v_format_keys,
        sample_data={},
        genotypes={},
        depths={},
        ad={},
        samples_loaded=False,
    )


def _sample_payload_from_cyvcf2(v: Any, samples: List[str]) -> Dict[str, Any]:
    """Extract fast sample payload (GT, DP, AD, GQ) from a full-sample cyvcf2 variant."""
    v_format_keys = list(v.FORMAT) if v.FORMAT else ["GT"]
    sample_data: Dict[str, Dict[str, Any]] = {}
    genotypes: Dict[str, Tuple[int, ...]] = {}
    depths: Dict[str, int] = {}
    ad_dict: Dict[str, List[int]] = {}

    if not samples:
        return {
            "format_keys": v_format_keys,
            "sample_data": sample_data,
            "genotypes": genotypes,
            "depths": depths,
            "ad": ad_dict,
        }

    v_gt = v.genotypes if "GT" in v_format_keys or v.genotypes is not None else None
    dp_arr = v.format("DP") if "DP" in v_format_keys else None
    ad_arr = v.format("AD") if "AD" in v_format_keys else None
    gq_arr = v.format("GQ") if "GQ" in v_format_keys else None

    dp_list = dp_arr.reshape(-1).tolist() if dp_arr is not None else None
    gq_list = gq_arr.reshape(-1).tolist() if gq_arr is not None else None
    ad_list_all = ad_arr.tolist() if ad_arr is not None else None

    gt_len = len(v_gt) if v_gt is not None else 0
    dp_len = len(dp_list) if dp_list is not None else 0
    gq_len = len(gq_list) if gq_list is not None else 0
    ad_len = len(ad_list_all) if ad_list_all is not None else 0

    for idx, s in enumerate(samples):
        if idx < gt_len:
            raw_gt = v_gt[idx]
            # cyvcf2 genotypes entry ends with phased bool; alleles precede it
            alleles = raw_gt[:-1] if len(raw_gt) > 1 else raw_gt
            gt_tuple = tuple(int(g) for g in alleles) if alleles else (-1,)
            sep = "|" if (len(raw_gt) > 1 and raw_gt[-1] is True) else "/"
            gt_str = sep.join(str(g) if g >= 0 else "." for g in gt_tuple)
        else:
            gt_tuple = (-1,)
            gt_str = "./."

        genotypes[s] = gt_tuple

        raw_dp = int(dp_list[idx]) if idx < dp_len else -1
        dp_val = raw_dp if raw_dp >= 0 else 0
        depths[s] = dp_val

        raw_gq = int(gq_list[idx]) if idx < gq_len else -1
        gq_display: Any = raw_gq if raw_gq >= 0 else "."

        if idx < ad_len:
            ad_vals = [int(x) for x in ad_list_all[idx] if x >= 0]
        else:
            ad_vals = []
        ad_dict[s] = ad_vals

        sample_data[s] = {
            "GT": gt_str,
            "DP": dp_val if raw_dp >= 0 else ".",
            "AD": ",".join(str(x) for x in ad_vals) if ad_vals else ".",
            "GQ": gq_display,
        }

    return {
        "format_keys": v_format_keys,
        "sample_data": sample_data,
        "genotypes": genotypes,
        "depths": depths,
        "ad": ad_dict,
    }


def _full_record_from_cyvcf2(v: Any, samples: List[str]) -> VariantRecord:
    site = _site_record_from_cyvcf2(v)
    payload = _sample_payload_from_cyvcf2(v, samples)
    return site.with_samples(payload)


class VcfReader:
    """
    Dual-Handle VCF Parser interface:
    - Enforces >100 MB unindexed file check before opening any handle.
    - Handle 1 (`samples=[]`): Fast site-only streaming for FixedVariantTable, total count, filter, and region jump.
    - Handle 2 (full samples): Asynchronous LRU hydration + priority Tabix/SparseIndex fetch for SampleMatrixTable.
    """

    def __init__(self, filepath: str, lazy: bool = True, allow_unindexed_large: bool = False):
        self.filepath = os.path.abspath(filepath)
        if not allow_unindexed_large:
            check_vcf_index_requirement(self.filepath)

        lower = self.filepath.lower()
        self.is_gzipped = lower.endswith(".gz") or lower.endswith(".bgz")
        self.is_bcf = lower.endswith(".bcf")
        self.has_tabix = os.path.exists(f"{self.filepath}.tbi") or os.path.exists(f"{self.filepath}.csi")
        self.samples: List[str] = []
        self.contigs: List[str] = []
        self.header_lines: List[str] = []

        if HAS_CYVCF2:
            self.backend = "cyvcf2_dual_tabix" if self.has_tabix else "cyvcf2_dual"
        elif not (self.is_gzipped or self.is_bcf):
            self.backend = "indexed_vcf"
        else:
            self.backend = "gzipped_stream"

        self._sparse_index: Optional[SparseVcfIndex] = None
        self._sample_cache = RecordLruCache(maxsize=2500)
        self._site_records: List[VariantRecord] = []
        self._site_lock = threading.RLock()
        self._records: List[VariantRecord] = []  # Populated for full eager mode

        self._total_variants_count: Optional[int] = None
        self._site_stream_done = False
        self._site_thread: Optional[threading.Thread] = None
        self._sample_thread: Optional[threading.Thread] = None
        self._sample_cond = threading.Condition()
        self._priority_windows: deque[Tuple[int, int]] = deque()
        self._focus_row: int = 0
        self._stop_workers = False

        self._count_callbacks: List[Callable[[int], None]] = []
        self._progress_callbacks: List[Callable[[int], None]] = []
        self._hydration_callbacks: List[Callable[[List[int]], None]] = []

        # 1. Fast Header Extraction (< 15ms)
        self._load_header_only()

        # 2. Setup Sparse Index for uncompressed plain .vcf files
        if not self.is_gzipped and not self.is_bcf:
            if lazy:
                self._sparse_index = SparseVcfIndex(
                    self.filepath,
                    build_async=True,
                    on_progress=self._on_sparse_progress,
                    on_complete=self._on_sparse_complete,
                )
                if self._sparse_index.is_ready:
                    self._total_variants_count = self._sparse_index.total_records
            else:
                self._sparse_index = SparseVcfIndex(self.filepath, build_async=False)
                self._total_variants_count = self._sparse_index.total_records

        # 3. Start Dual Parsing Pipelines
        self._start_dual_pipelines(lazy=lazy)

        # 4. Eagerly hydrate small datasets or when lazy=False
        if not lazy or (self._total_variants_count is not None and self._total_variants_count <= 500):
            self._preload_all_records()

    def _open_file(self):
        if self.is_gzipped:
            return gzip.open(self.filepath, "rt", encoding="utf-8", errors="replace")
        return open(self.filepath, "r", encoding="utf-8", errors="replace")

    def _load_header_only(self):
        """Extracts samples, contigs, and metadata lines from the header."""
        self.samples.clear()
        self.contigs.clear()
        self.header_lines.clear()

        if self.is_bcf and HAS_CYVCF2:
            vcf_hdr = cyvcf2.VCF(self.filepath, samples=[])
            # Extract contigs & samples cleanly from BCF header
            raw_hdr = str(vcf_hdr.raw_header or "")
            for line in raw_hdr.splitlines():
                line = line.rstrip("\r\n")
                if not line:
                    continue
                self.header_lines.append(line)
                if line.startswith("##contig=<ID="):
                    cid = line.split("##contig=<ID=")[1].split(",")[0].split(">")[0]
                    self.contigs.append(cid)
            # Get full sample list without decoding rows
            vcf_all = cyvcf2.VCF(self.filepath)
            self.samples = list(vcf_all.samples)
            vcf_hdr.close()
            vcf_all.close()
            return

        with self._open_file() as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if line.startswith("##"):
                    self.header_lines.append(line)
                    if line.startswith("##contig=<ID="):
                        cid = line.split("##contig=<ID=")[1].split(",")[0].split(">")[0]
                        self.contigs.append(cid)
                    continue
                if line.startswith("#CHROM"):
                    self.header_lines.append(line)
                    parts = line.split("\t")
                    if len(parts) > 9:
                        self.samples = parts[9:]
                    break

    def _on_sparse_progress(self, count: int) -> None:
        if not HAS_CYVCF2:
            self._emit_progress(count)

    def _on_sparse_complete(self, total: int) -> None:
        if self._total_variants_count is None:
            self._total_variants_count = total
        if not HAS_CYVCF2:
            self._emit_progress(total)
            self._emit_count_complete(total)

    def _emit_progress(self, count: int) -> None:
        for pcb in list(self._progress_callbacks):
            try:
                pcb(count)
            except Exception:
                pass

    def _emit_count_complete(self, total: int) -> None:
        for cb in list(self._count_callbacks):
            try:
                cb(total)
            except Exception:
                pass

    def _emit_hydration(self, indices: List[int]) -> None:
        if not indices:
            return
        for hcb in list(self._hydration_callbacks):
            try:
                hcb(indices)
            except Exception:
                pass

    def _start_dual_pipelines(self, lazy: bool = True) -> None:
        """
        Launch Handle 1 (samples=[]) site streamer and Handle 2 (full samples) LRU hydrator.
        Reads first 150 site records synchronously so FixedVariantTable renders immediately.
        """
        initial_batch = 150

        if HAS_CYVCF2:
            try:
                site_vcf = cyvcf2.VCF(self.filepath, samples=[])
                for v in site_vcf:
                    self._site_records.append(_site_record_from_cyvcf2(v))
                    if len(self._site_records) >= initial_batch:
                        break

                if len(self._site_records) < initial_batch:
                    # Entire file fit in initial batch
                    site_vcf.close()
                    self._site_stream_done = True
                    self._total_variants_count = len(self._site_records)
                    self._emit_progress(self._total_variants_count)
                    self._emit_count_complete(self._total_variants_count)
                elif lazy:
                    self._start_cyvcf2_site_worker(site_vcf)
                else:
                    for v in site_vcf:
                        self._site_records.append(_site_record_from_cyvcf2(v))
                    site_vcf.close()
                    self._site_stream_done = True
                    self._total_variants_count = len(self._site_records)
            except Exception:
                # Fallback to text line streaming if cyvcf2 failed
                self._start_fallback_site_worker(initial_batch, lazy=lazy)
        else:
            self._start_fallback_site_worker(initial_batch, lazy=lazy)

        # Start Handle 2 (Sample Hydration Worker) in background when lazy & samples exist
        if lazy and self.samples:
            self._start_sample_hydration_worker()

    def _start_cyvcf2_site_worker(self, site_vcf: Any) -> None:
        """Background worker continuing Handle 1 (samples=[]) site stream."""
        def _worker():
            try:
                batch: List[VariantRecord] = []
                count = len(self._site_records)
                for v in site_vcf:
                    if self._stop_workers:
                        break
                    batch.append(_site_record_from_cyvcf2(v))
                    count += 1
                    if len(batch) >= 250:
                        with self._site_lock:
                            self._site_records.extend(batch)
                        batch.clear()
                        if count % 1000 == 0:
                            self._emit_progress(count)
                        time.sleep(0.0002)
                if batch:
                    with self._site_lock:
                        self._site_records.extend(batch)
                try:
                    site_vcf.close()
                except Exception:
                    pass
                with self._site_lock:
                    self._site_stream_done = True
                    self._total_variants_count = len(self._site_records)
                self._emit_progress(self._total_variants_count)
                self._emit_count_complete(self._total_variants_count)
            except Exception:
                with self._site_lock:
                    self._site_stream_done = True

        self._site_thread = threading.Thread(target=_worker, daemon=True)
        self._site_thread.start()

    def _start_fallback_site_worker(self, initial_batch: int, lazy: bool = True) -> None:
        """Pure-Python fallback site-only reader (splits only columns 0..8)."""
        with self._open_file() as f:
            for line in f:
                if not line or line.startswith("#"):
                    continue
                rec = parse_vcf_site_only(line)
                if rec:
                    self._site_records.append(rec)
                    if lazy and len(self._site_records) >= initial_batch:
                        break

        if len(self._site_records) < initial_batch or not lazy:
            self._site_stream_done = True
            self._total_variants_count = len(self._site_records)
            self._emit_progress(self._total_variants_count)
            self._emit_count_complete(self._total_variants_count)
            return

        start_idx = len(self._site_records)

        def _worker():
            try:
                idx = 0
                batch: List[VariantRecord] = []
                with self._open_file() as f:
                    for line in f:
                        if self._stop_workers:
                            break
                        if not line or line.startswith("#"):
                            continue
                        if idx < start_idx:
                            idx += 1
                            continue
                        rec = parse_vcf_site_only(line)
                        if rec:
                            batch.append(rec)
                            idx += 1
                            if len(batch) >= 250:
                                with self._site_lock:
                                    self._site_records.extend(batch)
                                batch.clear()
                                if idx % 1000 == 0:
                                    self._emit_progress(idx)
                                time.sleep(0.0005)
                if batch:
                    with self._site_lock:
                        self._site_records.extend(batch)
                with self._site_lock:
                    self._site_stream_done = True
                    self._total_variants_count = len(self._site_records)
                self._emit_progress(self._total_variants_count)
                self._emit_count_complete(self._total_variants_count)
            except Exception:
                with self._site_lock:
                    self._site_stream_done = True

        self._site_thread = threading.Thread(target=_worker, daemon=True)
        self._site_thread.start()

    def _hydrate_window_sync(self, start_idx: int, count: int) -> List[int]:
        """Hydrate sample payloads for [start_idx, start_idx + count) using Handle 2 / Tabix / SparseIndex."""
        if not self.samples or count <= 0:
            return []

        with self._site_lock:
            end_idx = min(len(self._site_records), start_idx + count)
            missing = [i for i in range(start_idx, end_idx) if not self._sample_cache.contains(i)]
            if not missing:
                return []
            target_sites = [(i, self._site_records[i]) for i in missing]

        hydrated: List[int] = []

        # Fast path 1: Tabix / CSI region query via cyvcf2 Handle 2
        if HAS_CYVCF2 and self.has_tabix and target_sites:
            try:
                tabix_vcf = cyvcf2.VCF(self.filepath)
                # Group contiguous missing indices by chromosome
                by_chrom: Dict[str, List[Tuple[int, VariantRecord]]] = {}
                for i, srec in target_sites:
                    by_chrom.setdefault(srec.chrom, []).append((i, srec))

                for chrom, items in by_chrom.items():
                    min_pos = min(s.pos for _, s in items)
                    max_pos = max(s.pos for _, s in items)
                    lookup: Dict[Tuple[int, str, str], List[int]] = {}
                    for i, s in items:
                        key = (s.pos, s.ref, s.alt_str)
                        lookup.setdefault(key, []).append(i)

                    for v in tabix_vcf(f"{chrom}:{min_pos}-{max_pos}"):
                        v_alts = ",".join(v.ALT) if v.ALT else ""
                        k = (int(v.POS), v.REF, v_alts)
                        if k in lookup:
                            payload = _sample_payload_from_cyvcf2(v, self.samples)
                            for row_i in lookup[k]:
                                self._sample_cache.put(row_i, payload)
                                hydrated.append(row_i)
                tabix_vcf.close()
                if len(hydrated) == len(missing):
                    return hydrated
            except Exception:
                pass

        # Fast path 2: Sparse byte-offset index for plain uncompressed .vcf
        if self._sparse_index and target_sites:
            remaining = [i for i in missing if not self._sample_cache.contains(i)]
            if remaining:
                first_i = remaining[0]
                last_i = remaining[-1]
                seek_offset, curr_idx = self._sparse_index.get_seek_offset_for_index(first_i)
                needed_set = set(remaining)
                with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(seek_offset)
                    while curr_idx <= last_i:
                        line = f.readline()
                        if not line:
                            break
                        if line.startswith("#"):
                            continue
                        if curr_idx in needed_set:
                            full_rec = parse_vcf_line(line, self.samples)
                            if full_rec:
                                payload = {
                                    "format_keys": full_rec.format_keys,
                                    "sample_data": full_rec.sample_data,
                                    "genotypes": full_rec.genotypes,
                                    "depths": full_rec.depths,
                                    "ad": full_rec.ad,
                                }
                                self._sample_cache.put(curr_idx, payload)
                                hydrated.append(curr_idx)
                        curr_idx += 1
                return hydrated

        # Fallback path 3: cyvcf2 sequential scan or text scan up to last needed index
        remaining = [i for i in missing if not self._sample_cache.contains(i)]
        if remaining:
            last_i = remaining[-1]
            needed_set = set(remaining)
            if HAS_CYVCF2:
                try:
                    vcf2 = cyvcf2.VCF(self.filepath)
                    for idx, v in enumerate(vcf2):
                        if idx > last_i:
                            break
                        if idx in needed_set or not self._sample_cache.contains(idx):
                            payload = _sample_payload_from_cyvcf2(v, self.samples)
                            self._sample_cache.put(idx, payload)
                            if idx in needed_set:
                                hydrated.append(idx)
                    vcf2.close()
                    return hydrated
                except Exception:
                    pass

            curr_idx = 0
            with self._open_file() as f:
                for line in f:
                    if not line or line.startswith("#"):
                        continue
                    if curr_idx > last_i:
                        break
                    if curr_idx in needed_set:
                        full_rec = parse_vcf_line(line, self.samples)
                        if full_rec:
                            payload = {
                                "format_keys": full_rec.format_keys,
                                "sample_data": full_rec.sample_data,
                                "genotypes": full_rec.genotypes,
                                "depths": full_rec.depths,
                                "ad": full_rec.ad,
                            }
                            self._sample_cache.put(curr_idx, payload)
                            hydrated.append(curr_idx)
                    curr_idx += 1

        return hydrated

    def _start_sample_hydration_worker(self) -> None:
        """
        Handle 2 background worker:
        - Prioritizes visible/requested windows immediately.
        - Streams sample rows sequentially into LRU cache behind FixedVariantTable.
        """
        def _worker():
            seq_idx = 0
            seq_iter = None
            seq_vcf = None

            def _open_seq_stream():
                nonlocal seq_vcf, seq_iter
                if HAS_CYVCF2:
                    try:
                        seq_vcf = cyvcf2.VCF(self.filepath)
                        seq_iter = iter(seq_vcf)
                        return
                    except Exception:
                        seq_vcf = None
                        seq_iter = None

            _open_seq_stream()
            batch_hydrated: List[int] = []

            try:
                while not self._stop_workers:
                    # 1. Process any urgent priority window requests first
                    prio = None
                    with self._sample_cond:
                        if self._priority_windows:
                            prio = self._priority_windows.popleft()

                    if prio is not None:
                        p_start, p_count = prio
                        try:
                            hydrated = self._hydrate_window_sync(p_start, p_count)
                        except (FileNotFoundError, OSError):
                            break
                        if hydrated:
                            self._emit_hydration(hydrated)
                        continue

                    # 2. Sequential background streaming into LRU cache up to lookahead horizon
                    with self._site_lock:
                        total_sites = len(self._site_records)
                        done_sites = self._site_stream_done

                    horizon = min(total_sites, max(400, self._focus_row + 500))
                    if seq_idx >= horizon:
                        if done_sites and seq_idx >= total_sites:
                            # All rows streamed; sleep waiting for priority requests
                            with self._sample_cond:
                                if not self._priority_windows and not self._stop_workers:
                                    self._sample_cond.wait(timeout=0.1)
                            continue
                        time.sleep(0.01)
                        continue

                    if seq_iter is not None:
                        try:
                            v = next(seq_iter)
                            if not self._sample_cache.contains(seq_idx):
                                payload = _sample_payload_from_cyvcf2(v, self.samples)
                                self._sample_cache.put(seq_idx, payload)
                                batch_hydrated.append(seq_idx)
                            seq_idx += 1
                            if len(batch_hydrated) >= 25:
                                self._emit_hydration(list(batch_hydrated))
                                batch_hydrated.clear()
                                time.sleep(0.0005)
                        except StopIteration:
                            if batch_hydrated:
                                self._emit_hydration(list(batch_hydrated))
                                batch_hydrated.clear()
                            with self._sample_cond:
                                if not self._priority_windows and not self._stop_workers:
                                    self._sample_cond.wait(timeout=0.1)
                        except Exception:
                            seq_iter = None
                    else:
                        # Text fallback hydration chunk
                        chunk_end = min(horizon, seq_idx + 50)
                        try:
                            hydrated = self._hydrate_window_sync(seq_idx, chunk_end - seq_idx)
                        except (FileNotFoundError, OSError):
                            break
                        seq_idx = chunk_end
                        if hydrated:
                            self._emit_hydration(hydrated)
                        time.sleep(0.002)
            finally:
                if batch_hydrated:
                    self._emit_hydration(batch_hydrated)
                if seq_vcf is not None:
                    try:
                        seq_vcf.close()
                    except Exception:
                        pass

        self._sample_thread = threading.Thread(target=_worker, daemon=True)
        self._sample_thread.start()

    def request_sample_hydration(self, offset: int, limit: int = 100) -> None:
        """Enqueue a high-priority sample hydration window for SampleMatrixTable."""
        if not self.samples or limit <= 0:
            return
        with self._sample_cond:
            self._priority_windows.append((max(0, offset), limit))
            self._sample_cond.notify_all()

    def set_focus_row(self, row_idx: int) -> None:
        """Update active cursor focus so Handle 2 streams ahead of the user's viewport."""
        self._focus_row = max(0, row_idx)

    def add_hydration_callback(self, cb: Callable[[List[int]], None]) -> None:
        """Register callback invoked when Sample Hydration Worker populates row indices."""
        self._hydration_callbacks.append(cb)

    def add_progress_callback(self, cb: Callable[[int], None]):
        """Register a callback for periodic progress updates during Handle 1 site scan."""
        self._progress_callbacks.append(cb)
        if self._total_variants_count is not None:
            try:
                cb(self._total_variants_count)
            except Exception:
                pass

    def add_total_variants_callback(self, cb: Callable[[int], None]):
        """Register a callback for when Handle 1 variant counting completes asynchronously."""
        if self._total_variants_count is not None:
            try:
                cb(self._total_variants_count)
            except Exception:
                pass
        else:
            self._count_callbacks.append(cb)

    @property
    def total_variants_ready(self) -> bool:
        """Returns True if Handle 1 has completed counting all variant sites."""
        return self._total_variants_count is not None

    def get_total_variants_async(self) -> Optional[int]:
        """Returns total variant count if already known, or None if Handle 1 is still streaming."""
        return self._total_variants_count

    def _wait_for_site_index(self, target_count: int) -> None:
        """Wait briefly for Handle 1 site worker to reach target_count (or complete)."""
        while not self._site_stream_done:
            with self._site_lock:
                if len(self._site_records) >= target_count:
                    return
            time.sleep(0.002)

    def _preload_all_records(self):
        """Loads all records with full sample payloads for smaller files or eager callers."""
        if self._records:
            return
        self._records = self.get_records(0, None)

    @property
    def total_variants(self) -> int:
        if self._total_variants_count is not None:
            return self._total_variants_count
        if self._records:
            return len(self._records)
        if self._site_thread and self._site_thread.is_alive():
            self._site_thread.join()
        if self._total_variants_count is not None:
            return self._total_variants_count
        if self._sparse_index:
            if not self._sparse_index.is_ready:
                self._sparse_index.wait_until_ready()
            self._total_variants_count = self._sparse_index.total_records
            return self._total_variants_count
        with self._site_lock:
            return len(self._site_records)

    @property
    def total_samples(self) -> int:
        return len(self.samples)

    def get_hydrated_record(self, row_idx: int) -> Optional[VariantRecord]:
        """Return VariantRecord at row_idx with cached sample payload attached if hydrated."""
        with self._site_lock:
            if row_idx < 0 or row_idx >= len(self._site_records):
                return None
            site_rec = self._site_records[row_idx]
        if not self.samples:
            site_rec.samples_loaded = True
            return site_rec
        payload = self._sample_cache.get(row_idx)
        if payload is not None:
            return site_rec.with_samples(payload)
        return site_rec

    def get_slice(
        self,
        offset: int = 0,
        limit: int = 100,
        allow_placeholder: bool = False,
    ) -> List[VariantRecord]:
        """
        Windowed variant slice retrieval combining Handle 1 site store + Handle 2 LRU sample cache.
        - When allow_placeholder=True (TUI scrolling): returns site rows immediately (<1ms) and queues
          priority sample hydration for any uncached rows.
        - When allow_placeholder=False (default): ensures sample payloads are hydrated before returning.
        """
        if offset < 0:
            offset = 0

        if self._records and len(self._records) > offset:
            return self._records[offset: offset + limit]

        self._wait_for_site_index(offset + limit)

        with self._site_lock:
            site_slice = self._site_records[offset: offset + limit]

        if not site_slice:
            return []

        if not self.samples:
            for sr in site_slice:
                sr.samples_loaded = True
            return site_slice

        # Hydrate synchronously if caller does not want placeholder rows
        if not allow_placeholder:
            missing_any = any(
                not self._sample_cache.contains(offset + j) for j in range(len(site_slice))
            )
            if missing_any:
                self._hydrate_window_sync(offset, len(site_slice))

        result: List[VariantRecord] = []
        need_async_hydrate = False
        for j, site_rec in enumerate(site_slice):
            row_idx = offset + j
            payload = self._sample_cache.get(row_idx)
            if payload is not None:
                result.append(site_rec.with_samples(payload))
            else:
                result.append(site_rec)
                need_async_hydrate = True

        if allow_placeholder and need_async_hydrate:
            self.request_sample_hydration(offset, len(site_slice))

        return result

    def get_records(self, offset: int = 0, limit: Optional[int] = None) -> List[VariantRecord]:
        """Backward-compatible get_records method."""
        if limit is not None:
            return self.get_slice(offset, limit, allow_placeholder=False)

        if not self._records:
            all_records: List[VariantRecord] = []
            if HAS_CYVCF2:
                try:
                    vcf = cyvcf2.VCF(self.filepath)
                    for idx, v in enumerate(vcf):
                        rec = _full_record_from_cyvcf2(v, self.samples)
                        all_records.append(rec)
                        if self.samples:
                            self._sample_cache.put(idx, {
                                "format_keys": rec.format_keys,
                                "sample_data": rec.sample_data,
                                "genotypes": rec.genotypes,
                                "depths": rec.depths,
                                "ad": rec.ad,
                            })
                    vcf.close()
                except Exception:
                    all_records = []

            if not all_records:
                curr_idx = 0
                with self._open_file() as f:
                    for line in f:
                        if not line or line.startswith("#"):
                            continue
                        rec = parse_vcf_line(line, self.samples)
                        if rec:
                            all_records.append(rec)
                            if self.samples:
                                self._sample_cache.put(curr_idx, {
                                    "format_keys": rec.format_keys,
                                    "sample_data": rec.sample_data,
                                    "genotypes": rec.genotypes,
                                    "depths": rec.depths,
                                    "ad": rec.ad,
                                })
                            curr_idx += 1

            self._records = all_records
            self._total_variants_count = len(self._records)

        return self._records[offset:]

    def query_region(self, chrom: str, start: int, end: int, limit: int = 500) -> List[VariantRecord]:
        """
        Query variants in a genomic interval chrom:start-end.
        Uses cyvcf2 Tabix Handle 2 if indexed, or SparseVcfIndex / site stream fallback.
        """
        if HAS_CYVCF2 and self.has_tabix:
            try:
                vcf = cyvcf2.VCF(self.filepath)
                region_str = f"{chrom}:{start}-{end}"
                records: List[VariantRecord] = []
                for v in vcf(region_str):
                    records.append(_full_record_from_cyvcf2(v, self.samples))
                    if len(records) >= limit:
                        break
                vcf.close()
                return records
            except Exception:
                pass

        # Seek using sparse index
        if self._sparse_index:
            seek_offset, _ = self._sparse_index.find_nearest_checkpoint_for_region(chrom, start)
            records = []
            with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                f.seek(seek_offset)
                while len(records) < limit:
                    line = f.readline()
                    if not line:
                        break
                    if line.startswith("#"):
                        continue
                    parts = line.split("\t", 3)
                    if len(parts) >= 2:
                        c = parts[0]
                        try:
                            p = int(parts[1])
                        except ValueError:
                            continue
                        if c == chrom:
                            if p > end:
                                break
                            if p >= start:
                                rec = parse_vcf_line(line, self.samples)
                                if rec:
                                    records.append(rec)
                        elif records:
                            break
            return records

        # Fallback linear scan
        records = []
        with self._open_file() as f:
            for line in f:
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t", 3)
                if len(parts) >= 2 and parts[0] == chrom:
                    try:
                        p = int(parts[1])
                    except ValueError:
                        continue
                    if start <= p <= end:
                        rec = parse_vcf_line(line, self.samples)
                        if rec:
                            records.append(rec)
                            if len(records) >= limit:
                                break
        return records

    def filter_records(
        self,
        min_qual: Optional[float] = None,
        min_depth: Optional[int] = None,
        variant_type: Optional[str] = None,
        filter_status: Optional[str] = None,
        search_query: Optional[str] = None,
        limit: int = 200,
    ) -> List[VariantRecord]:
        """
        Filter variants in real time.
        Site-only filters execute directly on Handle 1's fast samples=[] site stream,
        hydrating sample payloads only for the matched subset!
        """
        def _match_site(r: VariantRecord) -> bool:
            if min_qual is not None and r.qual is not None and r.qual < min_qual:
                return False
            if variant_type and variant_type != "ALL":
                if variant_type == "SNP" and r.is_indel:
                    return False
                if variant_type == "INDEL" and not r.is_indel:
                    return False
                if variant_type == "MULTI_ALLELIC" and not r.is_multiallelic:
                    return False
                if variant_type == "DRUG_RESISTANT" and not r.drug_annotation:
                    return False
            if filter_status and filter_status != "ALL":
                if r.filter != filter_status:
                    return False
            if search_query:
                q = search_query.lower()
                matches = (
                    q in r.chrom.lower()
                    or str(r.pos) in q
                    or q in r.gene.lower()
                    or q in r.drug.lower()
                    or q in r.mutation.lower()
                )
                if not matches:
                    return False
            return True

        def _match_depth(r: VariantRecord) -> bool:
            if min_depth is None:
                return True
            total_dp = sum(r.depths.values())
            mean_dp = total_dp / len(r.depths) if r.depths else 0
            return mean_dp >= min_depth

        if self._records:
            filtered: List[VariantRecord] = []
            for r in self._records:
                if _match_site(r) and _match_depth(r):
                    filtered.append(r)
                    if limit and len(filtered) >= limit:
                        break
            return filtered

        # Wait briefly if Handle 1 is still finishing small file or evaluate available + remaining sites
        matched_indices: List[int] = []
        idx = 0
        while True:
            with self._site_lock:
                avail = len(self._site_records)
                done = self._site_stream_done
                batch = self._site_records[idx:avail]
            for offset_j, site_rec in enumerate(batch):
                row_i = idx + offset_j
                if _match_site(site_rec):
                    if min_depth is not None:
                        if not self._sample_cache.contains(row_i):
                            self._hydrate_window_sync(row_i, 1)
                        hydrated_r = self.get_hydrated_record(row_i)
                        if hydrated_r and _match_depth(hydrated_r):
                            matched_indices.append(row_i)
                    else:
                        matched_indices.append(row_i)
                    if limit and len(matched_indices) >= limit:
                        break
            idx = avail
            if (limit and len(matched_indices) >= limit) or done:
                break
            time.sleep(0.002)

        # Hydrate only the matched subset for display in SampleMatrixTable
        results: List[VariantRecord] = []
        if matched_indices and self.samples:
            for row_i in matched_indices:
                if not self._sample_cache.contains(row_i):
                    self._hydrate_window_sync(row_i, 1)
                rec = self.get_hydrated_record(row_i)
                if rec:
                    results.append(rec)
        else:
            for row_i in matched_indices:
                rec = self.get_hydrated_record(row_i)
                if rec:
                    results.append(rec)
        return results

    def close(self) -> None:
        self._stop_workers = True
        self._progress_callbacks.clear()
        self._count_callbacks.clear()
        self._hydration_callbacks.clear()
        with self._sample_cond:
            self._sample_cond.notify_all()
