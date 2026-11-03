# VCFscape - VCF inspector part of vivaxGEN Project

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Textual](https://img.shields.io/badge/Textual-TUI-purple.svg)](https://textual.textualize.io/)
[![cyvcf2](https://img.shields.io/badge/cyvcf2-Genomics-green.svg)](https://github.com/brentp/cyvcf2)
[![Pixi](https://img.shields.io/badge/Pixi-Compatible-orange.svg)](https://pixi.sh/)

A high-performance Textual-based Python terminal user interface (TUI) and genomic analysis workbench designed specifically for inspecting complex, multi-allelic, and indel-dense VCF files from *Plasmodium falciparum*, *Plasmodium vivax*, and other eukaryotic pathogen sequencing as part of the **vivaxGEN Project**.

Built for malaria molecular surveillance, outbreak investigation, and population genetics.

---

## Key Features

- **Space-Preserving, Minimal-Border TUI**: Eliminates heavy decorative box borders to maximize screen columns and rows for genomic data—letting you view dozens of sample columns and variant rows simultaneously.
- **Fast VCF Parsing with `cyvcf2`**: Optimized C/htslib engine with seamless fallback to a pure-Python streaming reader when compiled binaries are unavailable.
- **Multi-Allelic & Complex Indel Decomposition**: Real-time per-allele frequencies (`AF0`, `AF1`, `AF2...`), indel length delta spectrum (`+1bp`, `-3bp`), and microsatellite polygenomic analysis.
- **WHO Antimalarial Drug Resistance Surveillance**: Automatic coordinate lookup against WHO validated markers (*Pfkelch13* artemisinin, *Pfcrt* chloroquine, *Pfmdr1* lumefantrine/mefloquine, *Pfdhps* sulfadoxine, *Pfdhfr* pyrimethamine, *Plasmepsin 2/3* piperaquine).
- **Resizable Cohort Statistics Split-Pane**: Dynamic panel between the main table and footer comparing population genetics metrics (allele frequencies, mean read depth, missingness rate, polyclonal infection rates) across user-defined sample cohorts (e.g. Clinical vs. Asymptomatic, regional isolates).
- **4 Variant View Modes**: Instant toggling between **Raw View** (all 9 VCF columns), **Normal View** (surveillance fields), **Compact View** (coordinates & alleles), and **Essential View** (chrom & pos).
- **Dynamic Sample Column Widths**: Fitted compactly to the active FORMAT tag (`GT`, `DP`, `AD`, `GQ`).
- **Comprehensive Cell Inspector**: Deconstructs genotype, depth, and allelic depths for any sample on cursor focus.

---

## Installation

### Method 1: Direct from GitHub with Pixi
You can add this package directly to your Pixi environment using:
```bash
pixi add --pypi "git+https://github.com/<user>/vcfscape.git"
```
Or inside a local clone:
```bash
pixi add --pypi .
```

### Method 2: With uv
```bash
# Run TUI directly without explicit install:
uv run --with "git+https://github.com/<user>/vcfscape.git" vcfscape --demo

# Run Web Simulator directly without explicit install:
uv run --with "git+https://github.com/<user>/vcfscape.git" vcfscape-web

# Or install into active uv environment:
uv pip install -e .
```

### Method 3: Standard pip
```bash
git clone https://github.com/<user>/vcfscape.git
cd vcfscape
pip install -e .
```

---

## Quick Start (Terminal TUI)

### 1. Launch TUI with Bundled Demo Dataset
```bash
vcfscape --demo
# or via helper script:
./run_tui.sh
```

### 2. Inspect Your Own VCF File
```bash
vcfscape path/to/malaria_isolates.vcf.gz
```

### 3. Specify Cohort Metadata
```bash
vcfscape path/to/malaria_isolates.vcf.gz --cohorts sample_metadata.tsv
```

---

## Running the Web Version on Local System

The project includes an interactive, browser-based surveillance simulator that exactly mirrors the TUI layout, hotkeys, and data tables. You can execute it locally using any of the following mechanisms:

### Option A: Zero-Node.js Python Launcher (Recommended)
The package bundles pre-compiled static web assets and an automated zero-dependency HTTP server using Python's standard library. **No Node.js or npm required**:

```bash
# Via dedicated web command:
vcfscape-web

# Or via the main CLI --web flag:
vcfscape --web

# Or via the root helper script:
./run_web.sh

# Custom port, headless/remote execution, or token authentication:
vcfscape-web --port 8080 --host 0.0.0.0 --no-browser
```
This prints the local URL (e.g. `http://localhost:3000/?token=...`) along with your local network IP and FQDN URLs.

### Option B: Pixi Tasks
If you use [Pixi](https://pixi.sh/), the included `pixi.toml` provides pre-configured tasks:
```bash
# Launch the bundled web simulator:
pixi run web

# Or start the live Vite development server:
pixi run dev-web

# Launch the terminal TUI:
pixi run tui
```

### Option C: Instant Execution with uv (No Install Needed)
Run directly from GitHub into a temporary ephemeral environment:
```bash
uv run --with "git+https://github.com/<user>/vcfscape.git" vcfscape-web
```

### Option D: Node.js & Vite (Full-Stack / Frontend Development)
If you want to modify the React/TypeScript frontend or develop components with live reloading:
```bash
# 1. Install Node dependencies
npm install

# 2. Start Vite development server (port 3000)
npm run dev

# 3. Build production bundle to dist/ and sync to package
npm run build

# 4. Preview production build
npm run preview
```

---

## Keyboard Shortcuts & Controls

| Hotkey | Action | Description |
|:---:|:---|:---|
| `1` | **Genotype (GT)** | Switch sample matrix to `0/0`, `0/1`, `1/1`, `1/2` (color-coded by polyclonal status) |
| `2` | **Read Depth (DP)** | Display raw sequencing depth per sample cell |
| `3` | **Allelic Depth (AD)** | Display comma-separated depths for REF and ALT alleles |
| `4` | **Genotype Quality (GQ)** | Display Phred-scaled confidence score |
| `v` | **Cycle View Mode** | Cycle between **Normal** &rarr; **Compact** &rarr; **Essential** &rarr; **Raw** |
| `s` | **Toggle Split-Pane** | Expand / Collapse the Cohort Statistics split-pane |
| `c` | **Toggle Cohorts** | Toggle active status of sample cohorts in real time |
| `f` | **Cycle Variant Filter** | Filter by `ALL`, `DRUG_RESISTANT`, `INDEL`, or `SNP` |
| `t` | **Toggle Theme** | Toggle between **Dark** and **Light** high-contrast themes (Web & TUI) |
| `?` | **Help** | Display keyboard shortcut legend in the log console |
| `q` | **Quit** | Exit the TUI application |
| `↑` `↓` `←` `→` | **Navigate** | Move cell cursor across variants and sample columns |

---

## Screen Layout Architecture

```
[Header] pf_malaria_surveillance.vcf.gz | Pf3D7_v3 | 1,420 Vars | 24 Samples | View: [Normal] | Tag: [GT]
───────────────────────────────────────────────────────────────────────────────────────────────────────
CHROM    POS     REF ALT   KL_01 KL_02 KL_03 AS_01 AS_02 AS_03 │ VARIANT SUMMARY
Pf13_v3  1725259 C   T,A   1/1   1/1   0/1   0/0   0/1   0/0   │ Locus: Pf3D7_13_v3:1,725,259
Pf07_v3  403625  C   T     1/1   1/1   1/1   0/0   0/1   0/0   │ Gene:  Pfkelch13 (C580Y Missense)
Pf05_v3  958145  A   T     1/1   0/1   1/1   0/0   0/1   0/0   │ Drug:  ARTEMISININ RESISTANCE
Pf12_v3  974200  TA  T,TAA 1/1   1/2   0/1   0/0   1/1   0/0   │ ──────────────────────────────────
Pf14_v3  1402310 A   A,ATT 1/1   1/1   1/2   0/0   0/1   0/0   │ COHORTS & FILTERS
                                                               │ [x] Cohort KL (Clinical: 8)
                                                               │ [x] Cohort AS (Asymptomatic: 8)
                                                               │ ──────────────────────────────────
                                                               │ CELL INSPECTOR [KL_01]
                                                               │ GT: 1/1 (Homozygous Alt)
                                                               │ DP: 78 reads  AD: 2,76,0  GQ: 99
───────────────────────────────────────────────────────────────────────────────────────────────────────
COHORT STATISTICS (SPLIT-PANE) [Toggle: s]
METRIC / ALLELE    ALL SAMPLES (N=24)        COHORT KL (N=8)           COHORT AS (N=8)
Called / Missing   24/24 (0.0% miss)         8/8 (0.0% miss)           8/8 (0.0% miss)
Mean Read Depth    62.4x [36 - 95x]          75.5x [55 - 95x]          42.1x [36 - 52x]
Polyclonal / Het   7 isolates (29.2%)        2 isolates (25.0%)        2 isolates (25.0%)
REF [0: C]         AF=0.354 (n=17)           AF=0.125 (n=2)            AF=0.688 (n=11)
ALT [1: T]         AF=0.583 (n=28)           AF=0.812 (n=13)           AF=0.312 (n=5)
ALT [2: A]         AF=0.062 (n=3)            AF=0.062 (n=1)            AF=0.000 (n=0)
───────────────────────────────────────────────────────────────────────────────────────────────────────
[1] GT [2] DP [3] AD [4] GQ | [v] View Mode | [s] Toggle Split | [c] Cohorts | [f] Filter | [q] Quit
LOG: Locus: Pf3D7_13_v3:1,725,259 (Pfkelch13) [Artemisinin Resistance] | Sample: KL_001
```

---

## Running Tests

Run the built-in test suite:
```bash
python3 -m unittest discover tests
```
Or with pytest:
```bash
pytest tests/
```
