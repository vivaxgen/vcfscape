# Implementation Plan: Sample Cohort Management (Create, Edit, Clone, Invert, Delete)

## 1. Overview & User Requirements
The objective is to provide a comprehensive cohort management interface across **both** the Python Textual TUI and the Web React application. Users will be able to:
1. **Create new cohorts** with custom name, description, and color.
2. **Edit existing cohorts** (modifying sample memberships, names, and color tags).
3. **Filter and select samples** using an interactive modal checklist with real-time text search and filter toggles.
4. **Use bulk selection helpers**: "Select All", "Deselect All", and **"Invert Selection"** (flips current checkbox states).
5. **Clone cohorts**: Duplicate an existing cohort's sample list into a new cohort for fast variation and branching.
6. **Delete cohorts**: Remove cohorts with confirmation and safely update active calculations.

---

## 2. Architecture & Gap Analysis

### Python Core (`src/malaria_vcf_tui/core/cohort.py`)
- **Current State**:
  - `Cohort` dataclass defines `name`, `sample_ids: Set[str]`, `description`, `color`, and `active`.
  - `CohortManager` provides basic operations (`add_cohort`, `remove_cohort`, `toggle_cohort`, `rename_cohort`, `get_sample_indices`).
- **Gaps to Address**:
  - Add `clone_cohort(cohort_id: str, new_name: str | None = None, new_color: str | None = None) -> Cohort`
  - Add `update_cohort(cohort_id: str, name: str | None = None, sample_ids: Set[str] | None = None, description: str | None = None, color: str | None = None) -> Cohort`
  - Add `invert_sample_selection(all_samples: Sequence[str], current_selection: Set[str]) -> Set[str]` helper
  - Add validation preventing deletion of default or last remaining cohort if configured, and ensure index caches invalidate properly.

### Python Textual TUI (`src/malaria_vcf_tui/ui/`)
- **Current State**:
  - `CohortWidget` displays active cohort badges and sample counts, but only supports clicking to toggle active status.
  - No modal screen exists for managing or creating cohorts.
- **New Components to Add**:
  - `src/malaria_vcf_tui/ui/screens/cohort_manager_screen.py`: A `ModalScreen` implementing:
    - **Header**: Cohort dropdown/selector (`[+ New Cohort]` option + list of existing cohorts).
    - **Details Form**: Input for Cohort Name, Color preset picker/selector, Description input.
    - **Toolbar Actions**: `[Clone]`, `[Delete]` (with safety prompt), `[Save]`, `[Cancel]`.
    - **Sample Filter Controls**: Text `Input` for instantaneous sample ID filtering, plus `[Select All]`, `[Deselect All]`, and `[Invert Selection]`.
    - **Sample Checklist**: Textual `SelectionList[str]` widget rendering each sample with a checkbox, displaying total vs. selected count badge (e.g. `34 / 80 selected`).
  - **Integration**:
    - Add a `[+ Cohorts]` button to `CohortWidget` header and bind hotkey `c` / `Shift+C` in `MalariaVcfApp`.
    - Emit `CohortsUpdated` message when dismissed to refresh `CohortWidget`, `CohortStatsPane`, and `VariantTable`.

### Web Interface (`src/components/`, `src/App.tsx`)
- **Current State**:
  - `CohortModal.tsx` provides high-level cohort viewing or metric summary, but lacks a full interactive sample checklist and cloning/deletion controls.
- **Enhancements to Add**:
  - In `src/components/CohortModal.tsx`:
    - Tabbed/split view: List of cohorts on the left, editor on the right with a prominent `+ New Cohort` button.
    - Editable fields: Cohort name, color selector (preset palette), and description.
    - Search input to filter samples by ID or country/metadata prefix.
    - Quick actions: **Select All**, **Deselect All**, **Invert Selection**, and filter toggle ("All" vs "Selected Only").
    - Scrollable sample list with checkboxes and instant selection summary.
    - **Clone** action: duplicates the active cohort's samples with `(Copy)` suffix.
    - **Delete** action: deletes cohort with confirmation prompt.
  - In `src/App.tsx`:
    - Update state handlers to update variant allele frequencies and cohort statistics across tables whenever cohorts are added, edited, cloned, or deleted.

---

## 3. Implementation Steps

### Phase 1: Python Core Engine & Unit Tests
1. Enhance `src/malaria_vcf_tui/core/cohort.py`:
   - Implement `clone_cohort(...)`, `update_cohort(...)`, `invert_selection(...)`.
   - Ensure `_sample_indices_cache` is properly invalidated on edits.
2. Add comprehensive tests in `tests/test_cohort_management.py`:
   - Test cohort creation, update, deletion, cloning, and inverted selection.
   - Test edge cases: empty selections, invalid sample IDs, duplicate names.

### Phase 2: Textual TUI Cohort Manager Modal
1. Create `src/malaria_vcf_tui/ui/screens/cohort_manager_screen.py`:
   - Textual `ModalScreen` with responsive layout, keyboard bindings (`Esc` to close, `Enter` to save, `Ctrl+A` select all, `Ctrl+I` invert).
   - Dynamic search filtering of `SelectionList`.
   - Clone and Delete actions.
2. Update `src/malaria_vcf_tui/ui/styles.tcss`:
   - Styling for modal overlay, search toolbar, button groupings, and badge counters.
3. Update `src/malaria_vcf_tui/ui/widgets/cohort_widget.py` & `src/malaria_vcf_tui/app.py`:
   - Add button to open modal, handle hotkey `c`, and handle `CohortsUpdated` message.

### Phase 3: Web Application Cohort Management
1. Enhance `src/components/CohortModal.tsx`:
   - Implement search filter, Select All, Deselect All, Invert Selection, Clone, and Delete buttons.
   - Implement sample checklist grid with responsive scrolling.
2. Update `src/App.tsx` and types:
   - Wire up `onSaveCohort`, `onCloneCohort`, `onDeleteCohort` callbacks.
   - Sync recalculation of fixed and sample tables upon cohort updates.

### Phase 4: Build, Testing & Verification
1. Run Python unit tests: `python3 -m unittest discover tests`.
2. Build frontend assets: `npm run build` and sync to `src/malaria_vcf_tui/web_dist/`.
3. Verify interactive flows:
   - Creating a new cohort with inverted selection.
   - Cloning an existing cohort and modifying samples.
   - Deleting a cohort and verifying table updates.
   - Testing keyboard hotkeys and responsiveness in both interfaces.
