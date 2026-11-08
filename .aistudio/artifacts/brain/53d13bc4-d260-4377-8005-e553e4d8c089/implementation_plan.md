# Plan: Master-Slave Vertical Synchronization & Elimination of Cursor Oscillation

Resolve vertical scrolling flickering, row misalignment, and erratic cursor jumping in the Textual TUI by establishing a single-source-of-truth synchronization architecture that eliminates mutual event loops between the fixed variant table and sample matrix table.

---

## User Review & Critical Architecture Decisions

> [!IMPORTANT]
> **Confirmed User Requirements**:
> 1. **Symptom Identified**: The cursor/pointer continuously moves up/down and jumps erratically to and from the original row and adjacent rows when scrolling vertically.
> 2. **Target Architecture**: Eliminate mutual dual-controller conflicts by establishing a unified single-controller vertical synchronization pattern where one master vertical scroll controller drives both the fixed variant table and the sample matrix table.
> 3. **Testing Constraint**: Do not write any more excessive mock tests; focus on solving the real Textual user interface issues directly.

---

## 1. Root Cause Analysis: Why the Cursor Oscillates and Flickers

### A. The Asynchronous Event Echo Loop (Cursor Ping-Pong)
Currently, both `FixedVariantTable` and `SampleMatrixTable` listen to their own highlight events and instruct the other table:
```
User presses Down
     │
     ▼
FixedVariantTable.cursor_row becomes 141
     │
     ▼ (posts RowHighlighted)
VariantSplitView.on_data_table_row_highlighted:
     - Sets _syncing_cursor = True
     - Calls sample_table.move_cursor(row=141)
     - Sets _syncing_cursor = False (resets synchronously before event is processed!)
     │
     ▼ (Textual event queue processes sample_table move_cursor)
SampleMatrixTable fires CellHighlighted:
     - Checks _syncing_cursor (which is now FALSE!)
     - Says: "Hey, cell highlighted at 141, move fixed_table.move_cursor(row=141)!"
     │
     ▼ (Sample table auto-scrolls to keep cursor visible)
Textual's internal scroll_to_cell shifts viewport, causing FixedTable to adjust cursor to 140
     │
     ▼
Infinite mutual ping-pong: Row 140 ↔ Row 141 ↔ Row 140 ... (Erratic continuous cursor jumping)
```

### B. The Dual `watch_scroll_y` Desynchronization
Both tables run `watch_scroll_y` and call `peer.scroll_to(y=new_value)`.
- If `abs(peer.scroll_y - new_value) >= 1.0` is used, fractional scroll values leave the tables misaligned by 1 line (e.g., variant info on row 140 lines up with sample genotype row 141).
- When the threshold of `1.0` is crossed, the peer table abruptly snaps by 1 row, producing a visible jump and screen flicker.
- Dual vertical scrollbars (one on fixed table and one on sample table) fight for render updates.

### C. Non-Batched DOM Row Addition
In `fetch_more_rows`, calling `self.fixed_table.add_row()` and `self.sample_table.add_row()` 100 times individually triggers up to 200 separate layout recalculations and repaints on the main thread while the user is actively scrolling, creating visual tearing.

---

## 2. Target Architecture: Master-Slave Unified Scroll & Lockstep Cursor

```
┌────────────────────────────────────────────────────────────────────────┐
│                        VariantSplitView                                │
│       (Sole Authoritative Controller of active_row & scroll_y)         │
├────────────────────────────────────────────────────────────────────────┤
│  Keyboard Events: Arrow Up / Down, Page Up / Down, Home / End          │
│  Mouse Events:    MouseScrollDown, MouseScrollUp                       │
│  State:           current_row_idx, scroll_y, suppress_events_flag      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
           ┌────────────────────────┴────────────────────────┐
           ▼                                                 ▼
┌──────────────────────────────┐        ┌───────────────────────────────┐
│     FixedVariantTable        │        │      SampleMatrixTable        │
│          (Slave)             │        │    (Master Horizontal/Scroll) │
├──────────────────────────────┤        ├───────────────────────────────┤
│ • overflow-y: hidden         │   │    │ • Shows vertical scrollbar    │
│ • No vertical scrollbar      │   │    │ • Shows horizontal scrollbar  │
│ • Does NOT watch scroll_y    │   │    │ • Drives master vertical      │
│ • Does NOT command peer      │   │    │   scroll for both tables      │
│ • Strictly receives row/y    │        │ • Handles sample cell cursor  │
└──────────────────────────────┘        └───────────────────────────────┘
```

