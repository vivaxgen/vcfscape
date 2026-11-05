/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { VARIANTS_DATA, SAMPLES, INITIAL_COHORTS } from "./data/malariaData";
import { Variant, ViewMode, FormatTag, Cohort, ThemeMode } from "./types/vcf";
import { HeaderBar } from "./components/HeaderBar";
import { VariantTable } from "./components/VariantTable";
import { Sidebar } from "./components/Sidebar";
import { CohortStatsPane } from "./components/CohortStatsPane";
import { FooterBar } from "./components/FooterBar";
import { PixiGuideModal } from "./components/PixiGuideModal";
import { HelpModal } from "./components/HelpModal";
import { CohortModal } from "./components/CohortModal";
import { JumpModal } from "./components/JumpModal";
import { readVcfFile } from "./utils/vcfParser";

export default function App() {
  const [variants, setVariants] = useState<Variant[]>(VARIANTS_DATA);
  const [totalVariantsCount, setTotalVariantsCount] = useState<number>(VARIANTS_DATA.length);
  const [samples, setSamples] = useState<string[]>(SAMPLES);
  const [filename, setFilename] = useState<string>("pf3d7_surveillance_demo.vcf");
  const [cohorts, setCohorts] = useState<Cohort[]>(INITIAL_COHORTS);
  const [activeFilter, setActiveFilter] = useState<string>("ALL");

  const [selectedVariantIndex, setSelectedVariantIndex] = useState<number>(0);
  const [selectedSampleIndex, setSelectedSampleIndex] = useState<number>(0);

  const [viewMode, setViewMode] = useState<ViewMode>("normal");
  const [formatTag, setFormatTag] = useState<FormatTag>("GT");

  const [isCohortModalOpen, setIsCohortModalOpen] = useState<boolean>(false);
  const [isJumpModalOpen, setIsJumpModalOpen] = useState<boolean>(false);

  const [theme, setTheme] = useState<ThemeMode>(() => {
    try {
      const saved = localStorage.getItem("malaria_vcf_theme");
      if (saved === "light" || saved === "dark") return saved;
    } catch {
      // ignore
    }
    return "dark";
  });

  const [isSplitExpanded, setIsSplitExpanded] = useState<boolean>(false);
  const [splitHeight, setSplitHeight] = useState<number>(180);

  const [logMessage, setLogMessage] = useState<string>(
    "Loaded malaria surveillance dataset. Press 1-4 for format tags, v for view, g to jump locus, s for split-pane, t for theme."
  );

  const [isPixiModalOpen, setIsPixiModalOpen] = useState<boolean>(false);
  const [isHelpModalOpen, setIsHelpModalOpen] = useState<boolean>(false);

  // Fetch CLI-provided VCF data from local server if available (streaming chunked API)
  useEffect(() => {
    let cancelled = false;
    const fetchVcfData = async () => {
      try {
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get("token");
        const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : "";

        // 1. Try fast metadata endpoint first
        let metaResp = await fetch(`/api/metadata${tokenQuery}`, { credentials: "same-origin" });
        if (metaResp.ok) {
          const meta = await metaResp.json();
          if (cancelled) return;
          if (meta.hasCustomVcf) {
            setFilename(meta.filename);
            if (Array.isArray(meta.samples)) setSamples(meta.samples);
            if (Array.isArray(meta.cohorts) && meta.cohorts.length > 0) setCohorts(meta.cohorts);
            setTotalVariantsCount(meta.totalVariants || 0);

            // Fetch initial slice of variants (sub-15ms)
            const varQuery = token ? `&token=${encodeURIComponent(token)}` : "";
            const varResp = await fetch(`/api/variants?offset=0&limit=150${varQuery}`, { credentials: "same-origin" });
            if (varResp.ok) {
              const varData = await varResp.json();
              if (cancelled) return;
              if (Array.isArray(varData.variants) && varData.variants.length > 0) {
                setVariants(varData.variants);
                setSelectedVariantIndex(0);
                setSelectedSampleIndex(0);
                setLogMessage(
                  `Ready: ${meta.totalVariants.toLocaleString()} variants across ${meta.totalSamples} isolates from ${meta.filename} (${meta.backend}).`
                );
                return;
              }
            }
          }
        }

        // 2. Fallback to /api/vcf-data or static vcf_data.json
        let resp = await fetch(`/api/vcf-data${tokenQuery}`, { credentials: "same-origin" });
        if (!resp.ok) {
          resp = await fetch(`/vcf_data.json${tokenQuery}`, { credentials: "same-origin" });
        }
        if (resp.ok) {
          const res = await resp.json();
          if (cancelled) return;
          if (res.hasCustomVcf && res.data) {
            const d = res.data;
            if (Array.isArray(d.variants) && d.variants.length > 0) {
              setVariants(d.variants);
            }
            if (Array.isArray(d.samples) && d.samples.length > 0) {
              setSamples(d.samples);
            }
            if (Array.isArray(d.cohorts) && d.cohorts.length > 0) {
              setCohorts(d.cohorts);
            }
            if (d.filename) {
              setFilename(d.filename);
            }
            setTotalVariantsCount(d.totalVariants || d.variants.length);
            setSelectedVariantIndex(0);
            setSelectedSampleIndex(0);
            setLogMessage(
              `Loaded ${d.totalVariants || d.variants.length} variants across ${
                d.totalSamples || d.samples.length
              } isolates from ${d.filename}.`
            );
          }
        }
      } catch {
        // Silently keep default surveillance demo dataset
      }
    };
    fetchVcfData();
    return () => {
      cancelled = true;
    };
  }, []);

  // Handle client-side file opening via Open VCF button
  const handleOpenFile = useCallback(async (file: File) => {
    try {
      setLogMessage(`Reading VCF file ${file.name}...`);
      const res = await readVcfFile(file);
      setVariants(res.variants);
      setSamples(res.samples);
      setCohorts(res.cohorts);
      setFilename(res.filename);
      setSelectedVariantIndex(0);
      setSelectedSampleIndex(0);
      setLogMessage(
        `Successfully loaded ${res.totalVariants} variants and ${res.totalSamples} isolates from ${res.filename}.`
      );
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setLogMessage(`Error loading VCF file: ${errMsg}`);
    }
  }, []);

  // Synchronize theme with html document element
  useEffect(() => {
    try {
      localStorage.setItem("malaria_vcf_theme", theme);
    } catch {
      // ignore
    }
    if (theme === "dark") {
      document.documentElement.classList.add("dark");
      document.documentElement.classList.remove("light");
    } else {
      document.documentElement.classList.remove("dark");
      document.documentElement.classList.add("light");
    }
  }, [theme]);

  // Toggle theme
  const handleToggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: ThemeMode = prev === "dark" ? "light" : "dark";
      setLogMessage(`Switched theme to [${next.toUpperCase()}] mode.`);
      return next;
    });
  }, []);

  // Filtered variants
  const filteredVariants = useMemo(() => {
    if (activeFilter === "ALL") return variants;
    if (activeFilter === "DRUG_RESISTANT") return variants.filter((v) => !!v.drug);
    if (activeFilter === "INDEL") return variants.filter((v) => v.varType.includes("INDEL"));
    if (activeFilter === "SNP") return variants.filter((v) => v.varType.includes("SNP"));
    return variants;
  }, [variants, activeFilter]);

  // Ensure index remains in bounds
  const currentVariant = filteredVariants[selectedVariantIndex] || filteredVariants[0] || null;
  const currentSampleId =
    selectedSampleIndex >= 0 && selectedSampleIndex < samples.length ? samples[selectedSampleIndex] : null;

  // Toggle cohort
  const handleToggleCohort = useCallback((name: string) => {
    setCohorts((prev) =>
      prev.map((c) => {
        if (c.name === name) {
          const nextActive = !c.active;
          setLogMessage(`Cohort [${c.name}] toggled to ${nextActive ? "ACTIVE" : "INACTIVE"}.`);
          return { ...c, active: nextActive };
        }
        return c;
      })
    );
  }, []);

  // Save or update cohort
  const handleSaveCohort = useCallback((newCohort: Cohort, oldName?: string) => {
    setCohorts((prev) => {
      if (oldName) {
        return prev.map((c) => (c.name === oldName ? newCohort : c));
      } else {
        return [...prev, newCohort];
      }
    });
    setLogMessage(`Saved cohort [${newCohort.name}] with ${newCohort.sampleIds.length} isolates.`);
  }, []);

  // Clone cohort
  const handleCloneCohort = useCallback((sourceName: string) => {
    setCohorts((prev) => {
      const source = prev.find((c) => c.name === sourceName);
      if (!source) return prev;

      let candidate = `${source.name} (Copy)`;
      let counter = 2;
      while (prev.some((c) => c.name === candidate)) {
        candidate = `${source.name} (Copy ${counter})`;
        counter++;
      }

      const palette = ["#3b82f6", "#a855f7", "#f59e0b", "#ec4899", "#06b6d4", "#84cc16", "#f97316"];
      const newColor = palette[prev.length % palette.length];

      const cloned: Cohort = {
        name: candidate,
        sampleIds: [...source.sampleIds],
        description: `Cloned from ${source.name}`,
        color: newColor,
        active: true,
      };

      setLogMessage(`Duplicated cohort [${source.name}] to [${candidate}] (${source.sampleIds.length} isolates).`);
      return [...prev, cloned];
    });
  }, []);

  // Delete cohort
  const handleDeleteCohort = useCallback((name: string) => {
    if (name === "All Samples") return;
    setCohorts((prev) => prev.filter((c) => c.name !== name));
    setLogMessage(`Deleted cohort [${name}].`);
  }, []);

  // Cycle format tag
  const handleSelectFormatTag = useCallback((tag: FormatTag) => {
    setFormatTag(tag);
    setLogMessage(`Switched sample matrix to [${tag}] view.`);
  }, []);

  // Cycle view mode
  const handleCycleViewMode = useCallback(() => {
    setViewMode((prev) => {
      const modes: ViewMode[] = ["normal", "compact", "essential", "raw"];
      const nextIdx = (modes.indexOf(prev) + 1) % modes.length;
      const next = modes[nextIdx];
      setLogMessage(`Switched fixed variant columns to [${next.toUpperCase()}] view.`);
      return next;
    });
  }, []);

  // Cycle filter
  const handleCycleFilter = useCallback(() => {
    const filters = ["ALL", "DRUG_RESISTANT", "INDEL", "SNP"];
    setActiveFilter((prev) => {
      const nextIdx = (filters.indexOf(prev) + 1) % filters.length;
      const next = filters[nextIdx];
      setLogMessage(`Variant filter set to [${next.replace("_", " ")}].`);
      return next;
    });
    setSelectedVariantIndex(0);
  }, []);

  // Toggle split-pane
  const handleToggleSplit = useCallback(() => {
    setIsSplitExpanded((prev) => {
      const next = !prev;
      setLogMessage(`Cohort Statistics split-pane ${next ? "Expanded" : "Collapsed"}.`);
      return next;
    });
  }, []);

  // Fetch more variants on scroll when streaming large datasets
  const handleNeedMoreRows = useCallback(async (offset: number, limit: number) => {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const token = urlParams.get("token");
      const tokenQuery = token ? `&token=${encodeURIComponent(token)}` : "";
      const resp = await fetch(`/api/variants?offset=${offset}&limit=${limit}${tokenQuery}`, {
        credentials: "same-origin",
      });
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.variants) && data.variants.length > 0) {
          setVariants((prev) => {
            const existingIds = new Set(prev.map((x) => x.id));
            const newRows = data.variants.filter((x: Variant) => !existingIds.has(x.id));
            return [...prev, ...newRows];
          });
        }
      }
    } catch {
      // ignore
    }
  }, []);

  // Jump directly to a genomic coordinate or marker gene
  const handleJumpLocus = useCallback(async (chrom: string, pos: number) => {
    try {
      setLogMessage(`Seeking to ${chrom}:${pos.toLocaleString()}...`);
      const urlParams = new URLSearchParams(window.location.search);
      const token = urlParams.get("token");
      const tokenQuery = token ? `&token=${encodeURIComponent(token)}` : "";
      const start = Math.max(0, pos - 10000);
      const end = pos + 100000;
      const resp = await fetch(
        `/api/region?chrom=${encodeURIComponent(chrom)}&start=${start}&end=${end}&limit=100${tokenQuery}`,
        { credentials: "same-origin" }
      );
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.variants) && data.variants.length > 0) {
          setVariants(data.variants);
          setSelectedVariantIndex(0);
          setSelectedSampleIndex(0);
          setLogMessage(`Jumped to ${chrom}:${pos.toLocaleString()} (${data.variants.length} nearby variants).`);
          return;
        }
      }
      setLogMessage(`No variants found near ${chrom}:${pos.toLocaleString()}`);
    } catch (e: unknown) {
      setLogMessage(`Error seeking locus: ${String(e)}`);
    }
  }, []);

  // Cell selection
  const handleSelectCell = useCallback(
    (vIdx: number, sIdx: number) => {
      setSelectedVariantIndex(vIdx);
      setSelectedSampleIndex(sIdx);
      const rec = filteredVariants[vIdx];
      if (rec) {
        const sample = sIdx >= 0 ? samples[sIdx] : null;
        const samplePart = sample ? ` | Sample: ${sample}` : "";
        const drugPart = rec.drug ? ` [${rec.drug} Resistance]` : "";
        setLogMessage(`Locus: ${rec.chrom}:${rec.pos.toLocaleString()} (${rec.gene})${drugPart}${samplePart}`);
      }
    },
    [filteredVariants, samples]
  );

  // Global Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if typing in input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      switch (e.key) {
        case "1":
          handleSelectFormatTag("GT");
          break;
        case "2":
          handleSelectFormatTag("DP");
          break;
        case "3":
          handleSelectFormatTag("AD");
          break;
        case "4":
          handleSelectFormatTag("GQ");
          break;
        case "v":
        case "V":
          handleCycleViewMode();
          break;
        case "g":
        case "G":
          setIsJumpModalOpen((prev) => !prev);
          break;
        case "s":
        case "S":
          handleToggleSplit();
          break;
        case "c":
        case "C":
          setIsCohortModalOpen((prev) => !prev);
          break;
        case "f":
        case "F":
          handleCycleFilter();
          break;
        case "t":
        case "T":
          e.preventDefault();
          handleToggleTheme();
          break;
        case "?":
          setIsHelpModalOpen((prev) => !prev);
          break;
        case "ArrowDown":
          e.preventDefault();
          setSelectedVariantIndex((prev) => {
            const next = Math.min(filteredVariants.length - 1, prev + 1);
            const rec = filteredVariants[next];
            if (rec) {
              setLogMessage(`Locus: ${rec.chrom}:${rec.pos.toLocaleString()} (${rec.gene})`);
            }
            return next;
          });
          break;
        case "ArrowUp":
          e.preventDefault();
          setSelectedVariantIndex((prev) => {
            const next = Math.max(0, prev - 1);
            const rec = filteredVariants[next];
            if (rec) {
              setLogMessage(`Locus: ${rec.chrom}:${rec.pos.toLocaleString()} (${rec.gene})`);
            }
            return next;
          });
          break;
        case "ArrowRight":
          e.preventDefault();
          setSelectedSampleIndex((prev) => {
            const next = Math.min(samples.length - 1, prev + 1);
            const sample = samples[next];
            const rec = filteredVariants[selectedVariantIndex];
            if (rec && sample) {
              const drugPart = rec.drug ? ` [${rec.drug} Resistance]` : "";
              setLogMessage(
                `Locus: ${rec.chrom}:${rec.pos.toLocaleString()} (${rec.gene})${drugPart} | Sample: ${sample}`
              );
            }
            return next;
          });
          break;
        case "ArrowLeft":
          e.preventDefault();
          setSelectedSampleIndex((prev) => {
            const next = Math.max(0, prev - 1);
            const sample = samples[next];
            const rec = filteredVariants[selectedVariantIndex];
            if (rec && sample) {
              const drugPart = rec.drug ? ` [${rec.drug} Resistance]` : "";
              setLogMessage(
                `Locus: ${rec.chrom}:${rec.pos.toLocaleString()} (${rec.gene})${drugPart} | Sample: ${sample}`
              );
            }
            return next;
          });
          break;
        default:
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    cohorts,
    filteredVariants,
    samples,
    selectedVariantIndex,
    handleCycleFilter,
    handleCycleViewMode,
    handleSelectFormatTag,
    handleToggleCohort,
    handleToggleSplit,
    handleToggleTheme,
  ]);

  const isLight = theme === "light";
  const isSecured = useMemo(() => Boolean(new URLSearchParams(window.location.search).get("token")), []);

  return (
    <div
      className={`w-screen h-screen flex flex-col font-mono overflow-hidden transition-colors duration-150 ${
        isLight ? "bg-[#f8fafc] text-[#0f172a]" : "bg-[#0f141c] text-[#e2e8f0]"
      }`}
    >
      {/* 1. Top Header Bar */}
      <HeaderBar
        filename={filename}
        totalVariants={totalVariantsCount > filteredVariants.length ? totalVariantsCount : filteredVariants.length}
        totalSamples={samples.length}
        viewMode={viewMode}
        formatTag={formatTag}
        theme={theme}
        isSecured={isSecured}
        onToggleTheme={handleToggleTheme}
        onOpenPixiGuide={() => setIsPixiModalOpen(true)}
        onOpenHelp={() => setIsHelpModalOpen(true)}
        onOpenFile={handleOpenFile}
        onOpenJumpModal={() => setIsJumpModalOpen(true)}
      />

      {/* 2. Main Center Container (Table + Right Sidebar) */}
      <div className="flex-1 flex overflow-hidden">
        {/* Central Data Table with vertical split and row virtualization */}
        <VariantTable
          variants={filteredVariants}
          totalVariantsCount={totalVariantsCount}
          samples={samples}
          selectedVariantIndex={selectedVariantIndex}
          selectedSampleIndex={selectedSampleIndex}
          viewMode={viewMode}
          formatTag={formatTag}
          theme={theme}
          onSelectCell={handleSelectCell}
          onNeedMoreRows={handleNeedMoreRows}
        />

        {/* Right Sidebar (Variant Summary, Cohorts & Filters, Cell Inspector) */}
        <Sidebar
          variant={currentVariant}
          selectedSampleId={currentSampleId}
          cohorts={cohorts}
          onToggleCohort={handleToggleCohort}
          onOpenCohortManager={() => setIsCohortModalOpen(true)}
          activeFilter={activeFilter}
          theme={theme}
          onSelectFilter={(f) => {
            setActiveFilter(f);
            setSelectedVariantIndex(0);
            setLogMessage(`Variant filter set to [${f.replace("_", " ")}].`);
          }}
        />
      </div>

      {/* 3. Resizable Split-Pane (Cohort Statistics) */}
      <CohortStatsPane
        variant={currentVariant}
        cohorts={cohorts}
        isExpanded={isSplitExpanded}
        onToggleExpand={handleToggleSplit}
        height={splitHeight}
        onResize={(h) => setSplitHeight(h)}
        theme={theme}
      />

      {/* 4. Bottom Footer Bar (Hotkeys & Log Console) */}
      <FooterBar
        viewMode={viewMode}
        formatTag={formatTag}
        logMessage={logMessage}
        theme={theme}
        onSelectFormatTag={handleSelectFormatTag}
        onCycleViewMode={handleCycleViewMode}
        onToggleSplit={handleToggleSplit}
        onToggleCohorts={() => setIsCohortModalOpen(true)}
        onCycleFilter={handleCycleFilter}
        onToggleTheme={handleToggleTheme}
        onOpenHelp={() => setIsHelpModalOpen(true)}
      />

      {/* Cohort Definition, Inversion & Cloning Modal */}
      <CohortModal
        isOpen={isCohortModalOpen}
        onClose={() => setIsCohortModalOpen(false)}
        cohorts={cohorts}
        allSamples={samples}
        theme={theme}
        onSaveCohort={handleSaveCohort}
        onCloneCohort={handleCloneCohort}
        onDeleteCohort={handleDeleteCohort}
      />

      {/* Pixi & Git Installation Guide Modal */}
      <PixiGuideModal
        isOpen={isPixiModalOpen}
        onClose={() => setIsPixiModalOpen(false)}
        theme={theme}
      />

      {/* Keyboard Shortcuts Help Modal */}
      <HelpModal
        isOpen={isHelpModalOpen}
        onClose={() => setIsHelpModalOpen(false)}
        theme={theme}
      />

      {/* Genomic Locus & Gene Jumper Modal */}
      <JumpModal
        isOpen={isJumpModalOpen}
        onClose={() => setIsJumpModalOpen(false)}
        theme={theme}
        onJump={handleJumpLocus}
      />
    </div>
  );
}
