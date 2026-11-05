# Implementation Plan: High-Performance Big VCF Handling & Virtual Windowing

## 1. Executive Summary

This plan outlines the architecture and implementation steps to scale **vcfscape** (both the Textual TUI and Web interface) to handle massive VCF datasets (100,000+ variants, hundreds to thousands of samples/isolates, and multi-gigabyte files). 

The goal is to achieve **near-instant startup (< 200ms)** and **fluid 60 FPS scrolling and zooming** by moving away from eager whole-file loading and replacing it with:
1. **Dual Indexing Engine**: Native Tabix/CSI indexing for bgzipped VCFs (`.vcf.gz`), alongside a lightweight sparse byte-offset index for uncompressed `.vcf` files.
2. **Windowed / Paginated Backend API**: A streaming chunk loader in Python (`vcfscape-web`) that serves windowed variant slices and sample genotypes with an LRU cache.
3. **Textual TUI Virtual Windowing**: Dynamic row replacement and viewport-bound buffer in Textual `DataTable`, keeping memory minimal and rendering instantaneous.
4. **Web UI Virtual Matrix**: Virtualized table rows and columns with horizontal/vertical viewport clipping, prefetching, and coordinate-based region jumping.

---

## 2. Architecture & Data Flow

```
                      ┌──────────────────────────────────────────────┐
                      │              VCF Data Source                 │
                      │  - Block-Gzipped (.vcf.gz + .tbi / .csi)     │
                      │  - Uncompressed (.vcf + .vcf.idx / in-mem)   │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │           IndexedVcfEngine (Python)          │
                      │  - Fast header-only parse on launch          │
                      │  - Genomic region slicing (chr:start-end)     │
                      │  - Numeric offset windowing (start, limit)   │
                      │  - Sparse byte-offset index builder          │
                      │  - Record LRU cache (1,000-5,000 records)    │
                      └──────────────┬───────────────────────────────┘
                                     │
           ┌─────────────────────────┴────────────────────────┐
           ▼                                                  ▼
┌─────────────────────────────┐                    ┌────────────────────────────┐
│      Textual TUI Core       │                    │    vcfscape-web Server     │
│ - Virtual Row Window Buffer │                    │ - REST / Streaming API:    │
│ - Over-the-wire paging on   │                    │   /api/meta                │
│   scroll event boundaries   │                    │   /api/variants (paged)    │
│ - Region jump modal         │                    │   /api/genotypes (chunked) │
└─────────────────────────────┘                    └──────────────┬─────────────┘
                                                                  │ HTTP/JSON
                                                                  ▼
                                                   ┌────────────────────────────┐
                                                   │       React Web App        │
                                                   │ - @tanstack/react-virtual  │
                                                   │   or custom windowing      │
                                                   │ - Jump to Gene/Region      │
                                                   │ - Sample matrix col-virtual│
                                                   └────────────────────────────┘
```

---

## 3. Detailed Components & Implementation Steps

### Phase 1: Python Core Dual Indexing Engine (`src/vcfscape/core/`)

1. **`VcfIndexManager`**:
   - **Tabix / CSI (`.vcf.gz`)**:
     - Check for `.tbi` or `.csi`. If missing, attempt automatic indexing or fallback to streaming.
     - Leverage `cyvcf2.VCF(path)` which natively supports tabix querying `vcf(f"{chrom}:{start}-{end}")`.
     - Read header metadata (samples, contigs/chromosomes, filters, info/format fields) in < 15ms without parsing records.
   - **Uncompressed VCF (`.vcf`) Sparse Byte-Offset Index**:
     - Build or load a companion `.vcfscape.idx` binary file containing:
       - Header end byte offset.
       - Sparse index array: every $N$-th variant (e.g., every 500 variants), store `(variant_index, chrom, pos, byte_offset)`.
       - On a 1GB uncompressed VCF, indexing takes ~0.5s in Python or can be generated in background on first load while displaying the first 200 records immediately.
       - Binary search in the sparse index to seek (`file.seek(offset)`) and yield exact slices of variants on demand.
