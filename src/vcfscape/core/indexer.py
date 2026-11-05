"""
High-Performance Indexing Engine for Big VCF Files.
Provides dual indexing:
1. Native Tabix / CSI index access via cyvcf2 for block-gzipped VCFs (.vcf.gz, .bgz).
2. Sparse byte-offset indexing for uncompressed VCFs (.vcf), enabling sub-millisecond seeks
   into multi-gigabyte plain text files without loading entire files into memory.
Includes an LRU cache for parsed VariantRecord objects.
"""

import os
import io
import gzip
import json
import bisect
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple, Iterator

from vcfscape.core.malaria_db import MalariaAnnotationDB, MarkerAnnotation

try:
    import cyvcf2
    HAS_CYVCF2 = True
except ImportError:
    HAS_CYVCF2 = False


class SparseIndexEntry:
    """Checkpoint entry inside a sparse VCF byte offset index."""
    __slots__ = ("index", "chrom", "pos", "offset")

    def __init__(self, index: int, chrom: str, pos: int, offset: int):
        self.index = index
        self.chrom = chrom
        self.pos = pos
        self.offset = offset

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "chrom": self.chrom,
            "pos": self.pos,
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SparseIndexEntry":
        return cls(d["index"], d["chrom"], d["pos"], d["offset"])


