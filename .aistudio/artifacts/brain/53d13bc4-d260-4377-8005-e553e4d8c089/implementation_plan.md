# High-Performance VCF Engine: Fast Startup & Instant Pointer Movement

Comprehensive architectural implementation plan to eliminate startup unresponsiveness and achieve instantaneous cursor/pointer movement in both the Textual TUI and Web versions when loading very large multi-gigabyte, multi-sample VCF files.

---

## User Review & Critical Decisions

> [!IMPORTANT]
> The following decisions were confirmed to govern the performance architecture:

- **Confirmed Decision 1 (Startup Variant Counting)**: **Instant startup with asynchronous background counter**. The application will display the first slice of variant rows and mount the UI immediately (< 30ms). Total variant counting for `.vcf.gz` files will execute in a lightweight background thread and seamlessly update the header once complete.
- **Confirmed Decision 2 (Sample Column Scaling)**: **Dynamic horizontal windowing of visible sample columns in Textual**. Rather than adding hundreds or thousands of sample columns to Textual's in-memory `DataTable` (which explodes to 150,000+ cells and slows down cursor movement), the TUI will dynamically window sample columns to the visible viewport width (20–30 columns).
- **Confirmed Decision 3 (Web Large File Safeguard)**: **Preview first 1,000 variants with server recommendation for big files**. Direct browser file uploads will stream the first 1,000 variants without loading gigabytes of raw text into memory, displaying a notification recommending the local Python streaming server (`vcfscape-web`) for full-file exploration.

---

## 1. Overview & Core Concept

### What It Does
Empowers malaria researchers and genomic surveillance teams to open multi-gigabyte, multi-sample VCF files (`.vcf` and `.vcf.gz`) with **zero initial startup lag (< 30ms)** and **silky-smooth pointer/cursor navigation (60 FPS, < 2ms latency per keystroke)** in both the Textual terminal interface and the Web simulator.

### Target Audience & Persona
Field epidemiologists, bioinformaticians, and genomic surveillance researchers inspecting large-scale *Plasmodium falciparum* and *P. vivax* datasets with 500 to 2,500 clinical isolates and hundreds of thousands of genetic markers.

### Key Value Delivered
- **Zero Startup Wait**: The UI is usable instantly upon launching `vcfscape` or `vcfscape-web`, eliminating 30–120 second freezes on cold start.
- **Fluid Keyboard Navigation**: Arrow keys respond instantly without dropped frames or input lag.
- **Zero Window Edge Stutter**: Scrolling across row buffer boundaries remains smooth without full-table DOM or `DataTable` rebuilds.
- **Memory Safety**: Prevents browser tab crashes and terminal memory exhaustion.

---

## 2. User Experience & Visual Design

### TUI Experience (Textual)
1. **Immediate Zero-State Launch**: Terminal window opens within 30 milliseconds. Fixed variant metadata columns (CHROM, POS, REF, ALT, QUAL, FILTER, GENE) and the initial viewport of sample genotype cells appear populated.
2. **Asynchronous Header Indicator**: 
   - While counting in the background, the header displays `Variants: Counting...` with total samples and active backend.
   - Upon completion, the header updates to the exact count (e.g. `Variants: 142,500 | Samples: 850`) without interrupting user navigation.
3. **Responsive Pointer Movement**:
   - Arrow keys (`Up`/`Down`/`Left`/`Right`) highlight cells immediately without lag.
   - When cursor reaches the horizontal boundary of visible samples, sample columns slide smoothly with dynamic header labels.
   - Sidebar panels (`VariantSummary`, `CohortListWidget`, `CellInspector`) update in real time without queuing up stale renders.

### Web Experience
1. **Streaming Load**: When connected to `vcfscape-web`, metadata and initial variant slices load concurrently.
2. **Client-Side File Upload Modal**:
   - Dragging a 500 MB+ VCF directly into the browser streams the first 1,000 variants in chunks using `ReadableStream`.
   - A quiet banner at the top of the table informs the user:
     `Displaying first 1,000 variants. For full multi-gigabyte dataset streaming, run vcfscape-web <file.vcf>.`
3. **Horizontal Virtualization**: Only visible sample columns within the scroll container are rendered in the DOM, eliminating layout recalculation overhead on 1,000+ sample datasets.

---

## 3. Key Product Decisions & Trade-Offs

### Decision 1: Asynchronous Background Counting vs. Blocking Exact Count
- **Chosen Approach**: Start immediately with an indeterminate count indicator (`Variants: Counting...`), run line counting in a background daemon thread, and dispatch a thread-safe update event to the UI upon completion.
- **Why**: Counting millions of compressed lines in Python gzip takes 30–120 seconds. Blocking startup for a decorative total count destroys user experience.
- **Alternatives Considered**: 
  - *Estimating based on file size*: Highly inaccurate for VCF files due to variable INFO field lengths and sample counts.
  - *No count at all*: Users need to know total variant volume for surveillance context.