### Core Design Rules
1. **Unidirectional Event Flow**: Child tables NEVER communicate directly with each other via `peer_table`.
2. **Hidden Fixed Table Scrollbar**: `FixedVariantTable` has `overflow-y: hidden` and `scrollbar-size-vertical: 0`. Only `SampleMatrixTable` renders the authoritative vertical scrollbar for the split view.
3. **Event Loop Suppression Token**: When `VariantSplitView` programmatically moves a cursor on either table, a suppression flag `_is_internal_update = True` blocks any recursive highlight handling until the operation completes.
4. **Atomic Batch Row Insertion**: Wrap `add_row` loops inside `self.app.batch_update()` so Textual aggregates all 100 appended rows into a single render pass without intermediate frame flashes.
5. **Exact Integer Scroll Alignment**: Both tables are locked to exact integer scroll coordinates (`scroll_to(y=int(y), animate=False, force=True)`), eliminating the 1-row drift.

---

## 3. Implementation Steps

### Step 1: Clean Up Child Table Classes (`src/vcfscape/ui/widgets/variant_table.py`)
- In `FixedVariantTable`:
  - Remove `peer_table` reference and mutual `watch_scroll_y` ping-pong.
  - Disable vertical scrollbar via CSS: `overflow-y: hidden;` and `scrollbar-size-vertical: 0;`.
  - Simplify `action_cursor_down` and `action_cursor_up` to delegate directly to `VariantSplitView.navigate_rows(delta)`.
- In `SampleMatrixTable`:
  - Remove `peer_table` reference.
  - When its vertical scroll updates (`watch_scroll_y`), notify `VariantSplitView.on_master_scroll_y(new_value)` which directly sets `FixedVariantTable.scroll_to(y=new_value, animate=False, force=True)`.

### Step 2: Centralize Row Navigation in `VariantSplitView`
- Implement `navigate_rows(delta: int)`:
  - Calculate `target_row = max(0, min(self.total_records_count - 1 if self.total_records_count else len(self.records) + 50, self.current_row_idx + delta))`.
  - If `target_row >= len(self.records) - 25`, call `fetch_more_rows(100)`.
  - Set `self._is_internal_update = True`.
  - Move `fixed_table.move_cursor(row=target_row, animate=False)`.
  - Move `sample_table.move_cursor(row=target_row, column=local_col, animate=False)`.
  - Synchronize vertical scroll positions directly:
    `self.fixed_table.scroll_to(y=self.sample_table.scroll_y, animate=False, force=True)`.
  - Finally reset `self._is_internal_update = False`.
  - Update `self.current_row_idx = target_row` and post `VariantSelected` ONCE.

### Step 3: Implement Atomic Batch Row Appending
- In `fetch_more_rows`:
  - Wrap the 100-row `add_row` loop in `with self.app.batch_update():` (or pause refresh during the append loop).
  - Append all 100 rows to `fixed_table` and `sample_table` simultaneously.
  - Keep scroll positions locked before and after batch append.

### Step 4: Verification
- Verify that pressing Down arrow repeatedly through rows 140–200 moves smoothly one row at a time with ZERO cursor oscillation or bouncing.
- Verify that mouse wheel down continuously scrolls past row 150 without screen stutter.
- Verify that Page Down advances cleanly without desynchronizing left variant columns from right sample matrix columns.
- Ensure all existing tests pass and run `compile_applet` and `lint_applet` with 0 errors.
