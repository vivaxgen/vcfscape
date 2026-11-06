# Seamless Buffer Scrolling & Exact Chromosome Preservation Plan

Fix the virtual row windowing in both the Textual TUI and Web interface so scrolling down past row 150 smoothly auto-shifts the active slice without getting stuck, preserves exact chromosome names without substring stripping, and guarantees flicker-free cursor and selection tracking.

---

### User Review & Critical Decisions

> [!IMPORTANT]
> The following confirmed decisions govern this implementation:
> - **Buffer Navigation**: Auto-shift the virtual row window dynamically whenever cursor navigation or mouse scrolling approaches or crosses buffer boundaries, keeping the cursor continuously in view.
> - **Exact Chromosome Representation**: Always display the full, authentic chromosome/contig name (e.g. `Pf3D7_13_v3`, `chr1`, `NC_000001.11`) without prefix stripping (`replace("Pf3D7_", ...)`) or suffix stripping (`replace("_v3", "")`).
> - **Background Count Decoupling**: Allow continuous forward and backward buffer streaming even while background variant counting is still running on large compressed files.

---

### 1. Overview & Core Concept

- **What It Does**: Enables fluid, continuous navigation down through multi-gigabyte VCF datasets across thousands of variants without hitting a hard wall at row 149. It ensures that chromosome names and genomic coordinates accurately represent the underlying VCF records across fixed columns, cell inspectors, and summary cards.
- **Target Audience**: Genomic epidemiologists, bioinformaticians, and surveillance lab technicians reviewing high-throughput Plasmodium and pathogen VCF files.
- **Key Value**: Eliminates navigational lockup and coordinate corruption when exploring large genomic datasets in both terminal TUI and web browser environments.

---

### 2. User Experience & Visual Design

- **Continuous Scroll Flow**:
  - As the user scrolls down using the **Down Arrow**, **Page Down**, or **Mouse Wheel**, the table seamlessly shifts the 150-variant window forward (e.g., from variants 0–149 to 40–189, 80–229, etc.).
  - The cursor remains anchored to the user's intended genomic record without jumping to the top or leaving the active screen.
  - Upward scrolling dynamically shifts the window backward until reaching row 0.
- **Visual Identity & Theme**:
  - Adheres to the **Science, Space & Biotech** visual design standard: 60% clinical dark obsidian (`#0b0f17`) / light lab slate (`#f8fafc`), 30% structural panels with 1px hairline dividers (`#1e293b`), and 10% precision cyan (`#06b6d4`) / emerald (`#10b981`) telemetry accents.
  - All chromosome/contig identifiers are rendered in crisp monospace (`font-mono tabular-nums`) with adequate column width to prevent ellipsis truncation or cell bleeding.
- **Flicker-Free Locus Feedback**:
  - The right-hand Variant Summary, Cell Inspector, and split Cohort Statistics pane smoothly display the active locus (`{chrom}:{pos}`) in real time without momentary index desynchronization.

---

### 3. Key Technical Decisions & Trade-Offs

- **Decision 1: Container-Level Key Handling & Dynamic Scroll Hooking in Textual**:
  - *Chosen Approach*: Intercept `action_cursor_down`, `action_cursor_up`, `action_page_down`, and `action_page_up` in `FixedVariantTable` and `SampleMatrixTable`. When the cursor is at the bottom row of the current 150-variant buffer, trigger `shift_buffer()` directly rather than relying solely on Textual's internal highlight event (which is suppressed when the cursor cannot move further down).
  - *Why*: Textual's default `DataTable.action_cursor_down` is a no-op when the cursor is already at `len(records) - 1`. Intercepting the boundary action guarantees immediate buffer streaming.
- **Decision 2: Elimination of Chromosome String Replacements**:
  - *Chosen Approach*: Remove all calls to `.replace("Pf3D7_", ...)` and `.replace("_v3", ...)` in `VariantSplitView.rebuild_fixed_table`, `VariantSummary.render`, and the Web `VariantTable.tsx`.
  - *Why*: Unconditional substring replacement corrupts standard non-malaria contigs (`chr1`, `scaffold_3_v3`) and violates the user's explicit requirement to keep chromosome names exactly as they are.
