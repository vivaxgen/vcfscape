# Buffer Window Scrolling & Pointer Stability Fix

Eliminates the pointer snapback problem when scrolling past variant buffer boundaries and sample column windows in the Textual TUI, ensuring smooth genomic record pinning and auto-centered horizontal sample navigation.

## User Review & Critical Decisions

> [!IMPORTANT]
> The following user preferences were confirmed during clarification and govern the implementation:

- **Confirmed Decision 1 (Vertical Pointer Behavior)**: **Pin cursor to exact genomic record smoothly**. When the vertical row buffer slides forward or backward, the active cursor remains anchored to the exact same genomic locus and maintains its visual viewport position rather than snapping backwards or disorienting the user.
- **Confirmed Decision 2 (Horizontal Sample Navigation)**: **Auto-center active sample column in viewport**. When navigating across sample columns with arrow keys, the active sample column is dynamically centered within the visible matrix viewport with zero snapback.

---

## 1. Overview & Core Concept

When navigating large genomic datasets with hundreds of thousands of variants and dozens of sample columns, `vcfscape` uses dynamic sliding windows to achieve instant startup (<15ms) and memory efficiency:
1. **Vertical Variant Buffer Window**: A sliding slice of variants (150 rows) loaded from disk into memory.
2. **Horizontal Sample Column Window**: A sliding subset of sample columns rendered in the matrix view.

### The Problem
Previously, when the user navigated past row ~135 or column ~23, the buffer shifted by a fixed block step (`step = 40` or `step = 8`). During the shift, the table recalculated the relative local cursor index (`new_cursor = old_cursor - step`) and cleared/rebuilt the `DataTable`. This caused:
- The cursor to visibly jump backward by 40 rows or 8 columns on screen.
- Textual's internal `scroll_y` and `scroll_x` to reset to 0 upon table rebuild, jarring the user viewport and sending the pointer back into previous window territory.

### The Solution
- **Global Genomic Index Tracking**: Maintain a single authoritative global variant index (`global_variant_idx`) and global sample index (`global_sample_idx`).
- **Smooth Viewport Offset Preservation**: Before a buffer window shift, capture the visible screen viewport line of the cursor. After shifting the underlying data window, restore the cursor to the exact matching record and restore the vertical scroll position so the record stays at the exact same screen row.
- **Auto-Centered Horizontal Sample Scrolling**: Auto-center the active sample column in the visible viewport when crossing column boundaries, providing continuous fluid navigation across high sample counts.

---

## 2. User Experience & Visual Design

### Vertical Variant Navigation Flow
```
User presses Down Arrow / Mouse Wheel Down
               │
               ▼
   Approaching Buffer Boundary (Row > 120)
               │
               ▼
   Capture Viewport Anchor: screen_y_offset
               │
               ▼
   Slide Buffer Window Forward (e.g. +40 rows)
               │
               ▼
   Re-populate DataTable Rows (Preserving exact CHROM / POS)
               │
               ▼
   Restore Cursor to Same Global Genomic Record
   Restore Viewport Scroll Offset (Zero Jump, Zero Snapback)
```

### Horizontal Sample Column Navigation Flow
```
User presses Left / Right Arrow in Sample Matrix
               │
               ▼
   Global Sample Index Updates: global_col_idx += 1
               │
               ▼
   Check Viewport Geometry & Sample Window
               │
               ▼
   Center Active Column in Viewport:
   scroll_to(x = col_center_x - viewport_width / 2)
               │
               ▼
   If outside current sample window, slide window centered on active sample
```

### Visual Stability
- **Zero Cursor Jump**: When moving the cursor down past row 150, the pointer moves seamlessly down to row 151, 152, etc., without jumping back to row 100 or resetting the view.
- **Unmodified Chromosome Names**: Chromosome contigs (`Pf3D7_07_v3`, `chr1`, etc.) remain completely unmodified and rendered with high-contrast cyan headers.
- **Zebra Striping & Cell Highlights**: Row selection and genotype cell highlights stay synchronized in lockstep between the fixed table and the sample matrix.

