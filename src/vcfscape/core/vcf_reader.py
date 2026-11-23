"""
High-performance Mandatory cyvcf2 Dual-Handle VCF Reader with Pre-Open Index Guard:
1. Enforces a pre-open >100 MB unindexed file check (.tbi / .csi) before opening any handle.
2. Requires cyvcf2 for all VCF/VCF.GZ/BCF parsing (no pure-Python fallback parsers).
3. Handle 1 (Site Reader): Opens cyvcf2.VCF(path, samples=[]) to stream minimal core
   variant fields (CHROM, POS, ID, REF, ALT, QUAL, FILTER) without allocating per-row
   INFO dicts, FORMAT lists, or sample genotypes across background rows.
4. Handle 2 (Viewport Sample Reader): Hydrates requested viewport windows on demand into a
   thread-safe RecordLruCache using Tabix/CSI region queries or bounded cyvcf2 scan.
"""

from __future__ import annotations

import os
import time
import threading
from typing import List, Dict, Any, Optional, Tuple, Callable, Sequence, Set

from vcfscape.core.malaria_db import MalariaAnnotationDB, MarkerAnnotation
from vcfscape.core.indexer import RecordLruCache

try:
    import cyvcf2
    _CYVCF2_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as exc:
    cyvcf2 = None  # type: ignore
    _CYVCF2_IMPORT_ERROR = exc

LARGE_UNINDEXED_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB


class UnindexedLargeVcfError(Exception):
    """Raised before opening a VCF file when size > 100 MB and no .tbi/.csi index is available."""

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
    """Check if a Tabix (.tbi) or CSI (.csi) index exists via filesystem checks only."""
    abs_path = os.path.abspath(filepath)
    return os.path.exists(f"{abs_path}.tbi") or os.path.exists(f"{abs_path}.csi")


def check_vcf_index_requirement(
    filepath: str,
    max_unindexed_bytes: int = LARGE_UNINDEXED_THRESHOLD_BYTES,
) -> None:
    """Enforce index requirement for VCF/BCF files larger than 100 MB before opening the file."""
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


class _MinimalSite:
    """Ultra-lightweight core site tuple stored by Handle 1 without INFO/FORMAT/annotation dicts."""
    __slots__ = (
        "chrom", "pos", "var_id", "ref", "alt", "qual", "filter",
        "is_multiallelic", "is_indel",
    )

    def __init__(
        self,
        chrom: str,
        pos: int,
        var_id: str,
        ref: str,
        alt: Tuple[str, ...],
        qual: Optional[float],
        filter_str: str,
    ):
        self.chrom = chrom
        self.pos = pos
        self.var_id = var_id or "."
        self.ref = ref
        self.alt = alt
        self.qual = qual
        self.filter = filter_str or "PASS"
        self.is_multiallelic = len(alt) > 1
        self.is_indel = len(ref) != 1 or any(len(a) != 1 for a in alt)

    @property
    def alt_str(self) -> str:
        return ",".join(self.alt)

    def to_variant_record(
        self,
        info: Optional[Dict[str, Any]] = None,
        format_keys: Optional[List[str]] = None,
    ) -> "VariantRecord":
        return VariantRecord(
            chrom=self.chrom,
            pos=self.pos,
            var_id=self.var_id,
            ref=self.ref,
            alt=list(self.alt),
            qual=self.qual,
            filter_str=self.filter,
            info=info if info is not None else {},
            format_keys=format_keys if format_keys is not None else ["GT"],
            sample_data={},
            genotypes={},
            depths={},
            ad={},
            samples_loaded=False,
        )


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

        self.is_multiallelic = len(self.alt) > 1
        self.is_indel = len(self.ref) != 1 or any(len(a) != 1 for a in self.alt)

        if self.is_multiallelic and self.is_indel:
            self.var_type = "Multi-Allelic INDEL"
        elif self.is_multiallelic:
            self.var_type = "Multi-Allelic SNP"
        elif self.is_indel:
            self.var_type = "INDEL"
        else:
            self.var_type = "SNP"

        self.drug_annotation: Optional[MarkerAnnotation] = MalariaAnnotationDB.lookup(
            self.chrom, self.pos, self.ref, ",".join(self.alt)
        )

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
        info = payload.get("info")
        rec.info = info if info is not None else self.info
        rec.is_multiallelic = self.is_multiallelic
        rec.is_indel = self.is_indel
        rec.var_type = self.var_type
        rec.drug_annotation = self.drug_annotation
        rec.gene = str(rec.info.get("GENE", (rec.drug_annotation.gene if rec.drug_annotation else ".")))
        rec.impact = str(rec.info.get("IMPACT", (rec.drug_annotation.impact if rec.drug_annotation else ".")))
        rec.mutation = str(rec.info.get("MUT", (rec.drug_annotation.mutation if rec.drug_annotation else ".")))
        rec.drug = str(rec.info.get("DRUG", (rec.drug_annotation.drug if rec.drug_annotation else ".")))

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


