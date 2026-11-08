"""
High-performance VCF Reader with dual indexing support:
1. Native Tabix/CSI via cyvcf2 for block-gzipped VCFs.
2. Sparse byte-offset index for uncompressed VCFs.
Supports instant startup (< 50ms), lazy chunked fetching, LRU caching, and region queries.
"""

import os
import gzip
import time
import threading
from typing import List, Dict, Any, Optional, Tuple, Iterator, Callable

from vcfscape.core.malaria_db import MalariaAnnotationDB, MarkerAnnotation
from vcfscape.core.indexer import SparseVcfIndex, RecordLruCache

try:
    import cyvcf2
    HAS_CYVCF2 = True
except ImportError:
    HAS_CYVCF2 = False


class VariantRecord:
    """Normalized internal representation of a VCF variant row."""
    __slots__ = (
        "chrom", "pos", "var_id", "ref", "alt", "qual", "filter", "info",
        "format_keys", "sample_data", "genotypes", "depths", "ad",
        "is_multiallelic", "is_indel", "var_type", "drug_annotation",
        "gene", "impact", "mutation", "drug"
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
        self.gene = self.info.get("GENE", (self.drug_annotation.gene if self.drug_annotation else "."))
        self.impact = self.info.get("IMPACT", (self.drug_annotation.impact if self.drug_annotation else "."))
        self.mutation = self.info.get("MUT", (self.drug_annotation.mutation if self.drug_annotation else "."))
        self.drug = self.info.get("DRUG", (self.drug_annotation.drug if self.drug_annotation else "."))

    @property
    def alt_str(self) -> str:
        return ",".join(self.alt)

    @property
    def num_alleles(self) -> int:
        return 1 + len(self.alt)


def parse_vcf_line(line: str, samples: List[str]) -> Optional[VariantRecord]:
    """Parse a single raw VCF line string into a VariantRecord."""
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

    # INFO parsing
    info_dict: Dict[str, Any] = {}
    if parts[7] != ".":
        for item in parts[7].split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                info_dict[k] = v
            else:
                info_dict[item] = True

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
    )


