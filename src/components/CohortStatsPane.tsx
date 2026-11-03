import React, { useState } from "react";
import { Variant, Cohort, ThemeMode } from "../types/vcf";
import { ChevronUp, ChevronDown, BarChart2, GripHorizontal } from "lucide-react";

interface CohortStatsPaneProps {
  variant: Variant | null;
  cohorts: Cohort[];
  isExpanded: boolean;
  onToggleExpand: () => void;
  height: number;
  onResize: (newHeight: number) => void;
  theme?: ThemeMode;
}

export const CohortStatsPane: React.FC<CohortStatsPaneProps> = ({
  variant,
  cohorts,
  isExpanded,
  onToggleExpand,
  height,
  onResize,
  theme = "dark",
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const isLight = theme === "light";

  // Compute stats for each active cohort
  const computeCohortMetrics = (c: Cohort) => {
    if (!variant) return null;

    const sampleSet = new Set(c.sampleIds);
    const sampleDataEntries = Object.entries(variant.samples).filter(([s]) => sampleSet.has(s));

    const totalSamples = c.sampleIds.length;
    let called = 0;
    let missing = 0;
    let polyCount = 0;
    const dpList: number[] = [];
    const alleleCounts: Record<number, number> = { 0: 0 };
    for (let i = 1; i <= variant.alt.length; i++) {
      alleleCounts[i] = 0;
    }
    let totalAn = 0;

    sampleDataEntries.forEach(([, data]) => {
      if (data.DP !== undefined && data.DP > 0) {
        dpList.push(data.DP);
      }

      const gt = data.GT;
      if (!gt || gt === "./." || gt === ".") {
        missing++;
      } else {
        called++;
        const parts = gt.replace("|", "/").split("/");
        const unique = new Set(parts);
        if (unique.size > 1) {
          polyCount++;
        }

        parts.forEach((p) => {
          const aIdx = parseInt(p, 10);
          if (!isNaN(aIdx) && aIdx >= 0) {
            totalAn++;
            alleleCounts[aIdx] = (alleleCounts[aIdx] || 0) + 1;
          }
        });
      }
    });

    const meanDp = dpList.length ? dpList.reduce((a, b) => a + b, 0) / dpList.length : 0;
    const minDp = dpList.length ? Math.min(...dpList) : 0;
    const maxDp = dpList.length ? Math.max(...dpList) : 0;

    return {
      totalSamples,
      called,
      missing,
      missingnessRate: totalSamples ? (missing / totalSamples) * 100 : 0,
      meanDp,
      minDp,
      maxDp,
      polyCount,
      polyRate: called ? (polyCount / called) * 100 : 0,
      alleleCounts,
      totalAn,
    };
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    const startY = e.clientY;
    const startHeight = height;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const delta = startY - moveEvent.clientY;
      const newHeight = Math.max(80, Math.min(320, startHeight + delta));
      onResize(newHeight);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  const activeCohorts = cohorts.filter((c) => c.active);

  if (!isExpanded) {
    return (
      <div
        onClick={onToggleExpand}
        className={`h-6 border-t px-3 flex items-center justify-between text-xs cursor-pointer select-none transition-colors ${
          isLight
            ? "bg-[#e2e8f0] border-[#cbd5e1] text-slate-700 hover:text-slate-900"
            : "bg-[#101725] border-[#1e293b] text-slate-400 hover:text-white"
        }`}
      >
        <div className="flex items-center space-x-2">
          <span className={`font-bold text-[11px] ${isLight ? "text-amber-800" : "text-amber-400"}`}>
            [s] COHORT STATISTICS
          </span>
          <span className={`text-[10px] ${isLight ? "text-slate-500" : "text-slate-500"}`}>
            (Collapsed — Click or press 's' to expand)
          </span>
        </div>
        <ChevronUp className="w-3.5 h-3.5" />
      </div>
    );
  }

  return (
    <div
      style={{ height: `${height}px` }}
      className={`border-t flex flex-col select-none relative overflow-hidden transition-colors duration-150 ${
        isLight
          ? "bg-[#f8fafc] border-[#cbd5e1]"
          : "bg-[#101725] border-[#1e293b]"
      }`}
    >
      {/* Drag handle */}
      <div
        onMouseDown={handleMouseDown}
        className={`h-1.5 w-full cursor-row-resize flex items-center justify-center transition-colors ${
          isLight
            ? "bg-[#cbd5e1] hover:bg-cyan-600/50"
            : "bg-[#1e293b] hover:bg-cyan-500/50"
        }`}
        title="Drag up or down to resize cohort split-pane"
      >
        <GripHorizontal className={`w-4 h-3 opacity-60 ${isLight ? "text-slate-500" : "text-slate-500"}`} />
      </div>

      {/* Pane Header */}
      <div
        className={`px-3 py-1 flex items-center justify-between border-b text-xs ${
          isLight
            ? "bg-[#e2e8f0] border-[#cbd5e1]"
            : "bg-[#131b26] border-slate-800"
        }`}
      >
        <div className="flex items-center space-x-2">
          <BarChart2 className={`w-3.5 h-3.5 ${isLight ? "text-amber-800" : "text-amber-400"}`} />
          <span className={`font-bold text-[11px] ${isLight ? "text-amber-800" : "text-amber-400"}`}>
            COHORT STATISTICS (SPLIT-PANE)
          </span>
          <span className={`text-[10px] hidden sm:inline ${isLight ? "text-slate-500" : "text-slate-500"}`}>
            [HotKey: 's' to collapse/expand]
          </span>
        </div>

        <button
          onClick={onToggleExpand}
          className={`p-0.5 rounded-xs transition-colors ${
            isLight
              ? "text-slate-600 hover:text-slate-900 hover:bg-slate-300"
              : "text-slate-400 hover:text-white hover:bg-slate-800"
          }`}
          title="Collapse split-pane (s)"
        >
          <ChevronDown className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Table Content */}
      <div
        className={`flex-1 overflow-auto scrollbar-thin p-2 ${
          isLight
            ? "scrollbar-thumb-slate-300 bg-[#f8fafc]"
            : "scrollbar-thumb-slate-700 bg-[#101725]"
        }`}
      >
        {!variant ? (
          <div className={`text-xs italic ${isLight ? "text-slate-500" : "text-slate-500"}`}>
            Select a variant to view cohort metrics
          </div>
        ) : (
          <table className="w-full text-left text-xs font-mono border-collapse border-none">
            <thead>
              <tr
                className={`border-b font-semibold text-[11px] ${
                  isLight
                    ? "text-amber-800 border-slate-300"
                    : "text-amber-400 border-slate-800"
                }`}
              >
                <th className="py-1 px-2">METRIC / ALLELE</th>
                {activeCohorts.map((c) => (
                  <th
                    key={c.name}
                    className={`py-1 px-2 whitespace-nowrap ${isLight ? "text-slate-800" : "text-slate-200"}`}
                  >
                    <span className="inline-flex items-center space-x-1.5">
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{ backgroundColor: c.color || "#3b82f6" }}
                      />
                      <span>{c.name.toUpperCase()}</span>
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody
              className={`text-[11px] divide-y ${
                isLight ? "divide-slate-200" : "divide-slate-800/40"
              }`}
            >
              {/* Called / Missingness */}
              <tr className={isLight ? "hover:bg-slate-200/40" : "hover:bg-slate-800/30"}>
                <td className={`py-1 px-2 font-medium ${isLight ? "text-cyan-800 font-bold" : "text-cyan-300"}`}>
                  Called / Missing
                </td>
                {activeCohorts.map((c) => {
                  const m = computeCohortMetrics(c);
                  if (!m) return <td key={c.name}>-</td>;
                  return (
                    <td
                      key={c.name}
                      className={`py-1 px-2 whitespace-nowrap ${isLight ? "text-slate-800" : "text-slate-300"}`}
                    >
                      {m.called}/{m.totalSamples}{" "}
                      <span className={isLight ? "text-slate-500" : "text-slate-500"}>
                        ({m.missingnessRate.toFixed(1)}% miss)
                      </span>
                    </td>
                  );
                })}
              </tr>

              {/* Mean Read Depth */}
              <tr className={isLight ? "hover:bg-slate-200/40" : "hover:bg-slate-800/30"}>
                <td className={`py-1 px-2 font-medium ${isLight ? "text-cyan-800 font-bold" : "text-cyan-300"}`}>
                  Mean Read Depth (DP)
                </td>
                {activeCohorts.map((c) => {
                  const m = computeCohortMetrics(c);
                  if (!m) return <td key={c.name}>-</td>;
                  return (
                    <td
                      key={c.name}
                      className={`py-1 px-2 whitespace-nowrap font-bold ${
                        isLight ? "text-emerald-700" : "text-emerald-400"
                      }`}
                    >
                      {m.meanDp.toFixed(1)}x{" "}
                      <span className={`font-normal ${isLight ? "text-slate-500" : "text-slate-500"}`}>
                        [{m.minDp} - {m.maxDp}x]
                      </span>
                    </td>
                  );
                })}
              </tr>

              {/* Polyclonal / Heterozygous infection rate */}
              <tr className={isLight ? "hover:bg-slate-200/40" : "hover:bg-slate-800/30"}>
                <td className={`py-1 px-2 font-medium ${isLight ? "text-cyan-800 font-bold" : "text-cyan-300"}`}>
                  Polyclonal / Het Rate
                </td>
                {activeCohorts.map((c) => {
                  const m = computeCohortMetrics(c);
                  if (!m) return <td key={c.name}>-</td>;
                  return (
                    <td
                      key={c.name}
                      className={`py-1 px-2 whitespace-nowrap font-bold ${
                        isLight ? "text-purple-700" : "text-fuchsia-400"
                      }`}
                    >
                      {m.polyCount} isolates{" "}
                      <span className={`font-normal ${isLight ? "text-slate-500" : "text-slate-500"}`}>
                        ({m.polyRate.toFixed(1)}%)
                      </span>
                    </td>
                  );
                })}
              </tr>

              {/* REF Allele Frequency */}
              <tr className={isLight ? "hover:bg-slate-200/40" : "hover:bg-slate-800/30"}>
                <td className={`py-1 px-2 ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                  REF [0: {variant.ref}]
                </td>
                {activeCohorts.map((c) => {
                  const m = computeCohortMetrics(c);
                  if (!m) return <td key={c.name}>-</td>;
                  const count = m.alleleCounts[0] || 0;
                  const af = m.totalAn ? count / m.totalAn : 0;
                  return (
                    <td
                      key={c.name}
                      className={`py-1 px-2 whitespace-nowrap ${isLight ? "text-slate-800" : "text-slate-300"}`}
                    >
                      AF ={" "}
                      <span className={`font-bold ${isLight ? "text-slate-950" : "text-white"}`}>
                        {af.toFixed(3)}
                      </span>{" "}
                      <span className={isLight ? "text-slate-500" : "text-slate-500"}>
                        (n={count})
                      </span>
                    </td>
                  );
                })}
              </tr>

              {/* ALT Alleles Frequencies */}
              {variant.alt.map((altAllele, altIdx) => {
                const aIdx = altIdx + 1;
                return (
                  <tr
                    key={altIdx}
                    className={isLight ? "hover:bg-slate-200/40" : "hover:bg-slate-800/30"}
                  >
                    <td className={`py-1 px-2 ${isLight ? "text-cyan-800 font-semibold" : "text-cyan-300"}`}>
                      ALT [{aIdx}: {altAllele}]
                    </td>
                    {activeCohorts.map((c) => {
                      const m = computeCohortMetrics(c);
                      if (!m) return <td key={c.name}>-</td>;
                      const count = m.alleleCounts[aIdx] || 0;
                      const af = m.totalAn ? count / m.totalAn : 0;
                      return (
                        <td
                          key={c.name}
                          className={`py-1 px-2 whitespace-nowrap ${
                            isLight ? "text-cyan-900 font-medium" : "text-cyan-300"
                          }`}
                        >
                          AF ={" "}
                          <span
                            className={`font-bold ${
                              isLight ? "text-amber-800" : "text-amber-300"
                            }`}
                          >
                            {af.toFixed(3)}
                          </span>{" "}
                          <span className={isLight ? "text-slate-500" : "text-slate-500"}>
                            (n={count})
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