2. **`IndexedVcfReader`**:
   - Refactor `VcfReader` to distinguish between `metadata` (instant) and `records` (lazy).
   - Implement `get_total_count() -> int` (estimated from index or known exact count).
   - Implement `get_slice(offset: int, limit: int) -> List[VariantRecord]`.
   - Implement `query_region(chrom: str, start: int, end: int, limit: int = 500) -> List[VariantRecord]`.
   - Cache decoded records in an internal `collections.OrderedDict` LRU cache (e.g., 2,000 records max).

---

### Phase 2: Web Server Streaming API (`src/vcfscape/web_server.py`)

1. **API Endpoints**:
   - `GET /api/metadata`:
     - Returns dataset summary: filename, file format (tabix/uncompressed), sample list, sample count, contigs/chromosomes with lengths, total variant count (or estimate).
   - `GET /api/variants?offset=0&limit=100`:
     - Returns variant rows for the requested window: chrom, pos, id, ref, alt, qual, filter, info summary, and total count.
   - `GET /api/region?chrom=Pf3D7_07_v3&start=400000&end=450000&limit=200`:
     - Returns variants within genomic bounds for coordinate jumping.
   - `GET /api/matrix?offset=0&limit=100&sample_start=0&sample_limit=50`:
     - Returns the 2D genotype / sample matrix for the visible variant window and visible sample subset, preventing heavy payload transfer when dealing with 1,000+ isolates.
2. **Compression & Serialization**:
   - Enable `gzip` / `deflate` transfer encoding in Python server responses.
   - Compact JSON format for genotypes (integer-encoded or minimal tuple representation: `[GT, AD, DP, GQ]`).

---

### Phase 3: Textual TUI Virtual Windowing (`src/vcfscape/ui/`)

1. **`VirtualVariantTable` & `VirtualSampleMatrix`**:
   - Replace eager `table.add_row` of all rows with a **sliding window buffer**:
     - Maintain a buffer of visible rows plus a padding buffer (e.g. 150 rows above and below current scroll position).
     - As the cursor moves up/down or page-up/page-down triggers, if the cursor approaches buffer thresholds (< 30 rows from margin), asynchronously fetch the next slice from `IndexedVcfReader` and update rows.
     - Keep total live rows in `DataTable` bounded to ~300 rows to ensure snappy UI rendering without widget hierarchy lag.
2. **Genomic Coordinate & Chromosome Jump Dialog**:
   - Pressing `Ctrl+G` or `:` opens a quick-jump dialog:
     - Select Chromosome / Contig.
     - Enter genomic coordinate (e.g., `Pf3D7_07_v3:403000`).
     - Seek immediately via tabix index or sparse index, repopulating viewport in under 50ms.

---

### Phase 4: Web UI Virtualization & Smooth Scrolling (`src/components/`)

1. **Virtual Grid Matrix**:
   - Integrate virtualization for the variant table rows and horizontal sample matrix columns.
   - Keep fixed left columns (Variant ID, Position, Ref/Alt) pinned while horizontally scrolling the sample matrix.
2. **Chunk Prefetching**:
   - Maintain a sliding window cache in React (`useVcfChunkLoader` hook).
   - Automatically prefetch adjacent chunk `[offset - limit, offset + 2 * limit]` in background while rendering current viewport.
3. **Region / Gene Selector**:
   - Coordinate navigation bar with quick selector for Plasmodium falciparum / standard chromosomes.
   - Direct jump to gene loci (e.g., *crt*, *k13*, *dhfr*, *mdr1*) with instant coordinate-based window reload.

---

## 4. Verification & Testing Strategy

1. **Unit & Benchmark Tests (`tests/test_vcf_indexing.py`)**:
   - Verify `IndexedVcfReader` on indexed `.vcf.gz` (tabix lookup by coordinate).
   - Verify sparse index generator on large uncompressed `.vcf` (seeking by offset).
   - Benchmark: Ensure startup time on 50MB-1GB VCF is < 200ms.
   - Benchmark: Ensure slice query of 100 rows completes in < 15ms.
2. **TUI Tests**:
   - Verify scrolling past window boundary triggers transparent chunk reload without breaking selected cell or cursor position.
   - Test horizontal scrolling and half-screen jumps across hundreds of sample columns.
3. **Web API Tests**:
   - Validate `/api/metadata`, `/api/variants`, and `/api/matrix` response times and payload sizes.
   - Verify end-to-end client rendering with 10,000+ variants.