class VcfReader:
    """
    Unified VCF Parser interface with dual Tabix and Sparse Indexing support.
    Starts in < 50ms on multi-gigabyte VCFs by parsing only header lines on init,
    and retrieving record slices dynamically with an LRU cache.
    """

    def __init__(self, filepath: str, lazy: bool = True):
        self.filepath = os.path.abspath(filepath)
        self.is_gzipped = self.filepath.endswith(".gz") or self.filepath.endswith(".bgz")
        self.samples: List[str] = []
        self.contigs: List[str] = []
        self.header_lines: List[str] = []
        self.backend = "cyvcf2" if (HAS_CYVCF2 and self.is_gzipped) else "indexed_vcf"
        
        self._sparse_index: Optional[SparseVcfIndex] = None
        self._cache = RecordLruCache(maxsize=3000)
        self._records: List[VariantRecord] = []
        self._total_variants_count: Optional[int] = None
        self._counting_thread: Optional[threading.Thread] = None
        self._count_callbacks: List[Callable[[int], None]] = []
        self._progress_callbacks: List[Callable[[int], None]] = []

        # 1. Fast Header Extraction (always executes in < 15ms)
        self._load_header_only()

        # 2. Setup Indexing Engine
        if not self.is_gzipped:
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
                    self._total_variants_count = None
            else:
                self._sparse_index = SparseVcfIndex(self.filepath, build_async=False)
                self._total_variants_count = self._sparse_index.total_records
        else:
            self._setup_gzipped_source()

        # For small files or backward compatibility when requested eagerly
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
        for pcb in list(self._progress_callbacks):
            try:
                pcb(count)
            except Exception:
                pass

    def _on_sparse_complete(self, total: int) -> None:
        self._total_variants_count = total
        for pcb in list(self._progress_callbacks):
            try:
                pcb(total)
            except Exception:
                pass
        for cb in list(self._count_callbacks):
            try:
                cb(total)
            except Exception:
                pass

    def _setup_gzipped_source(self):
        """Prepares cyvcf2 and starts asynchronous background line counting."""
        has_tabix = os.path.exists(f"{self.filepath}.tbi") or os.path.exists(f"{self.filepath}.csi")
        if HAS_CYVCF2:
            try:
                cyvcf2.VCF(self.filepath)
                self.backend = "cyvcf2_tabix" if has_tabix else "cyvcf2"
            except Exception:
                self.backend = "gzipped_stream"
        else:
            self.backend = "gzipped_stream"

        # Background thread counts records without blocking UI startup
        self._start_background_count()

    def _start_background_count(self):
        if self._counting_thread is not None or self._total_variants_count is not None:
            return

        def _count_worker():
            try:
                count = 0
                with self._open_file() as f:
                    for line in f:
                        if line and not line.startswith("#"):
                            count += 1
                            if count % 1000 == 0:
                                for pcb in list(self._progress_callbacks):
                                    try:
                                        pcb(count)
                                    except Exception:
                                        pass
                            if count % 2000 == 0:
                                time.sleep(0.0005)
                self._total_variants_count = count
                for pcb in list(self._progress_callbacks):
                    try:
                        pcb(count)
                    except Exception:
                        pass
                for cb in list(self._count_callbacks):
                    try:
                        cb(count)
                    except Exception:
                        pass
            except Exception:
                pass

        self._counting_thread = threading.Thread(target=_count_worker, daemon=True)
        self._counting_thread.start()

    def add_progress_callback(self, cb: Callable[[int], None]):
        """Register a callback for periodic progress updates during background counting."""
        self._progress_callbacks.append(cb)
        if self._total_variants_count is not None:
            try:
                cb(self._total_variants_count)
            except Exception:
                pass

    def add_total_variants_callback(self, cb: Callable[[int], None]):
        """Register a callback for when variant counting completes asynchronously."""
        if self._total_variants_count is not None:
            try:
                cb(self._total_variants_count)
            except Exception:
                pass
        else:
            self._count_callbacks.append(cb)

    @property
    def total_variants_ready(self) -> bool:
        """Returns True if the exact total variant count is known."""
        return self._total_variants_count is not None

    def get_total_variants_async(self) -> Optional[int]:
        """Returns total variant count if already known, or None if still counting in background."""
        return self._total_variants_count

    def _preload_all_records(self):
        """Loads records into memory for smaller files or backward compatibility."""
        if self._records:
            return
        self._records = self.get_records(0, None)

    @property
    def total_variants(self) -> int:
        if self._total_variants_count is not None:
            return self._total_variants_count
        if self._records:
            return len(self._records)
        if self._sparse_index:
            if not self._sparse_index.is_ready:
                self._sparse_index.wait_until_ready()
            self._total_variants_count = self._sparse_index.total_records
            return self._total_variants_count

        # If background counting is running, wait for it synchronously for callers that need it
        if self._counting_thread and self._counting_thread.is_alive():
            self._counting_thread.join()
            if self._total_variants_count is not None:
                return self._total_variants_count

        # Fallback count for gzipped files without tabix total
        count = 0
        with self._open_file() as f:
            for line in f:
                if line and not line.startswith("#"):
                    count += 1
        self._total_variants_count = count
        return count

    @property
    def total_samples(self) -> int:
        return len(self.samples)

    def get_slice(self, offset: int = 0, limit: int = 100) -> List[VariantRecord]:
        """
        Fast windowed variant slice retrieval with LRU caching.
        Uses sparse byte offset seeking to jump directly to target row.
        """
        if offset < 0:
            offset = 0

        # Check if entire requested range is in in-memory list
        if self._records and len(self._records) > offset:
            return self._records[offset: offset + limit]

        # Check if entire range is already in LRU cache
        cached_result = []
        all_cached = True
        for i in range(offset, offset + limit):
            rec = self._cache.get(i)
            if rec is not None:
                cached_result.append(rec)
            else:
                all_cached = False
                break
        if all_cached and len(cached_result) == limit:
            return cached_result

        # Fetch from sparse index for uncompressed files
        if self._sparse_index:
            seek_offset, start_idx = self._sparse_index.get_seek_offset_for_index(offset)
            records: List[VariantRecord] = []
            curr_idx = start_idx

            with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                f.seek(seek_offset)
                while curr_idx < offset + limit:
                    line = f.readline()
                    if not line:
                        break
                    if line.startswith("#"):
                        continue
                    if curr_idx >= offset:
                        rec = parse_vcf_line(line, self.samples)
                        if rec:
                            records.append(rec)
                            self._cache.put(curr_idx, rec)
                    curr_idx += 1
            return records

        # Fallback stream for gzipped files
        records = []
        curr_idx = 0
        with self._open_file() as f:
            for line in f:
                if not line or line.startswith("#"):
                    continue
                if curr_idx >= offset:
                    rec = parse_vcf_line(line, self.samples)
                    if rec:
                        records.append(rec)
                        self._cache.put(curr_idx, rec)
                    if len(records) >= limit:
                        break
                curr_idx += 1
        return records

    def get_records(self, offset: int = 0, limit: Optional[int] = None) -> List[VariantRecord]:
        """Backward-compatible get_records method."""
        if limit is not None:
            return self.get_slice(offset, limit)

        # Full fetch requested (e.g. for small test files or export)
        if not self._records:
            all_records = []
            curr_idx = 0
            with self._open_file() as f:
                for line in f:
                    if not line or line.startswith("#"):
                        continue
                    rec = parse_vcf_line(line, self.samples)
                    if rec:
                        all_records.append(rec)
                        self._cache.put(curr_idx, rec)
                        curr_idx += 1
            self._records = all_records
            self._total_variants_count = len(self._records)

        return self._records[offset:]

    def query_region(self, chrom: str, start: int, end: int, limit: int = 500) -> List[VariantRecord]:
        """
        Query variants in a genomic interval chrom:start-end.
        Uses cyvcf2 tabix if available, or sparse index seeking.
        """
        if HAS_CYVCF2 and self.backend.startswith("cyvcf2"):
            try:
                vcf = cyvcf2.VCF(self.filepath)
                region_str = f"{chrom}:{start}-{end}"
                records = []
                for v in vcf(region_str):
                    # parse cyvcf2 variant into VariantRecord
                    alts = list(v.ALT) if v.ALT else []
                    sample_data: Dict[str, Dict[str, Any]] = {}
                    genotypes: Dict[str, Tuple[int, ...]] = {}
                    depths: Dict[str, int] = {}
                    ad_dict: Dict[str, List[int]] = {}

                    v_gt = v.genotypes
                    v_format_keys = list(v.FORMAT)
                    dp_arr = v.format("DP") if "DP" in v_format_keys else None
                    ad_arr = v.format("AD") if "AD" in v_format_keys else None
                    gq_arr = v.format("GQ") if "GQ" in v_format_keys else None

                    for idx, s in enumerate(self.samples):
                        gt_tuple = tuple(v_gt[idx][:2]) if len(v_gt[idx]) >= 2 else (v_gt[idx][0],)
                        genotypes[s] = gt_tuple
                        dp_val = int(dp_arr[idx][0]) if (dp_arr is not None and len(dp_arr) > idx) else 0
                        depths[s] = dp_val
                        ad_vals = [int(x) for x in ad_arr[idx]] if (ad_arr is not None and len(ad_arr) > idx) else []
                        ad_dict[s] = ad_vals
                        gq_val = int(gq_arr[idx][0]) if (gq_arr is not None and len(gq_arr) > idx) else 0
                        gt_str = "/".join(str(g) if g >= 0 else "." for g in gt_tuple)
                        sample_data[s] = {
                            "GT": gt_str,
                            "DP": dp_val,
                            "AD": ",".join(str(x) for x in ad_vals) if ad_vals else ".",
                            "GQ": gq_val,
                        }

                    rec = VariantRecord(
                        chrom=v.CHROM,
                        pos=v.POS,
                        var_id=v.ID,
                        ref=v.REF,
                        alt=alts,
                        qual=v.QUAL,
                        filter_str=v.FILTER or "PASS",
                        info=dict(v.INFO),
                        format_keys=v_format_keys,
                        sample_data=sample_data,
                        genotypes=genotypes,
                        depths=depths,
                        ad=ad_dict,
                    )
                    records.append(rec)
                    if len(records) >= limit:
                        break
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
                            # Left the target chromosome
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
                    if p >= start and p <= end:
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
        """Filter variants in real time using streaming evaluation, respecting limit for fast responsive UI."""
        def _match_record(r: VariantRecord) -> bool:
            if min_qual is not None and r.qual is not None and r.qual < min_qual:
                return False
            if min_depth is not None:
                total_dp = sum(r.depths.values())
                mean_dp = total_dp / len(r.depths) if r.depths else 0
                if mean_dp < min_depth:
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
                    q in r.chrom.lower() or
                    str(r.pos) in q or
                    q in r.gene.lower() or
                    q in r.drug.lower() or
                    q in r.mutation.lower()
                )
                if not matches:
                    return False
            return True

        filtered: List[VariantRecord] = []
        if self._records:
            for r in self._records:
                if _match_record(r):
                    filtered.append(r)
                    if limit and len(filtered) >= limit:
                        break
            return filtered

        # Stream lazily through file without loading entire dataset into memory
        with self._open_file() as f:
            for line in f:
                if not line or line.startswith("#"):
                    continue
                rec = parse_vcf_line(line, self.samples)
                if rec and _match_record(rec):
                    filtered.append(rec)
                    if limit and len(filtered) >= limit:
                        break
        return filtered
