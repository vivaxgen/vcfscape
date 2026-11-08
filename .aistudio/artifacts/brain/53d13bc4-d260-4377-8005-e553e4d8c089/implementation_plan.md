# VCF File Reading Loading Indicator (Modal Popup)

Add an intuitive visual cue—a centered modal popup dialog with an animated spinner and live variant count progress—when reading, indexing, and parsing VCF files, giving users clear visual feedback that the application is actively processing their data.

## User Review & Critical Decisions

> [!IMPORTANT]
> The following design choices were confirmed via interactive user clarification and govern this implementation:

- **Confirmed Decision 1 (Loading Cue Type)**: Centered modal popup dialog with an animated spinner.
- **Confirmed Decision 2 (Displayed Information)**: Filename with animated spinner, status description ("Reading VCF file... Scanning index & counting records"), and live variant count progress.
- **Auto-Dismiss & Early Dismiss**: The popup automatically closes as soon as the VCF file indexing and counting are complete. Users can also press `Escape` or click "Dismiss" to begin exploring the initial 150-variant slice immediately while background counting finishes in the header bar.

---

## 1. Overview & Architecture

### User Experience Walkthrough
1. When the user launches VCFscape with a VCF file (`vcfscape sample.vcf.gz`), the application opens.
2. A centered, styled modal dialog (`VcfLoadingScreen`) appears over the dimmed main UI:
   - **Header**: "Reading VCF File" with a cyan/blue glow border matching the malaria surveillance aesthetic.
   - **Target File**: Displays the exact file name (e.g. `malaria_pf3d7_cohort.vcf.gz`).
   - **Animated Indicator**: A live spinner giving active visual motion.
   - **Live Progress Metric**: Displays dynamic progress text:
     - "Parsing header & sample metadata..."
     - "Variants indexed: 14,200..."
   - **Notice**: "Please wait while records are indexed..."
   - **Action**: An optional "Continue in Background (Esc)" button allowing power users to immediately inspect the first slice.
3. Once the background reader finishes scanning or reaches readiness, `VcfLoadingScreen` smoothly dismisses automatically, transitioning focus to the variant table.

---

## 2. Technical Architecture & Component Flow

```
┌────────────────────────────────────────────────────────┐
│                   VcfscapeApp.on_mount                 │
│                                                        │
│  1. Mount main UI (Header, Split Table, Sidebar)       │
│  2. If file reading / counting is in progress:         │
│     app.push_screen(VcfLoadingScreen(...))             │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                   VcfLoadingScreen                     │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │               Reading VCF File                   │  │
│  │  File: malaria_pf3d7.vcf.gz                      │  │
│  │                                                  │  │
│  │  [ ⠋ LoadingIndicator / Animated Spinner ]       │  │
│  │                                                  │  │
│  │  Status: Scanning index and parsing records...   │  │
│  │  Variants Scanned: 45,200                        │  │
│  │                                                  │  │
│  │  [ Continue in Background (Esc) ]                │  │
│  └──────────────────────────────────────────────────┘  │
└───────────────────────────┬────────────────────────────┘
                            │
             Auto-dismiss on readiness callback
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│             Table Ready (Focus Variant Table)          │
└────────────────────────────────────────────────────────┘
```

---

## 3. Implementation Steps

### Step 1: Add Progress Callbacks to `VcfReader` (`src/vcfscape/core/vcf_reader.py`)
- In `VcfReader`, add `add_progress_callback(self, cb: Callable[[int], None])`.
- In `_count_worker`, emit progress updates every 1,000 scanned lines (or at intervals) to registered progress callbacks.
- When counting completes, notify callbacks with the final total.

### Step 2: Implement `VcfLoadingScreen` (`src/vcfscape/ui/screens/vcf_loading_screen.py`)
- Create a `ModalScreen` subclass:
  - Center-aligned on screen with a semi-transparent dark backdrop (`rgba(11, 15, 23, 0.85)`).
  - Modal container with a bold cyan border, dark navy background (`#161e2e`), and clear typography.
  - Contains `LoadingIndicator` (or animated spinner), filename label, dynamic progress counter label (`#progress_label`), and a status hint.
  - Binds `escape` and `enter` to dismiss the modal early if desired.
  - Public method `update_progress(count: int)` and `mark_complete(total: int)` to update the live count and close automatically.

### Step 3: Wire into `VcfscapeApp` (`src/vcfscape/ui/app.py`)
- In `VcfscapeApp.on_mount()`:
  - If `not self.reader.total_variants_ready`:
    - Create `VcfLoadingScreen(filename=os.path.basename(self.vcf_path))`.
    - Push screen via `self.push_screen(...)`.
    - Hook reader progress and completion callbacks via `self.call_from_thread` to update and dismiss the modal when ready.

### Step 4: Tests & Verification
- Add unit tests in `tests/test_vcf_loading_screen.py` verifying:
  - `VcfLoadingScreen` initialization, layout, and styling.
  - Progress updates via `update_progress(count)`.
  - Auto-dismissal when completion callback triggers.
  - Dismissal via `escape` key.
- Run full test suite (`python3 -m unittest discover tests`).
- Run `compile_applet` and `lint_applet` to confirm zero build/lint regressions.
