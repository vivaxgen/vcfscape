# Plan: Continuous Dynamic Row Appending & Fluid Vertical Scrolling

Eliminate the 150-row buffer boundary wall in the Textual TUI by transitioning from a rigid sliding-window to a continuous dynamic appending model that supports arrow keys, mouse wheel, and page up/down without cursor snapback or flickering.

---

## 1. Root Cause Analysis

### The Flaw with the Rigid 150-Row Sliding Window
1. **The 150-Row Wall for Mouse & PageDown**:
   - In Textual, a `DataTable` computes `max_scroll_y = row_count - viewport_height`.
   - With `row_count` fixed at 150, scrolling via mouse wheel or dragging the scrollbar physically halts at row 150.
   - When code tried to detect `scroll_y >= max_scroll_y` and shift the 150-row window by resetting `scroll_y = 0`, it caused the scroll position to snap all the way back to the top of the screen.

2. **The Coordinate Snapback for Keyboard Arrow Down**:
   - When cursor reached row 135 or 149 and shifted `buffer_start` forward by 40, code called `move_cursor(row = current_row - 40)`.
   - Textual's internal `move_cursor` automatically invoked `scroll_to_cell`, causing the viewport to visibly jump 40 rows backward. The user felt like they were being pushed back every few keystrokes.

3. **Scrollbar Desynchronization**:
   - The native `DataTable` scrollbar only knew about the 150 rows in the DOM, giving no indication of where the user was within a 50,000-variant file.

---

## 2. Technical Overhaul Strategy

### Continuous Dynamic Append ("Infinite Scroll")
Instead of maintaining a small 150-row window that has to be slid and re-keyed, the `VariantSplitView` will continuously append variant rows dynamically as the user scrolls down:

```
┌────────────────────────────────────────────────────────────┐
│                    Initial Load: 150 Rows                  │
│                    (Rows 0 .. 149 in DOM)                  │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼ User scrolls / arrows near bottom (e.g. Row 120)
┌────────────────────────────────────────────────────────────┐
│        Dynamically Append Batch (+100 Rows: 150 .. 249)    │
│        - Total rows become 250                             │
│        - Cursor continues naturally (no coordinate jumps!) │
│        - Mouse wheel continues scrolling down smoothly     │
│        - Zero cell recreation or scroll snapping           │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼ Continued Scrolling
┌────────────────────────────────────────────────────────────┐
│        Dynamically Append Batch (+100 Rows: 250 .. 349)    │
│        - High water mark buffer (smooth up to 5,000+ rows) │
└────────────────────────────────────────────────────────────┘
```

### Why Continuous Append Fixes Every Issue:
1. **Zero Snapback**: The cursor simply advances from row 148 to 149 to 150 to 151. `move_cursor` is never called with a negative offset.
2. **No Mouse Wheel Wall**: `max_scroll_y` automatically expands as new rows are appended. The mouse wheel continues scrolling downward uninterrupted.
3. **Fluid Page Up / Page Down**: Page Down moves through rows naturally without hitting an artificial wall.
4. **Lightweight DOM**: Because sample columns are virtualized to 50 columns, appending 100 rows adds only `100 × 50 = 5,000` cells. Appending takes `<2ms` and consumes minimal memory.

---

## 3. Implementation Steps

### Step 1: Continuous Append Engine in `VariantSplitView` (`src/vcfscape/ui/widgets/variant_table.py`)
- Replace the rigid `shift_buffer` and `_check_buffer_boundary` logic with `_check_and_fetch_more(current_row_or_scroll_y)`:
  - Trigger threshold: when `cursor_row >= self.row_count - 30` or `scroll_y >= self.max_scroll_y - 15`.
  - Fetch chunk: calls `self.reader.get_slice(self.row_count, batch_size=100)`.
  - Append to tables: calls `fixed_table.add_row(...)` and `sample_table.add_row(...)` for each new record.
  - Updates `self.records.extend(new_records)` and refreshes scroll extents.
  - No `clear()`, no in-place coordinate remapping, no snapbacks.

### Step 2: Input Handlers for Keyboard, Mouse, and Page Down
- **Arrow Down (`action_cursor_down`)**:
  - Simply allow `super().action_cursor_down()` to advance to the next row.
  - If cursor is near the end of loaded rows, proactively append the next batch so the cursor moves seamlessly across the boundary.
- **Mouse Wheel (`on_mouse_scroll_down`)**:
  - Remove the broken `self.scroll_y >= self.max_scroll_y` reset logic.
  - When scroll reaches near bottom, trigger `_check_and_fetch_more()`, allowing mouse wheel to scroll down smoothly without interruption.
- **Page Down (`action_page_down`)**:
  - Check if paging down approaches the buffer end; proactively append rows before delegating to `super().action_page_down()`.

### Step 3: Dataset-Wide Position Indicator
- Update Header and Footer bars to display exact dataset position proportional to the entire file:
  - e.g., `Variant: 1,420 / 52,400 (2.7%) [ Pf3D7_07_v3:412,500 ]`
  - Display a visual position track in the footer: `[████░░░░░░░░░░░░░░░░]` showing relative position within the full VCF.
  - Keep the table's native scrollbar proportional to loaded records while accurately tracking dataset progress.

### Step 4: Verification
- Test interactive vertical scrolling past rows 150, 300, 500, 1000 with:
  - Down arrow holding past row 150 without coordinate jump.
  - Page Down past multiple buffer batches.
  - Mouse scroll down continuously past the initial 150 rows.
  - Jumping to genomic locus (e.g. `Pf3D7_13_v3:1,725,259`) and appending from that locus.
- Run complete test suite and TypeScript linting.