def _minimal_site_from_cyvcf2(v: Any) -> _MinimalSite:
    """Minimal cyvcf2 extractor reading ONLY core fixed fields (skips INFO, FORMAT, genotypes)."""
    alts = tuple(v.ALT) if v.ALT else ()
    return _MinimalSite(
        chrom=v.CHROM,
        pos=int(v.POS),
        var_id=v.ID or ".",
        ref=v.REF,
        alt=alts,
        qual=float(v.QUAL) if v.QUAL is not None else None,
        filter_str=v.FILTER or "PASS",
    )


def _site_record_from_cyvcf2(v: Any) -> VariantRecord:
    """Create full site VariantRecord (with INFO/FORMAT) for initial visible slice or eager queries."""
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
    """Extract sample payload (GT, DP, AD, GQ) + INFO/FORMAT from a full-sample cyvcf2 variant."""
    v_format_keys = list(v.FORMAT) if v.FORMAT else ["GT"]
    try:
        info_dict = dict(v.INFO) if v.INFO else {}
    except Exception:
        info_dict = {}

    sample_data: Dict[str, Dict[str, Any]] = {}
    genotypes: Dict[str, Tuple[int, ...]] = {}
    depths: Dict[str, int] = {}
    ad_dict: Dict[str, List[int]] = {}

    if not samples:
        return {
            "info": info_dict,
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
        "info": info_dict,
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
    Mandatory Dual-Handle cyvcf2 VCF Reader:
    - Enforces >100 MB unindexed file check before opening any handle.
    - Handle 1 (`samples=[]`): Minimal core site stream (CHROM, POS, ID, REF, ALT, QUAL, FILTER).
    - Handle 2 (full samples): Viewport-only on-demand LRU sample hydration via Tabix/CSI or cyvcf2 scan.
    """

    def __init__(self, filepath: str, lazy: bool = True, allow_unindexed_large: bool = False):
        if cyvcf2 is None:
            raise RuntimeError(
                "cyvcf2 is mandatory for VCFscape. Install cyvcf2 and retry."
            ) from _CYVCF2_IMPORT_ERROR

        self.filepath = os.path.abspath(filepath)
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"VCF file not found: {self.filepath}")

        if not allow_unindexed_large:
            check_vcf_index_requirement(self.filepath)

        lower = self.filepath.lower()
        self.is_gzipped = lower.endswith(".gz") or lower.endswith(".bgz")
        self.is_bcf = lower.endswith(".bcf")
        self.has_tabix = has_vcf_index(self.filepath)
        self.samples: List[str] = []
        self.contigs: List[str] = []
        self.header_lines: List[str] = []
        self.backend = "cyvcf2_dual_tabix" if self.has_tabix else "cyvcf2_dual"

        self._sample_cache = RecordLruCache(maxsize=2500 if self.has_tabix else None)
        self._site_records: List[Any] = []  # VariantRecord for initial slice, _MinimalSite for rest
        self._materialized_sites: Dict[int, VariantRecord] = {}
        self._site_lock = threading.RLock()
        self._records: List[VariantRecord] = []

        self._total_variants_count: Optional[int] = None
        self._site_stream_done = False
        self._site_thread: Optional[threading.Thread] = None
        self._sample_thread: Optional[threading.Thread] = None
        self._sample_cond = threading.Condition()
        self._pending_indices: Optional[List[int]] = None
        self._priority_indices: Set[int] = set()
        self._priority_version: int = 0
        self._unindexed_pass_done = False
        self._focus_row: int = 0
        self._stop_event = threading.Event()
        self._stop_workers = False

        self._count_callbacks: List[Callable[[int], None]] = []
        self._progress_callbacks: List[Callable[[int], None]] = []
        self._hydration_callbacks: List[Callable[[List[int]], None]] = []

        # 1. Fast Header Extraction via cyvcf2
        self._load_header_only()

        # 2. Start Minimal Handle 1 + Viewport-Only Handle 2
        self._start_dual_pipelines(lazy=lazy)

        # 3. Eagerly hydrate small datasets or when lazy=False
        if not lazy or (self._total_variants_count is not None and self._total_variants_count <= 500):
            self._preload_all_records()

    def _load_header_only(self) -> None:
        """Extract samples, contigs, and header metadata lines directly via cyvcf2."""
        self.samples.clear()
        self.contigs.clear()
        self.header_lines.clear()

        vcf_hdr = cyvcf2.VCF(self.filepath)
        try:
            raw_hdr = str(vcf_hdr.raw_header or "")
            for line in raw_hdr.splitlines():
                line = line.rstrip("\r\n")
                if not line:
                    continue
                self.header_lines.append(line)
                if line.startswith("##contig=<ID="):
                    cid = line.split("##contig=<ID=")[1].split(",")[0].split(">")[0]
                    self.contigs.append(cid)
            self.samples = list(vcf_hdr.samples)
        finally:
            try:
                vcf_hdr.close()
            except Exception:
                pass

    def _emit_progress(self, count: int) -> None:
        if self._stop_workers or self._stop_event.is_set():
            return
        for pcb in list(self._progress_callbacks):
            if self._stop_workers or self._stop_event.is_set():
                return
            try:
                pcb(count)
            except Exception:
                pass

    def _emit_count_complete(self, total: int) -> None:
        if self._stop_workers or self._stop_event.is_set():
            return
        for cb in list(self._count_callbacks):
            if self._stop_workers or self._stop_event.is_set():
                return
            try:
                cb(total)
            except Exception:
                pass

    def _emit_hydration(self, indices: List[int]) -> None:
        if not indices or self._stop_workers or self._stop_event.is_set():
            return
        for hcb in list(self._hydration_callbacks):
            if self._stop_workers or self._stop_event.is_set():
                return
            try:
                hcb(indices)
            except Exception:
                pass

    def _materialize_site(self, row_idx: int, raw_site: Any) -> VariantRecord:
        """Convert _MinimalSite to VariantRecord on demand with bounded cache."""
        if isinstance(raw_site, VariantRecord):
            return raw_site
        cached = self._materialized_sites.get(row_idx)
        if cached is not None:
            return cached
        rec = raw_site.to_variant_record()
        if len(self._materialized_sites) > 2500:
            self._materialized_sites.clear()
        self._materialized_sites[row_idx] = rec
        return rec

    def _start_dual_pipelines(self, lazy: bool = True) -> None:
        """
        Launch Handle 1 (samples=[]) minimal site stream and Handle 2 viewport-only hydrator.
        Reads first 150 rows synchronously so FixedVariantTable renders immediately.
        """
        initial_batch = 150
        site_vcf = cyvcf2.VCF(self.filepath, samples=[])
        keep_open_for_worker = False
        try:
            for v in site_vcf:
                self._site_records.append(_site_record_from_cyvcf2(v))
                if len(self._site_records) >= initial_batch:
                    break

            if len(self._site_records) < initial_batch:
                self._site_stream_done = True
                self._total_variants_count = len(self._site_records)
                self._emit_progress(self._total_variants_count)
                self._emit_count_complete(self._total_variants_count)
            elif lazy:
                keep_open_for_worker = True
                self._start_cyvcf2_site_worker(site_vcf)
            else:
                for v in site_vcf:
                    self._site_records.append(_minimal_site_from_cyvcf2(v))
                self._site_stream_done = True
                self._total_variants_count = len(self._site_records)
                self._emit_progress(self._total_variants_count)
                self._emit_count_complete(self._total_variants_count)
        finally:
            if not keep_open_for_worker:
                try:
                    site_vcf.close()
                except Exception:
                    pass

        small_preloaded = (
            self._total_variants_count is not None and self._total_variants_count <= 500
        )
        if lazy and self.samples and not small_preloaded:
            self._start_sample_hydration_worker()

    def _start_cyvcf2_site_worker(self, site_vcf: Any) -> None:
        """Background Handle 1 worker extracting ONLY minimal core fields across remaining rows."""
        def _worker():
            try:
                batch: List[_MinimalSite] = []
                count = len(self._site_records)
                last_emit_t = time.monotonic()
                for v in site_vcf:
                    if self._stop_event.is_set() or self._stop_workers:
                        break
                    batch.append(_minimal_site_from_cyvcf2(v))
                    count += 1
                    if len(batch) >= 500:
                        with self._site_lock:
                            self._site_records.extend(batch)
                        batch.clear()
                        now = time.monotonic()
                        if count % 2000 == 0 and (now - last_emit_t) >= 0.08:
                            last_emit_t = now
                            self._emit_progress(count)
                        time.sleep(0.0001)
                if batch and not self._stop_event.is_set() and not self._stop_workers:
                    with self._site_lock:
                        self._site_records.extend(batch)
                with self._site_lock:
                    self._site_stream_done = True
                    if not self._stop_event.is_set() and not self._stop_workers:
                        self._total_variants_count = len(self._site_records)
                if not self._stop_event.is_set() and not self._stop_workers and self._total_variants_count is not None:
                    self._emit_progress(self._total_variants_count)
                    self._emit_count_complete(self._total_variants_count)
            except Exception:
                with self._site_lock:
                    self._site_stream_done = True
            finally:
                try:
                    site_vcf.close()
                except Exception:
                    pass

        self._site_thread = threading.Thread(target=_worker, daemon=True)
        self._site_thread.start()

    def _hydrate_indices_tabix(self, indices: Sequence[int]) -> List[int]:
        """Hydrate exact global row indices via compact Tabix/CSI region clusters."""
        if not self.samples or not indices or self._stop_event.is_set() or self._stop_workers:
            return []

        with self._site_lock:
            n_sites = len(self._site_records)
            missing = sorted({
                int(i) for i in indices
                if 0 <= int(i) < n_sites and not self._sample_cache.contains(int(i))
            })
            if not missing:
                return []
            target_sites = [(i, self._site_records[i]) for i in missing]

        hydrated: List[int] = []
        if not self.has_tabix:
            return hydrated

        tabix_vcf = None
        try:
            tabix_vcf = cyvcf2.VCF(self.filepath)
            by_chrom: Dict[str, List[Tuple[int, Any]]] = {}
            for i, srec in target_sites:
                by_chrom.setdefault(srec.chrom, []).append((i, srec))

            for chrom, items in by_chrom.items():
                if self._stop_event.is_set() or self._stop_workers:
                    break
                items.sort(key=lambda pair: (pair[1].pos, pair[0]))

                # Split sparse filtered hits into tight Tabix windows (<= 10kb gap, <= 50kb span)
                clusters: List[List[Tuple[int, Any]]] = []
                cur_cluster: List[Tuple[int, Any]] = []
                for pair in items:
                    if not cur_cluster:
                        cur_cluster.append(pair)
                    else:
                        gap = pair[1].pos - cur_cluster[-1][1].pos
                        span = pair[1].pos - cur_cluster[0][1].pos
                        if gap <= 10000 and span <= 50000:
                            cur_cluster.append(pair)
                        else:
                            clusters.append(cur_cluster)
                            cur_cluster = [pair]
                if cur_cluster:
                    clusters.append(cur_cluster)

                for cluster in clusters:
                    if self._stop_event.is_set() or self._stop_workers:
                        break
                    min_pos = cluster[0][1].pos
                    max_pos = cluster[-1][1].pos
                    lookup: Dict[Tuple[int, str, str], List[int]] = {}
                    for i, s in cluster:
                        lookup.setdefault((s.pos, s.ref, s.alt_str), []).append(i)

                    for v in tabix_vcf(f"{chrom}:{min_pos}-{max_pos}"):
                        if self._stop_event.is_set() or self._stop_workers:
                            break
                        v_alts = ",".join(v.ALT) if v.ALT else ""
                        k = (int(v.POS), v.REF, v_alts)
                        if k in lookup:
                            payload = _sample_payload_from_cyvcf2(v, self.samples)
                            for row_i in lookup[k]:
                                self._sample_cache.put(row_i, payload)
                                hydrated.append(row_i)
        except Exception:
            pass
        finally:
            if tabix_vcf is not None:
                try:
                    tabix_vcf.close()
                except Exception:
                    pass
        return hydrated

    def _hydrate_window_sync(self, start_idx: int, count: int) -> List[int]:
        """Hydrate sample payloads for [start_idx, start_idx + count) via cyvcf2 Handle 2."""
        if not self.samples or count <= 0 or self._stop_event.is_set() or self._stop_workers:
            return []

        with self._site_lock:
            end_idx = min(len(self._site_records), start_idx + count)
            missing = [i for i in range(start_idx, end_idx) if not self._sample_cache.contains(i)]
            if not missing:
                return []

        if self.has_tabix:
            return self._hydrate_indices_tabix(missing)

        # Unindexed (<= 100 MB): bounded scan up to last missing index when called synchronously
        hydrated: List[int] = []
        last_i = missing[-1]
        needed_set = set(missing)
        vcf2 = None
        try:
            vcf2 = cyvcf2.VCF(self.filepath)
            for idx, v in enumerate(vcf2):
                if idx > last_i or self._stop_event.is_set() or self._stop_workers:
                    break
                if idx in needed_set and not self._sample_cache.contains(idx):
                    payload = _sample_payload_from_cyvcf2(v, self.samples)
                    self._sample_cache.put(idx, payload)
                    hydrated.append(idx)
        except Exception:
            pass
        finally:
            if vcf2 is not None:
                try:
                    vcf2.close()
                except Exception:
                    pass
        return hydrated

    def _run_unindexed_single_pass(self) -> None:
        """
        Single-pass Handle 2 worker for allowed unindexed VCFs (<= 100 MB):
        Streams all variant rows once sequentially into an eviction-free cache,
        emitting incremental hydration batches so visible rows auto-repaint quickly.
        """
        vcf2 = None
        batch: List[int] = []
        last_emit_t = time.monotonic()
        seen_version = -1
        prio_snapshot: Set[int] = set()
        try:
            vcf2 = cyvcf2.VCF(self.filepath)
            for idx, v in enumerate(vcf2):
                if self._stop_event.is_set() or self._stop_workers:
                    break
                if not self._sample_cache.contains(idx):
                    payload = _sample_payload_from_cyvcf2(v, self.samples)
                    self._sample_cache.put(idx, payload)
                batch.append(idx)

                if seen_version != self._priority_version:
                    with self._sample_cond:
                        seen_version = self._priority_version
                        prio_snapshot = set(self._priority_indices)

                is_prio = idx in prio_snapshot
                now = time.monotonic()
                should_flush = (
                    len(batch) >= 150
                    or (is_prio and (len(batch) >= 25 or (now - last_emit_t) >= 0.02))
                    or (batch and (now - last_emit_t) >= 0.06)
                )
                if should_flush:
                    emit_list = list(batch)
                    batch.clear()
                    last_emit_t = now
                    self._emit_hydration(emit_list)
            if batch and not self._stop_event.is_set() and not self._stop_workers:
                self._emit_hydration(list(batch))
        except (FileNotFoundError, OSError):
            pass
        except Exception:
            pass
        finally:
            self._unindexed_pass_done = True
            if vcf2 is not None:
                try:
                    vcf2.close()
                except Exception:
                    pass

    def _start_sample_hydration_worker(self) -> None:
        """Start Handle 2 worker: Tabix exact-index lookup if indexed, else single-pass full cache."""
        if not self.has_tabix:
            self._sample_thread = threading.Thread(
                target=self._run_unindexed_single_pass, daemon=True
            )
            self._sample_thread.start()
            return

        def _indexed_worker():
            while not self._stop_event.is_set() and not self._stop_workers:
                req_indices: Optional[List[int]] = None
                with self._sample_cond:
                    while (
                        self._pending_indices is None
                        and not self._stop_event.is_set()
                        and not self._stop_workers
                    ):
                        self._sample_cond.wait(timeout=0.25)
                    if self._stop_event.is_set() or self._stop_workers:
                        break
                    req_indices = self._pending_indices
                    self._pending_indices = None

                if req_indices:
                    try:
                        hydrated = self._hydrate_indices_tabix(req_indices)
                    except (FileNotFoundError, OSError):
                        break
                    if hydrated and not self._stop_event.is_set() and not self._stop_workers:
                        self._emit_hydration(hydrated)

        self._sample_thread = threading.Thread(target=_indexed_worker, daemon=True)
        self._sample_thread.start()

    def request_sample_indices(self, indices: Sequence[int]) -> None:
        """Schedule viewport hydration for exact global row indices, coalescing superseded scrolls."""
        if not self.samples or self._stop_event.is_set() or self._stop_workers:
            return
        missing = [int(i) for i in indices if int(i) >= 0 and not self._sample_cache.contains(int(i))]
        if not missing:
            return
        with self._sample_cond:
            self._priority_indices = set(missing)
            self._priority_version += 1
            self._pending_indices = missing
            self._sample_cond.notify_all()

    def request_sample_hydration(self, offset: int, limit: int = 100) -> None:
        """Schedule viewport-scoped sample hydration for [offset, offset + limit)."""
        if not self.samples or limit <= 0 or self._stop_event.is_set() or self._stop_workers:
            return
        start = max(0, int(offset))
        self.request_sample_indices(range(start, start + int(limit)))

    def set_focus_row(self, row_idx: int) -> None:
        """Track active cursor row."""
        self._focus_row = max(0, row_idx)

    def add_hydration_callback(self, cb: Callable[[List[int]], None]) -> None:
        self._hydration_callbacks.append(cb)

    def add_progress_callback(self, cb: Callable[[int], None]) -> None:
        self._progress_callbacks.append(cb)
        if self._total_variants_count is not None:
            try:
                cb(self._total_variants_count)
            except Exception:
                pass

    def add_total_variants_callback(self, cb: Callable[[int], None]) -> None:
        if self._total_variants_count is not None:
            try:
                cb(self._total_variants_count)
            except Exception:
                pass
        else:
            self._count_callbacks.append(cb)

    @property
    def total_variants_ready(self) -> bool:
        return self._total_variants_count is not None

    def get_total_variants_async(self) -> Optional[int]:
        return self._total_variants_count

    def get_site_count(self) -> int:
        """Return number of Handle 1 site rows currently available in memory."""
        if self._records:
            return len(self._records)
        with self._site_lock:
            return len(self._site_records)

    def get_site_slice(self, offset: int = 0, limit: Optional[int] = None) -> List[Any]:
        """Return raw Handle 1 site objects (_MinimalSite or VariantRecord) without extra allocation."""
        if offset < 0:
            offset = 0
        if self._records:
            return self._records[offset:] if limit is None else self._records[offset: offset + limit]
        with self._site_lock:
            if limit is None:
                return list(self._site_records[offset:])
            return list(self._site_records[offset: offset + limit])

    def _wait_for_site_index(self, target_count: int) -> None:
        while not self._site_stream_done and not self._stop_event.is_set() and not self._stop_workers:
            with self._site_lock:
                if len(self._site_records) >= target_count:
                    return
            time.sleep(0.002)

    def _preload_all_records(self) -> None:
        if self._records:
            return
        self._records = self.get_records(0, None)

    @property
    def total_variants(self) -> int:
        if self._total_variants_count is not None:
            return self._total_variants_count
        if self._records:
            return len(self._records)
        if self._stop_event.is_set() or self._stop_workers:
            with self._site_lock:
                return len(self._site_records)
        if self._site_thread and self._site_thread.is_alive():
            self._site_thread.join()
        if self._total_variants_count is not None:
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
            raw_site = self._site_records[row_idx]
        site_rec = self._materialize_site(row_idx, raw_site)
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
        """Windowed variant slice retrieval combining Handle 1 site store + viewport LRU cache."""
        if offset < 0:
            offset = 0

        if self._records and len(self._records) > offset:
            return self._records[offset: offset + limit]

        self._wait_for_site_index(offset + limit)

        with self._site_lock:
            site_slice = self._site_records[offset: offset + limit]

        if not site_slice:
            return []

        materialized = [
            self._materialize_site(offset + j, raw_site)
            for j, raw_site in enumerate(site_slice)
        ]

        if not self.samples:
            for sr in materialized:
                sr.samples_loaded = True
            return materialized

        if not allow_placeholder:
            missing_any = any(
                not self._sample_cache.contains(offset + j) for j in range(len(materialized))
            )
            if missing_any:
                self._hydrate_window_sync(offset, len(materialized))

        result: List[VariantRecord] = []
        need_async_hydrate = False
        for j, site_rec in enumerate(materialized):
            row_idx = offset + j
            payload = self._sample_cache.get(row_idx)
            if payload is not None:
                result.append(site_rec.with_samples(payload))
            else:
                result.append(site_rec)
                need_async_hydrate = True

        if allow_placeholder and need_async_hydrate:
            self.request_sample_hydration(offset, len(materialized))

        return result

    def get_records(self, offset: int = 0, limit: Optional[int] = None) -> List[VariantRecord]:
        """Retrieve variant records (windowed if limit is given, else full file via cyvcf2)."""
        if limit is not None:
            return self.get_slice(offset, limit, allow_placeholder=False)

        if not self._records:
            all_records: List[VariantRecord] = []
            vcf = cyvcf2.VCF(self.filepath)
            try:
                for idx, v in enumerate(vcf):
                    rec = _full_record_from_cyvcf2(v, self.samples)
                    all_records.append(rec)
                    if self.samples:
                        self._sample_cache.put(idx, {
                            "info": rec.info,
                            "format_keys": rec.format_keys,
                            "sample_data": rec.sample_data,
                            "genotypes": rec.genotypes,
                            "depths": rec.depths,
                            "ad": rec.ad,
                        })
            finally:
                try:
                    vcf.close()
                except Exception:
                    pass

            self._records = all_records
            self._total_variants_count = len(self._records)

        return self._records[offset:]

    def query_region(self, chrom: str, start: int, end: int, limit: int = 500) -> List[VariantRecord]:
        """Query variants in a genomic interval chrom:start-end via cyvcf2."""
        if self.has_tabix:
            vcf = cyvcf2.VCF(self.filepath)
            records: List[VariantRecord] = []
            try:
                for v in vcf(f"{chrom}:{start}-{end}"):
                    records.append(_full_record_from_cyvcf2(v, self.samples))
                    if len(records) >= limit:
                        break
                return records
            except Exception:
                pass
            finally:
                try:
                    vcf.close()
                except Exception:
                    pass

        records = []
        vcf = cyvcf2.VCF(self.filepath)
        try:
            for v in vcf:
                if v.CHROM == chrom:
                    pos = int(v.POS)
                    if pos > end and records:
                        break
                    if start <= pos <= end:
                        records.append(_full_record_from_cyvcf2(v, self.samples))
                        if len(records) >= limit:
                            break
                elif records:
                    break
        finally:
            try:
                vcf.close()
            except Exception:
                pass
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
        """Filter variants directly on minimal site records, hydrating only matched rows."""
        def _match_site(r: Any) -> bool:
            if min_qual is not None and r.qual is not None and r.qual < min_qual:
                return False
            if variant_type and variant_type != "ALL":
                if variant_type == "SNP" and r.is_indel:
                    return False
                if variant_type == "INDEL" and not r.is_indel:
                    return False
                if variant_type == "MULTI_ALLELIC" and not r.is_multiallelic:
                    return False
                if variant_type == "DRUG_RESISTANT":
                    if hasattr(r, "drug_annotation"):
                        if not r.drug_annotation:
                            return False
                    else:
                        if not MalariaAnnotationDB.lookup(r.chrom, r.pos, r.ref, r.alt_str):
                            return False
            if filter_status and filter_status != "ALL":
                if r.filter != filter_status:
                    return False
            if search_query:
                q = search_query.lower()
                if q in r.chrom.lower() or str(r.pos) in q:
                    return True
                rec_full = r if isinstance(r, VariantRecord) else r.to_variant_record()
                matches = (
                    q in rec_full.gene.lower()
                    or q in rec_full.drug.lower()
                    or q in rec_full.mutation.lower()
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

        matched_indices: List[int] = []
        idx = 0
        while not self._stop_event.is_set() and not self._stop_workers:
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

    def close(self, wait: bool = True, timeout: float = 0.2) -> None:
        self._stop_workers = True
        self._stop_event.set()
        self._progress_callbacks.clear()
        self._count_callbacks.clear()
        self._hydration_callbacks.clear()
        with self._sample_cond:
            self._pending_indices = None
            self._priority_indices.clear()
            self._sample_cond.notify_all()
        if not wait:
            return
        cur = threading.current_thread()
        for t in (self._sample_thread, self._site_thread):
            if t is not None and t is not cur and t.is_alive():
                try:
                    t.join(timeout=timeout)
                except Exception:
                    pass