### Decision 2: Horizontal Column Windowing in Textual DataTable
- **Chosen Approach**: Dynamically mount only the horizontal slice of sample columns that fit the terminal viewport (plus 5 overscan columns on either side) into Textual's `DataTable`. As the cursor moves left/right, shift the active sample window.
- **Why**: Textual's `DataTable` recalculates layout coordinates across all columns on every cursor move. Reducing columns from 1,000 to ~25 cuts cell widgets from 150,000 to ~3,000, reducing cursor latency from ~60ms down to < 2ms.
- **Alternatives Considered**: 
  - *Full pagination*: Forces users to manually press `Page Left` / `Page Right`, breaking natural arrow-key navigation.

### Decision 3: Fast Sparse Indexing with Resilient Cache Fallback
- **Chosen Approach**: 
  1. Optimize `SparseVcfIndex._build_index` to read 4 MB binary chunks and track newline offsets in memory instead of calling `f.tell()` per line.
  2. If writing to `.{basename}.vcfscape.idx` in the file's parent folder fails (e.g., read-only shared cluster folders), automatically fall back to saving in `~/.cache/vcfscape/<hash>.idx`.
- **Why**: Speeds up index building by > 2× and guarantees that shared/read-only VCFs are cached after the first run.

---

## 4. Technical Architecture & Data Strategy

```
┌────────────────────────────────────────────────────────────────────────┐
│                        VCFscape Engine Architecture                    │
└────────────────────────────────────────────────────────────────────────┘
                                    │
           ┌────────────────────────┴────────────────────────┐
           ▼                                                 ▼
┌───────────────────────┐                         ┌───────────────────────┐
│     Textual TUI       │                         │    Web Simulator      │
└───────────────────────┘                         └───────────────────────┘
           │                                                 │
           ▼                                                 ▼
┌─────────────────────────┐                       ┌─────────────────────────┐
│ Dynamic Column Window   │                       │ Column Virtualization   │
│ (25 Visible Samples)    │                       │ (DOM Windowing)         │
└─────────────────────────┘                       └─────────────────────────┘
           │                                                 │
           └────────────────────────┬────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Unified VcfReader Core                           │
│  - Instant Header Extraction (< 15ms)                                  │
│  - Async Background Counter Thread                                     │
│  - LRU Record Cache (3,000 variants)                                   │
└────────────────────────────────────────────────────────────────────────┘
          │                                                  │
          ▼                                                  ▼
┌──────────────────────────────────┐        ┌────────────────────────────┐
│   Uncompressed VCF (.vcf)        │        │   Compressed VCF (.vcf.gz) │
│   - Fast 4MB Chunked Indexer     │        │   - Tabix / cyvcf2 Seeking │
│   - Fallback ~/.cache/vcfscape/  │        │   - Async line counting    │
└──────────────────────────────────┘        └────────────────────────────┘
```

### Component & State Mapping

| Component | File / Area | Key Enhancements |
| :--- | :--- | :--- |
| `VcfReader` | `src/vcfscape/core/vcf_reader.py` | Asynchronous background counting with callback; fast Tabix seek slice support; lazy streaming in `filter_records`. |
| `SparseVcfIndex` | `src/vcfscape/core/indexer.py` | 4 MB chunk-based byte-offset builder (eliminating per-line `f.tell()`); fallback caching to `~/.cache/vcfscape/`. |
| `VariantSplitView` | `src/vcfscape/ui/widgets/variant_table.py` | Horizontal column windowing (viewport + overscan); in-place row updates in `shift_buffer`; throttled sidebar selection notifications. |
| `VcfscapeApp` | `src/vcfscape/ui/app.py` | Initial load uses fast slice without waiting for variant count; receives thread-safe total variant count message and updates `HeaderBar`. |
| `web_server.py` | `src/vcfscape/web_server.py` | Non-blocking server startup; background metadata hydration; chunked API responses. |
| `vcfParser.ts` | `src/utils/vcfParser.ts` | Incremental stream reader parsing first 1,000 variants for browser file picker; payload size warning. |
| `VariantTable.tsx` | `src/components/VariantTable.tsx` | Horizontal sample column DOM virtualization; smooth horizontal scroll synchronization. |

---

## 5. Verification & Testing Strategy

1. **Python Unit Tests**:
   - Test `VcfReader` asynchronous total variants counting without blocking init.
   - Test `SparseVcfIndex` fast chunked indexing and cache path fallback.
   - Test `VariantSplitView` column windowing and cursor navigation.
   - Execute full test suite via `python3 -m unittest discover tests`.
2. **Synthetic Large-Dataset Benchmarks**:
   - Verify uncompressed 100,000-variant file startup time < 50ms.
   - Verify block-gzipped 100,000-variant file startup time < 50ms.
   - Verify single arrow key latency < 5ms with 1,000 samples.
3. **Web Simulator Verification**:
   - Run `compile_applet` and `lint_applet` to guarantee clean TypeScript typing and build.
   - Verify 1,000-sample horizontal scroll fluidity in browser preview.