- **Decision 3: Dynamic Column Width for Contigs**:
  - *Chosen Approach*: Compute the minimum required CHROM column width dynamically from the active records (or provide generous auto-fit width up to 18 characters) instead of hardcoding a narrow 6-character limit.
- **Decision 4: Decouple Buffer Shifting from Total Variant Count Availability**:
  - *Chosen Approach*: If `total_records_count` is `None` (because the background counter thread is still reading a multi-gigabyte gzip stream), allow shifting forward as long as `self.reader.get_slice()` returns records.

---

### 4. Technical Architecture & Component Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             VcfscapeApp (TUI)                                │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                              HeaderBar                                │  │
│  │   Filename │ Genome: Pf3D7 │ Vars: 1,420,891 │ View: Normal │ Tag: GT │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┬───────────────────────┐  │
│  │               VariantSplitView                │     SidebarPanel      │  │
│  │                                               │                       │  │
│  │  ┌─────────────────┬───┬───────────────────┐  │  ┌─────────────────┐  │  │
│  │  │FixedVariantTable│ │ │ SampleMatrixTable │  │  │ CohortListWidget│  │  │
│  │  │  (Unmodified    │ │ │  (Dynamic window  │  │  └─────────────────┘  │  │
│  │  │   CHROM + POS)  │ │ │   visible samples)│  │  ┌─────────────────┐  │  │
│  │  └─────────────────┴───┴───────────────────┘  │  │ VariantSummary  │  │  │
│  │           ▲                      ▲            │  │ (Exact CHROM)   │  │  │
│  │           │                      │            │  └─────────────────┘  │  │
│  │    [Boundary Keys]        [Wheel Scroll]      │  ┌─────────────────┐  │  │
│  │           └──────────┬───────────┘            │  │  CellInspector  │  │  │
│  │                      ▼                        │  └─────────────────┘  │  │
│  │           shift_buffer(new_start)             │                       │  │
│  │                      │                        └───────────────────────┘  │
│  │                      ▼                                                   │
│  │            VcfReader.get_slice()                                         │
│  │         (Sparse Index / LRU Cache)                                       │
│  └───────────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │               CohortStatsPane (Collapsible split pane)                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Component & Implementation Steps

1. **Textual Table Interception (`src/vcfscape/ui/widgets/variant_table.py`)**:
   - Update `FixedVariantTable` and `SampleMatrixTable` key actions:
     - On `action_cursor_down`, if `cursor_row >= len(self.records) - 1`, call the parent's `shift_buffer` down by step.
     - On `action_cursor_up`, if `cursor_row <= 0` and `buffer_start > 0`, call `shift_buffer` up by step.
     - In `on_mouse_scroll_down` and `on_mouse_scroll_up`, check if scroll position is at the boundary and request buffer shift.
   - In `shift_buffer`:
     - Allow forward shift even if `total_records_count` is `None` or provisional.
     - Synchronize `self.current_row_idx` to the new offset relative position *before* calling `rebuild_tables()`.
     - Suppress duplicate notification events during rebuild to avoid locus flicker.
   - In `rebuild_fixed_table`:
     - Render `r.chrom` directly without `.replace("Pf3D7_", ...)` or `.replace("_v3", ...)`.
     - Expand `FIXED_WIDTHS` appropriately so chromosome names up to 16–20 characters display cleanly without overlapping position numbers.

2. **Sidebar & Summary Locus Display (`src/vcfscape/ui/widgets/variant_summary.py`)**:
   - In `VariantSummary.render`, replace `chrom_short = r.chrom.replace(...)` with `r.chrom` directly.
   - Display full chromosome names in the Locus field (`{r.chrom}:{r.pos:,}`).

3. **Web Virtual Table Synchronization (`src/components/VariantTable.tsx`)**:
   - In `src/components/VariantTable.tsx`, remove `.replace("Pf3D7_", "").replace("_v3", "")` from line 342 and lines 387, 402, 412.
   - Display `v.chrom` intact across all view modes (`raw`, `compact`, `essential`, `normal`).
   - Adjust column min-width and truncate styling so full contig names render without collision.

4. **Automated Verification**:
   - Run unit test suite: `python3 -m unittest discover tests`.
   - Add/verify automated test for buffer boundary shifting and chromosome name integrity.
   - Compile and lint TypeScript codebase (`compile_applet` and `lint_applet`).