---

## 3. Key Product Decisions & Trade-Offs

### Decision 1: Record-Pinned Virtualization vs. Rebuilding from Zero
- **Chosen Approach**: Track the absolute global record index (`global_variant_idx`), calculate its local row index in the newly shifted slice (`local_row = global_variant_idx - buffer_start`), and restore the viewport scroll offset (`scroll_to(y = target_scroll_y)`).
- **Why**: Eliminates pointer jump while retaining lazy-loaded memory efficiency (< 10MB memory usage regardless of VCF file size).
- **Alternative Considered**: Rebuilding the table and leaving cursor at relative index 0 or relative offset resulted in the snapback bug reported by the user.

### Decision 2: Auto-Centering Sample Matrix Viewport
- **Chosen Approach**: Calculate the horizontal column center coordinate in content pixels and scroll the viewport to center that column.
- **Why**: Keeps the focused genotype cell prominent in the center of the screen, providing maximum surrounding sample context on both left and right sides.
- **Alternative Considered**: Paging by fixed block increments caused the cursor to bounce between the far-left and far-right edges.

---

## 4. Technical Architecture & Data Strategy

### Component Architecture & Event Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                              VcfscapeApp                               │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                           HeaderBar                              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────┬────────────────────────────────┐  │
│  │        VariantSplitView         │          SidebarPanel          │  │
│  │ ┌─────────────┬───┬───────────┐ │ ┌────────────────────────────┐ │  │
│  │ │ FixedTable  │ │ │SampleTable│ │ │ CohortListWidget           │ │  │
│  │ │ (Info Cols) │ │ │ (Matrix)  │ │ ├────────────────────────────┤ │  │
│  │ │             │ │ │           │ │ │ VariantSummary (Exact Contig)│ │  │
│  │ │             │ │ │           │ │ ├────────────────────────────┤ │  │
│  │ │             │ │ │           │ │ │ CellInspector              │ │  │
│  │ └─────────────┴───┴───────────┘ │ └────────────────────────────┘ │  │
│  └─────────────────────────────────┴────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                         CohortStatsPane                          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                            FooterBar                             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

### State Variables & Windowing Math

```python
# Vertical Virtual Window
self.global_row_idx: int         # Absolute index in VCF file (e.g. 154)
self.buffer_start: int           # Start of current slice (e.g. 40)
self.window_size: int = 150      # Sliced rows in memory (150)
local_row = self.global_row_idx - self.buffer_start  # Relative table row (e.g. 114)

# Horizontal Sample Window
self.global_sample_idx: int      # Absolute sample index (e.g. 42 out of 500)
self.sample_window_start: int    # Start of sample column slice
self.sample_window_size: int     # Rendered sample columns
local_col = self.global_sample_idx - self.sample_window_start
```

### Detailed Execution Steps
1. **Refactor `VariantSplitView` Pointer State**:
   - Store `self.global_row_idx` as the ground truth for vertical navigation.
   - Store `self.global_sample_idx` as the ground truth for horizontal sample navigation.
2. **Implement Viewport-Preserving Buffer Shift**:
   - In `shift_buffer()`, compute `target_local_row = target_global_row - new_start`.
   - Calculate target viewport scroll position so the row does not jump vertically on screen.
   - Suppress highlight events during rebuild with `_rebuilding = True` to prevent feedback loops.
3. **Implement Auto-Centering Sample Column Navigation**:
   - In `SampleMatrixTable.scroll_column_centered(col_idx)`, compute column midpoint and scroll to center.
   - When cursor approaches sample window boundary, shift `sample_window_start` so the active column is centered in the sample window.
4. **Verification & Testing**:
   - Run unit tests in `tests/test_variant_buffer_scrolling.py` and `tests/test_tui_app.py`.
   - Run `compile_applet` and `lint_applet` to confirm overall codebase health.
