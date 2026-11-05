import React from "react";
import { Variant, Cohort, ThemeMode } from "../types/vcf";
import { VariantSummary } from "./VariantSummary";
import { Users, CheckSquare, Square, Eye } from "lucide-react";

interface SidebarProps {
  variant: Variant | null;
  selectedSampleId: string | null;
  cohorts: Cohort[];
  onToggleCohort: (name: string) => void;
  onOpenCohortManager?: () => void;
  activeFilter: string;
  onSelectFilter: (filter: string) => void;
  theme?: ThemeMode;
}

export const Sidebar: React.FC<SidebarProps> = ({
  variant,
  selectedSampleId,
  cohorts,
  onToggleCohort,
  onOpenCohortManager,
  activeFilter,
  onSelectFilter,
  theme = "dark",
}) => {
  const isLight = theme === "light";
  const sampleData = variant && selectedSampleId ? variant.samples[selectedSampleId] : null;

  return (
    <aside
      className={`w-80 min-w-[320px] max-w-[320px] flex-shrink-0 h-full flex flex-col overflow-y-auto scrollbar-thin select-none text-xs border-l divide-y transition-colors duration-150 ${
        isLight
          ? "bg-[#f8fafc] border-[#cbd5e1] divide-[#e2e8f0] scrollbar-thumb-slate-300 text-slate-800"
          : "bg-[#131b26] border-[#1e293b] divide-[#1e293b] scrollbar-thumb-slate-700 text-slate-200"
      }`}
    >
      {/* 1. Cohorts & Filters (CohortListWidget) */}
      <div className="p-3 space-y-2.5">
        <div className="flex items-center justify-between">
          <span
            className={`font-bold uppercase tracking-wider text-[11px] flex items-center space-x-1 ${
              isLight ? "text-purple-700" : "text-fuchsia-400"
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Cohorts & Filters</span>
          </span>
          <div className="flex items-center space-x-1.5">
            {onOpenCohortManager && (
              <button
                onClick={onOpenCohortManager}
                className={`px-1.5 py-0.5 rounded-xs text-[10px] font-semibold border flex items-center space-x-1 transition-colors ${
                  isLight
                    ? "bg-purple-100 hover:bg-purple-200 text-purple-900 border-purple-300"
                    : "bg-purple-950/60 hover:bg-purple-900/80 text-purple-300 border-purple-700"
                }`}
                title="Open Cohort Manager (Define, Clone, Invert, Delete)"
              >
                <span>Manage</span>
              </button>
            )}
            <span className={`text-[10px] ${isLight ? "text-slate-500" : "text-slate-500"}`}>
              ['c' / 'f']
            </span>
          </div>
        </div>

        {/* Cohort Checkboxes */}
        <div className="space-y-1">
          <span className={`font-semibold text-[10px] uppercase ${isLight ? "text-slate-600" : "text-slate-400"}`}>
            Active Cohorts:
          </span>
          {cohorts.map((c) => {
            const isAll = c.name === "All Samples";
            return (
              <div
                key={c.name}
                onClick={() => !isAll && onToggleCohort(c.name)}
                className={`flex items-center justify-between p-1 rounded-xs cursor-pointer transition-colors ${
                  c.active
                    ? isLight
                      ? "bg-blue-50 text-slate-900 border border-blue-200/80 font-medium"
                      : "bg-slate-800/60 text-slate-200"
                    : isLight
                    ? "text-slate-500 hover:text-slate-800 hover:bg-slate-200/50"
                    : "text-slate-500 hover:text-slate-400 hover:bg-slate-800"
                } ${isAll ? "cursor-default" : ""}`}
              >
                <div className="flex items-center space-x-1.5 truncate">
                  {c.active ? (
                    <CheckSquare
                      className={`w-3.5 h-3.5 flex-shrink-0 ${
                        isLight ? "text-emerald-600" : "text-emerald-400"
                      }`}
                    />
                  ) : (
                    <Square
                      className={`w-3.5 h-3.5 flex-shrink-0 ${
                        isLight ? "text-slate-400" : "text-slate-600"
                      }`}
                    />
                  )}
                  <span className="truncate">{c.name}</span>
                </div>
                <span className={`text-[10px] font-mono ${isLight ? "text-slate-500" : "text-slate-500"}`}>
                  n={c.sampleIds.length}
                </span>
              </div>
            );
          })}
          {cohorts.length <= 1 && (
            <div className={`text-[10px] italic py-1 px-1 leading-tight ${isLight ? "text-slate-500" : "text-slate-500"}`}>
              No custom cohorts defined. Click "Manage" or press 'c' to create cohorts.
            </div>
          )}
        </div>

        {/* Real-time Filter Buttons */}
        <div className={`space-y-1 pt-1 border-t ${isLight ? "border-slate-200" : "border-slate-800/60"}`}>
          <span className={`font-semibold text-[10px] uppercase ${isLight ? "text-slate-600" : "text-slate-400"}`}>
            Filter Variants:
          </span>
          <div className="grid grid-cols-2 gap-1 text-[11px]">
            {["ALL", "DRUG_RESISTANT", "INDEL", "SNP"].map((f) => (
              <button
                key={f}
                onClick={() => onSelectFilter(f)}
                className={`px-1.5 py-1 rounded-xs font-mono text-[10px] transition-colors text-center ${
                  activeFilter === f
                    ? isLight
                      ? "bg-cyan-600 text-white font-bold shadow-xs"
                      : "bg-cyan-500 text-black font-bold shadow-xs"
                    : isLight
                    ? "bg-white text-slate-700 hover:text-slate-900 border border-slate-300 shadow-2xs"
                    : "bg-[#0b0f17] text-slate-400 hover:text-white border border-slate-800"
                }`}
              >
                {f.replace("_", " ")}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 2. Variant Summary Panel (VariantSummary) */}
      <VariantSummary variant={variant} theme={theme} />

      {/* 3. Cell Inspector (Current sample's FORMAT fields) */}
      <div className="p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span
            className={`font-bold uppercase tracking-wider text-[11px] flex items-center space-x-1 ${
              isLight ? "text-amber-800" : "text-amber-400"
            }`}
          >
            <Eye className="w-3.5 h-3.5" />
            <span>Cell Inspector</span>
          </span>
          {selectedSampleId && (
            <span
              className={`text-[10px] font-mono px-1 py-0.2 rounded-xs border ${
                isLight
                  ? "text-cyan-900 bg-cyan-100 border-cyan-300 font-bold"
                  : "text-cyan-300 bg-cyan-950 border-cyan-800"
              }`}
            >
              {selectedSampleId}
            </span>
          )}
        </div>

        {!selectedSampleId || !sampleData ? (
          <div
            className={`p-2 text-xs italic rounded-xs border ${
              isLight
                ? "text-slate-500 bg-white border-slate-200"
                : "text-slate-500 bg-[#0b0f17] border-slate-800"
            }`}
          >
            Click any sample cell in the data table to inspect GT, DP, AD, and GQ.
          </div>
        ) : (
          <div
            className={`p-2.5 rounded-xs border space-y-1.5 font-mono text-xs ${
              isLight
                ? "bg-white border-slate-200 shadow-2xs"
                : "bg-[#0b0f17] border-slate-800"
            }`}
          >
            <div className="flex justify-between items-center">
              <span className={`font-sans ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                Genotype (GT):
              </span>
              <span
                className={`font-bold px-1.5 py-0.5 rounded-xs border ${
                  isLight
                    ? "text-purple-800 bg-purple-50 border-purple-300"
                    : "text-fuchsia-300 bg-fuchsia-950/60 border-fuchsia-800"
                }`}
              >
                {sampleData.GT}
              </span>
            </div>

            <div className="flex justify-between">
              <span className={`font-sans ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                Read Depth (DP):
              </span>
              <span className={`font-bold ${isLight ? "text-emerald-700" : "text-emerald-400"}`}>
                {sampleData.DP} reads
              </span>
            </div>

            <div className="flex justify-between">
              <span className={`font-sans ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                Allelic Depths (AD):
              </span>
              <span className={`font-bold ${isLight ? "text-amber-800" : "text-amber-300"}`}>
                {sampleData.AD}
              </span>
            </div>

            <div className="flex justify-between">
              <span className={`font-sans ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                Genotype Quality (GQ):
              </span>
              <span className={`font-bold ${isLight ? "text-slate-900" : "text-white"}`}>
                {sampleData.GQ}
              </span>
            </div>

            {sampleData.PL && (
              <div
                className={`flex justify-between text-[10px] pt-1 border-t ${
                  isLight
                    ? "border-slate-200 text-slate-500"
                    : "border-slate-800 text-slate-500"
                }`}
              >
                <span className="font-sans">Phred PL:</span>
                <span>{sampleData.PL}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
