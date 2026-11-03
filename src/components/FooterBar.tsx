import React from "react";
import { ViewMode, FormatTag, ThemeMode } from "../types/vcf";

interface FooterBarProps {
  viewMode: ViewMode;
  formatTag: FormatTag;
  logMessage: string;
  theme: ThemeMode;
  onSelectFormatTag: (tag: FormatTag) => void;
  onCycleViewMode: () => void;
  onToggleSplit: () => void;
  onToggleCohorts: () => void;
  onCycleFilter: () => void;
  onToggleTheme: () => void;
  onOpenHelp: () => void;
}

export const FooterBar: React.FC<FooterBarProps> = ({
  viewMode,
  formatTag,
  logMessage,
  theme,
  onSelectFormatTag,
  onCycleViewMode,
  onToggleSplit,
  onToggleCohorts,
  onCycleFilter,
  onToggleTheme,
  onOpenHelp,
}) => {
  const isLight = theme === "light";

  return (
    <footer
      className={`h-14 border-t px-3 flex flex-col justify-center text-xs select-none transition-colors duration-150 ${
        isLight
          ? "bg-[#e2e8f0] border-[#cbd5e1] text-slate-800"
          : "bg-[#090d14] border-[#1e293b] text-slate-200"
      }`}
    >
      {/* Row 1: Hotkey Action Bar */}
      <div className="flex items-center space-x-1 sm:space-x-2 text-[11px] overflow-x-auto scrollbar-none pb-0.5">
        <span className={`font-mono hidden md:inline ${isLight ? "text-slate-600" : "text-slate-500"}`}>
          Hotkeys:
        </span>

        {/* Format Tags (1-4) */}
        <div
          className={`flex items-center rounded-xs px-1 border ${
            isLight
              ? "bg-white border-slate-300"
              : "bg-[#131b26] border-slate-800"
          }`}
        >
          {(["GT", "DP", "AD", "GQ"] as FormatTag[]).map((tag, idx) => (
            <button
              key={tag}
              onClick={() => onSelectFormatTag(tag)}
              className={`px-1.5 py-0.5 rounded-xs font-mono transition-colors ${
                formatTag === tag
                  ? isLight
                    ? "bg-cyan-600 text-white font-bold"
                    : "bg-cyan-500 text-black font-bold"
                  : isLight
                  ? "text-slate-600 hover:text-slate-950"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              <span className={`font-bold mr-0.5 ${isLight ? "text-cyan-700" : "text-cyan-400"}`}>
                [{idx + 1}]
              </span>
              {tag}
            </button>
          ))}
        </div>

        <span className={isLight ? "text-slate-400" : "text-slate-700"}>│</span>

        {/* View Mode Toggle (v) */}
        <button
          onClick={onCycleViewMode}
          className={`px-2 py-0.5 rounded-xs transition-colors flex items-center space-x-1 border ${
            isLight
              ? "bg-white hover:bg-slate-100 text-slate-800 border-slate-300 shadow-2xs"
              : "bg-[#131b26] hover:bg-slate-800 text-slate-300 hover:text-white border-slate-800"
          }`}
          title="Toggle between Normal, Compact, Essential, and Raw 9-column view (v)"
        >
          <span className={`font-bold font-mono ${isLight ? "text-amber-700" : "text-amber-400"}`}>
            [v]
          </span>
          <span>View:</span>
          <span className={`font-semibold capitalize ${isLight ? "text-purple-700" : "text-purple-300"}`}>
            {viewMode}
          </span>
        </button>

        {/* Toggle Split-Pane (s) */}
        <button
          onClick={onToggleSplit}
          className={`px-2 py-0.5 rounded-xs transition-colors flex items-center space-x-1 border ${
            isLight
              ? "bg-white hover:bg-slate-100 text-slate-800 border-slate-300 shadow-2xs"
              : "bg-[#131b26] hover:bg-slate-800 text-slate-300 hover:text-white border-slate-800"
          }`}
          title="Toggle Cohort Statistics split-pane (s)"
        >
          <span className={`font-bold font-mono ${isLight ? "text-amber-700" : "text-amber-400"}`}>
            [s]
          </span>
          <span>Split</span>
        </button>

        {/* Cohort Toggle (c) */}
        <button
          onClick={onToggleCohorts}
          className={`px-2 py-0.5 rounded-xs transition-colors flex items-center space-x-1 border ${
            isLight
              ? "bg-white hover:bg-slate-100 text-slate-800 border-slate-300 shadow-2xs"
              : "bg-[#131b26] hover:bg-slate-800 text-slate-300 hover:text-white border-slate-800"
          }`}
          title="Open Cohort Manager to create, define, clone, invert, and delete cohorts (c)"
        >
          <span className={`font-bold font-mono ${isLight ? "text-amber-700" : "text-amber-400"}`}>
            [c]
          </span>
          <span>Cohorts (Mgr)</span>
        </button>

        {/* Filter Toggle (f) */}
        <button
          onClick={onCycleFilter}
          className={`px-2 py-0.5 rounded-xs transition-colors flex items-center space-x-1 border ${
            isLight
              ? "bg-white hover:bg-slate-100 text-slate-800 border-slate-300 shadow-2xs"
              : "bg-[#131b26] hover:bg-slate-800 text-slate-300 hover:text-white border-slate-800"
          }`}
          title="Cycle variant filter (f)"
        >
          <span className={`font-bold font-mono ${isLight ? "text-amber-700" : "text-amber-400"}`}>
            [f]
          </span>
          <span>Filter</span>
        </button>

        {/* Theme Toggle (t) */}
        <button
          onClick={onToggleTheme}
          className={`px-2 py-0.5 rounded-xs transition-colors flex items-center space-x-1 border ${
            isLight
              ? "bg-white hover:bg-slate-100 text-slate-900 border-indigo-300 shadow-2xs font-medium"
              : "bg-[#131b26] hover:bg-slate-800 text-slate-300 hover:text-white border-slate-800"
          }`}
          title="Toggle Dark / Light color theme (t)"
        >
          <span className={`font-bold font-mono ${isLight ? "text-indigo-600" : "text-amber-400"}`}>
            [t]
          </span>
          <span>Theme:</span>
          <span className={`font-semibold capitalize ${isLight ? "text-indigo-700" : "text-cyan-300"}`}>
            {theme}
          </span>
        </button>

        {/* Help (?) */}
        <button
          onClick={onOpenHelp}
          className={`px-2 py-0.5 rounded-xs transition-colors flex items-center space-x-1 border ${
            isLight
              ? "bg-white hover:bg-slate-100 text-slate-800 border-slate-300 shadow-2xs"
              : "bg-[#131b26] hover:bg-slate-800 text-slate-300 hover:text-white border-slate-800"
          }`}
          title="Open shortcuts help (?)"
        >
          <span className={`font-bold font-mono ${isLight ? "text-amber-700" : "text-amber-400"}`}>
            [?]
          </span>
          <span>Help</span>
        </button>
      </div>

      {/* Row 2: Live Status & Log Console */}
      <div className="flex items-center space-x-2 text-[11px] font-mono truncate pt-0.5">
        <span
          className={`px-1 py-0.2 font-bold rounded-2xs text-[9px] tracking-wide uppercase flex-shrink-0 ${
            isLight
              ? "bg-amber-500 text-white"
              : "bg-amber-400 text-black"
          }`}
        >
          LOG
        </span>
        <span className={`truncate ${isLight ? "text-slate-900 font-medium" : "text-slate-200"}`}>
          {logMessage}
        </span>
      </div>
    </footer>
  );
};
