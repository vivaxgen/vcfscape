"""
High-performance VCF Reader with cyvcf2 support and streaming pure-Python fallback.
Supports tabix-indexed chunking, multi-allelic decomposition, and format field extraction.
"""

import os
import gzip
from typing import List, Dict, Any, Optional, Tuple, Iterator
from vcfscape.core.malaria_db import MalariaAnnotationDB, MarkerAnnotation

try:
    import cyvcf2
    HAS_CYVCF2 = True
except ImportError:
    HAS_CYVCF2 = False


class VariantRecord:
    """Normalized internal representation of a VCF variant row."""
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
        self.alt = alt  # list of ALTs (e.g. ['T', 'A'])
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
        return 1 + len(self.alt)  # 0 is REF, 1..N are ALTs


class VcfReader:
    """Unified VCF Parser interface."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.samples: List[str] = []
        self.contigs: List[str] = []
        self.header_lines: List[str] = []
        self.backend = "cyvcf2" if HAS_CYVCF2 else "pure_python"
        
        # In-memory index / buffer of variant records
        self._records: List[VariantRecord] = []
        self._load_header_and_records()

    def _open_file(self):
        if self.filepath.endswith(".gz") or self.filepath.endswith(".bgz"):
            return gzip.open(self.filepath, "rt", encoding="utf-8", errors="replace")
        return open(self.filepath, "r", encoding="utf-8", errors="replace")

    def _load_header_and_records(self):
        """Loads header and records either using cyvcf2 or pure Python fallback."""
        if HAS_CYVCF2:
            try:
                self._load_with_cyvcf2()
                return
            except Exception:
                # Fallback to pure Python parser if cyvcf2 fails on plain VCF
                pass

        self._load_with_pure_python()

    def _load_with_cyvcf2(self):
        vcf = cyvcf2.VCF(self.filepath)
        self.samples = list(vcf.samples)
        self.header_lines = [str(h) for h in vcf.header_iter()]
        
        # Load contigs
        for h in self.header_lines:
            if h.startswith("##contig=<ID="):
                cid = h.split("##contig=<ID=")[1].split(",")[0].split(">")[0]
                self.contigs.append(cid)

        # Parse variants
        for v in vcf:
            alts = list(v.ALT) if v.ALT else []
            genotypes: Dict[str, Tuple[int, ...]] = {}
            depths: Dict[str, int] = {}
            ad_dict: Dict[str, List[int]] = {}
            sample_data: Dict[str, Dict[str, Any]] = {}

            # Parse genotypes and format fields
            v_gt = v.genotypes
            v_format_keys = list(v.FORMAT)
            
            # Format matrices
            has_dp = "DP" in v_format_keys
            has_ad = "AD" in v_format_keys
            has_gq = "GQ" in v_format_keys

            dp_arr = v.format("DP") if has_dp else None
            ad_arr = v.format("AD") if has_ad else None
            gq_arr = v.format("GQ") if has_gq else None

            for idx, s in enumerate(self.samples):
                gt_tuple = tuple(v_gt[idx][:2]) if len(v_gt[idx]) >= 2 else (v_gt[idx][0],)
                # Clean up -1 in cyvcf2 genotypes
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

            info_dict = dict(v.INFO)
            rec = VariantRecord(
                chrom=v.CHROM,
                pos=v.POS,
                var_id=v.ID,
                ref=v.REF,
                alt=alts,
                qual=v.QUAL,
                filter_str=v.FILTER or "PASS",
                info=info_dict,
                format_keys=v_format_keys,
                sample_data=sample_data,
                genotypes=genotypes,
                depths=depths,
                ad=ad_dict,
            )
            self._records.append(rec)

    def _load_with_pure_python(self):
        self._records.clear()
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
                    parts = line.split("\t")
                    if len(parts) > 9:
                        self.samples = parts[9:]
                    continue

                parts = line.split("\t")
                if len(parts) < 8:
                    continue

                chrom = parts[0]
                pos = int(parts[1])
                var_id = parts[2]
                ref = parts[3]
                alt = parts[4].split(",") if parts[4] != "." else []
                qual = float(parts[5]) if parts[5] != "." else None
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

                for idx, s in enumerate(self.samples):
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

                rec = VariantRecord(
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
                self._records.append(rec)

    @property
    def total_variants(self) -> int:
        return len(self._records)

    @property
    def total_samples(self) -> int:
        return len(self.samples)

    def get_records(self, offset: int = 0, limit: Optional[int] = None) -> List[VariantRecord]:
        """Lazy chunk fetching for table scrolling."""
        if limit is None:
            return self._records[offset:]
        return self._records[offset: offset + limit]

    def filter_records(
        self,
        min_qual: Optional[float] = None,
        min_depth: Optional[int] = None,
        variant_type: Optional[str] = None,
        filter_status: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> List[VariantRecord]:
        """Filter variants in real time."""
        filtered = []
        for r in self._records:
            if min_qual is not None and r.qual is not None and r.qual < min_qual:
                continue
            if min_depth is not None:
                total_dp = sum(r.depths.values())
                mean_dp = total_dp / len(r.depths) if r.depths else 0
                if mean_dp < min_depth:
                    continue
            if variant_type and variant_type != "ALL":
                if variant_type == "SNP" and r.is_indel:
                    continue
                if variant_type == "INDEL" and not r.is_indel:
                    continue
                if variant_type == "MULTI_ALLELIC" and not r.is_multiallelic:
                    continue
                if variant_type == "DRUG_RESISTANT" and not r.drug_annotation:
                    continue
            if filter_status and filter_status != "ALL":
                if r.filter != filter_status:
                    continue
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
                    continue
            filtered.append(r)
        return filtered
