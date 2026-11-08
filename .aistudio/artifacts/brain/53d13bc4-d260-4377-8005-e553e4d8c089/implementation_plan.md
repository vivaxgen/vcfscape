# Textual Variant Table Scrolling Overhaul

A complete overhaul and simplification of the Textual TUI variant table scrolling architecture in VCFscape. This plan eliminates the root causes of flickering, scroll lockup, and cursor resets by moving from destructive `clear(columns=True)` rebuilds to in-place virtual row updates and native horizontal scrolling across all cohort samples.

## User Review & Critical Decisions

> [!IMPORTANT]
> The following architectural decisions were confirmed via interactive user clarification and govern this overhaul:

- **Confirmed Decision 1 (Vertical Buffer Navigation)**: Overhaul the vertical variant buffer using **in-place row cell updates** within a stable virtual row pool, completely eliminating table clearing (`clear()`) during buffer window shifts.
- **Confirmed Decision 2 (Horizontal Sample Navigation)**: Load **all sample columns upfront** with Textual's native horizontal scrolling, eliminating dynamic column window rebuilds, column pagination, and horizontal snapback.
- **Visual Layout Guarantee**: The existing split-screen visual layout (left fixed columns, divider, right scrollable sample matrix, cohort statistics pane, and sidebar) remains 100% intact.

---

## 1. Overview & Root Cause Analysis

### The Problem in Current Architecture
1. **Destructive Table Rebuilds (`clear()`)**:
   - Currently, whenever the user scrolls past buffer margins (rows 15 or 135) or across sample boundaries, the table executes `self.fixed_table.clear(columns=True)` and `self.sample_table.clear(columns=True)`.
   - In Textual, calling `clear()` drops all DOM nodes, resets `scroll_x` and `scroll_y` to `0`, and resets the cursor coordinate to `(0, 0)`.
   - This causes severe visible screen flashing/flicker and repeatedly throws the cursor back to the top/initial cell.
2. **Bidirectional Scroll Event Ping-Pong**:
   - Two separate tables (`FixedVariantTable` and `SampleMatrixTable`) have cross-referencing `watch_scroll_y` hooks and highlight event listeners (`on_data_table_row_highlighted` / `on_data_table_cell_highlighted`).
   - Scrolling one table triggers an event on the other, which triggers back, causing lockup and stutter.
3. **Column Pagination Snapback**:
   - The sample table was dynamically slicing samples into a 24-sample window. Sliding this window cleared all columns and reset `scroll_x` to 0.

### The Overhaul Solution
- **Fixed Virtual Row Pool (Zero `clear()` during scroll)**:
  - Both tables initialize a fixed number of rows (e.g. 150 rows) once on mount.
  - When the user scrolls past the visible window, the table updates cell text in place using `update_cell(...)` without destroying a single DOM node.
- **Native Horizontal Column Layout**:
  - Sample columns for the active cohort are added once during initialization.
  - Horizontal navigation uses Textual's native column scrolling, auto-centering only when the cursor crosses viewport boundaries.
- **Simplified Single-Authority Scroll Synchronization**:
  - Establish a single master-slave relationship for vertical scrolling and cursor focus so events flow in one direction without circular triggers.

---

## 2. Technical Architecture & Component Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                          VariantSplitView                              │
│                                                                        │
│   State Authority:                                                     │
│   - buffer_start (global variant offset)                               │
│   - current_row_idx (local virtual row 0..149)                         │
│   - active_sample_idx (global sample column 0..N)                      │
│                                                                        │
│   ┌───────────────────────────┐      ┌─────────────────────────────┐   │
│   │     FixedVariantTable     │  │   │      SampleMatrixTable      │   │
│   │  (Fixed 56ch Left Table)  │  │   │   (Native Horizontal View)  │   │
│   │                           │  │   │                             │   │
│   │  - 150 Virtual Rows       │  │   │  - 150 Virtual Rows         │   │
│   │  - CHROM, POS, REF, ALT.. │  │   │  - ALL Cohort Samples       │   │
│   │  - Stable row keys        │  │   │  - Stable row/col keys      │   │
│   └─────────────┬─────────────┘      └──────────────┬──────────────┘   │
│                 │                                   │                  │
│                 └───────────────┬───────────────────┘                  │
│                                 ▼                                      │
│                  In-Place Cell Value Updates                           │
│             table.update_cell(row_k, col_k, new_value)                 │
│              (Zero clear(), Zero DOM node recreation)                  │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  ▼
                 VcfReader (Indexed Lazy Slice Queries)
```

---

## 3. Detailed Implementation Steps

### Step 1: Simplify and Decouple Child Tables (`FixedVariantTable` & `SampleMatrixTable`)
- Strip out circular watchers (`watch_scroll_y`) and aggressive mouse scroll event overrides.
- In `SampleMatrixTable`, add all sample columns upfront during initial setup.
- Retain edge-triggered viewport auto-centering: only adjust `scroll_x` when the active column moves outside `[scroll_x, scroll_x + viewport_width]`.

### Step 2: Implement In-Place Virtual Row Buffer in `VariantSplitView`
- Maintain a stable pool of 150 row keys (`row_0` to `row_149`).
- When `buffer_start` shifts:
  1. Fetch the new slice of `VariantRecord`s from `reader.get_slice(new_start, 150)`.
  2. For each row `0..149`, update cell contents directly via `table.update_cell(row_key, col_key, new_text)`.
  3. If fewer than 150 records remain at EOF, clear or blank the trailing virtual rows.
  4. Adjust cursor position smoothly: `new_local_row = target_global - new_start`.
  5. The table's scroll offset and cursor remain stable—no node unmounting, no layout recomputation, no flicker.

### Step 3: Streamlined Boundary Navigation (`advance_row` & `advance_sample`)
- When reaching the buffer boundary (e.g., advancing past local row 140 or row 10):
  - Slide `buffer_start` forward or backward by a step (e.g. 40 rows).
  - Update rows in-place.
  - Re-point local cursor to `target_global - buffer_start`.
  - Maintain the visual line position (`scroll_y`) relative to the viewport.
- For horizontal sample navigation:
  - Cursor navigates across native columns.
  - If cursor moves beyond visible viewport width, auto-center the active sample column in the viewport.

### Step 4: Verification & Test Suite
- Update existing scrolling unit tests in `tests/test_variant_buffer_scrolling.py`:
  - Verify in-place update execution without table clearing.
  - Test scrolling down through multiple 150-variant buffer windows (rows 0 -> 400).
  - Test scrolling backward up across buffer windows (rows 400 -> 0).
  - Test horizontal sample navigation across all columns without column truncation.
  - Confirm chromosome contig names are never normalized or truncated.
- Run full test suite (`python3 -m unittest discover tests`).
- Run `compile_applet` and `lint_applet` to ensure zero compilation or type regressions.