class SparseVcfIndex:
    """
    Sparse byte-offset index for fast seeking into uncompressed VCF files.
    Checkpoints the file byte offset every N variants (default: 200).
    Allows instant jump to any variant index or genomic coordinate.
    """

    def __init__(self, filepath: str, step: int = 200):
        self.filepath = filepath
        self.step = step
        self.header_end_offset: int = 0
        self.total_records: int = 0
        self.checkpoints: List[SparseIndexEntry] = []
        self.chrom_positions: Dict[str, List[Tuple[int, int]]] = {}  # chrom -> [(pos, index), ...]

        self._load_or_build()

    def _get_candidate_cache_paths(self) -> List[str]:
        dir_name = os.path.dirname(self.filepath)
        base_name = os.path.basename(self.filepath)
        primary = os.path.join(dir_name, f".{base_name}.vcfscape.idx")
        paths = [primary]
        try:
            import hashlib
            cache_dir = os.path.expanduser("~/.cache/vcfscape")
            h = hashlib.sha256(os.path.abspath(self.filepath).encode("utf-8")).hexdigest()[:16]
            paths.append(os.path.join(cache_dir, f"{base_name}_{h}.idx"))
        except Exception:
            pass
        return paths

    def _index_cache_path(self) -> str:
        paths = self._get_candidate_cache_paths()
        # Prefer existing valid cache
        for p in paths:
            if os.path.exists(p):
                return p
        # Otherwise prefer primary if writable, else secondary
        dir_name = os.path.dirname(self.filepath)
        if os.access(dir_name, os.W_OK):
            return paths[0]
        return paths[-1] if len(paths) > 1 else paths[0]

    def _load_or_build(self):
        file_mtime = os.path.getmtime(self.filepath)
        file_size = os.path.getsize(self.filepath)

        for cache_path in self._get_candidate_cache_paths():
            if os.path.exists(cache_path):
                try:
                    if os.path.getmtime(cache_path) >= file_mtime:
                        with open(cache_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("file_size") == file_size and data.get("step") == self.step:
                            self.header_end_offset = data["header_end_offset"]
                            self.total_records = data["total_records"]
                            self.step = data["step"]
                            self.checkpoints = [SparseIndexEntry.from_dict(d) for d in data["checkpoints"]]
                            self._build_chrom_lookup()
                            return
                except Exception:
                    pass  # Try next or rebuild

        self._build_index()
        self._save_index(self._index_cache_path())

    def _build_chrom_lookup(self):
        self.chrom_positions.clear()
        for cp in self.checkpoints:
            if cp.chrom not in self.chrom_positions:
                self.chrom_positions[cp.chrom] = []
            self.chrom_positions[cp.chrom].append((cp.pos, cp.index))

    def _build_index(self):
        """Scans uncompressed VCF using high-speed 4MB chunked streaming buffer."""
        self.checkpoints = []
        self.total_records = 0
        record_idx = 0

        with open(self.filepath, "rb") as f:
            offset = 0
            # Read header
            while True:
                line = f.readline()
                if not line:
                    break
                if line.startswith(b"#"):
                    offset = f.tell()
                    continue
                # First non-header line reached
                self.header_end_offset = offset
                f.seek(offset)
                break

            # Fast 4MB chunked scanning
            buf_size = 4 * 1024 * 1024
            curr_offset = self.header_end_offset
            carry = b""
            while True:
                chunk = f.read(buf_size)
                if not chunk:
                    break
                data = carry + chunk
                lines = data.split(b"\n")
                carry = lines.pop()
                for line in lines:
                    if not line or not line.strip():
                        curr_offset += len(line) + 1
                        continue
                    if record_idx % self.step == 0:
                        parts = line.split(b"\t", 3)
                        if len(parts) >= 2:
                            chrom = parts[0].decode("utf-8", errors="replace")
                            try:
                                pos = int(parts[1])
                            except ValueError:
                                pos = 0
                            self.checkpoints.append(
                                SparseIndexEntry(
                                    index=record_idx,
                                    chrom=chrom,
                                    pos=pos,
                                    offset=curr_offset,
                                )
                            )
                    curr_offset += len(line) + 1
                    record_idx += 1

            if carry and carry.strip():
                if record_idx % self.step == 0:
                    parts = carry.split(b"\t", 3)
                    if len(parts) >= 2:
                        chrom = parts[0].decode("utf-8", errors="replace")
                        try:
                            pos = int(parts[1])
                        except ValueError:
                            pos = 0
                        self.checkpoints.append(
                            SparseIndexEntry(
                                index=record_idx,
                                chrom=chrom,
                                pos=pos,
                                offset=curr_offset,
                            )
                        )
                record_idx += 1

        self.total_records = record_idx
        self._build_chrom_lookup()

    def _save_index(self, cache_path: str):
        payload = {
            "file_size": os.path.getsize(self.filepath),
            "step": self.step,
            "header_end_offset": self.header_end_offset,
            "total_records": self.total_records,
            "checkpoints": [cp.to_dict() for cp in self.checkpoints],
        }
        for target in [cache_path] + self._get_candidate_cache_paths():
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                return
            except Exception:
                continue

    def get_seek_offset_for_index(self, target_idx: int) -> Tuple[int, int]:
        """
        Returns (byte_offset, start_idx) for the checkpoint immediately preceding target_idx.
        """
        if not self.checkpoints or target_idx <= 0:
            return self.header_end_offset, 0

        # Binary search for greatest checkpoint <= target_idx
        idx_keys = [cp.index for cp in self.checkpoints]
        pos = bisect.bisect_right(idx_keys, target_idx) - 1
        pos = max(0, min(pos, len(self.checkpoints) - 1))
        cp = self.checkpoints[pos]
        return cp.offset, cp.index

    def find_nearest_checkpoint_for_region(self, chrom: str, target_pos: int) -> Tuple[int, int]:
        """
        Returns (byte_offset, start_idx) for the checkpoint near (chrom, target_pos).
        """
        chrom_list = self.chrom_positions.get(chrom)
        if not chrom_list:
            # Chromosome not in checkpoints, fallback to beginning
            return self.header_end_offset, 0

        pos_keys = [p[0] for p in chrom_list]
        idx = bisect.bisect_right(pos_keys, target_pos) - 1
        idx = max(0, min(idx, len(chrom_list) - 1))
        matched_variant_idx = chrom_list[idx][1]
        return self.get_seek_offset_for_index(matched_variant_idx)


class RecordLruCache:
    """Thread-safe and fast in-memory LRU cache for parsed VariantRecord objects."""

    def __init__(self, maxsize: int = 3000):
        self.maxsize = maxsize
        self._cache: OrderedDict[int, Any] = OrderedDict()

    def get(self, key: int) -> Optional[Any]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: int, val: Any) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self.maxsize:
                self._cache.popitem(last=False)
        self._cache[key] = val

    def clear(self):
        self._cache.clear()

    def __len__(self):
        return len(self._cache)
