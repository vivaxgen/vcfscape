import React from "react";
import { X, Keyboard } from "lucide-react";
import { ThemeMode } from "../types/vcf";

interface HelpModalProps {
  isOpen: boolean;
  onClose: () => void;
  theme?: ThemeMode;
}

export const HelpModal: React.FC<HelpModalProps> = ({ isOpen, onClose, theme = "dark" }) => {
  if (!isOpen) return null;
  const isLight = theme === "light";

  const hotkeys = [
    { key: "1", action: "Genotype (GT)", desc: "Show genotypes (0/0, 0/1, 1/1, 1/2) with polygenomic highlights" },
    { key: "2", action: "Read Depth (DP)", desc: "Show sequencing read depth per sample cell" },
    { key: "3", action: "Allelic Depth (AD)", desc: "Show allelic depths for REF and multi-allelic ALT alleles" },
    { key: "4", action: "Genotype Quality (GQ)", desc: "Show Phred-scaled confidence score" },
    { key: "v", action: "Cycle View Mode", desc: "Toggle between Normal, Compact, Essential, and Raw 9-column view" },
    { key: "s", action: "Toggle Split-Pane", desc: "Expand or collapse the Cohort Statistics split-pane" },
    { key: "c", action: "Cohort Manager", desc: "Open modal to define, clone, invert selections, or delete cohorts" },
    { key: "f", action: "Cycle Filter", desc: "Filter by ALL, DRUG_RESISTANT, INDEL, or SNP" },
    { key: "t", action: "Toggle Theme", desc: "Toggle between Dark and Light mode (also persists in local settings)" },
    { key: "↑ / ↓", action: "Row Navigation", desc: "Move active cursor between variant rows" },
    { key: "← / →", action: "Column Navigation", desc: "Move active cursor between sample isolate columns" },
    { key: "?", action: "Help Modal", desc: "Open this keyboard shortcuts cheatsheet" },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4">
      <div
        className={`border rounded-xs max-w-xl w-full p-5 space-y-4 shadow-2xl text-xs font-mono ${
          isLight
            ? "bg-white border-slate-300 text-slate-800"
            : "bg-[#131b26] border-cyan-500/40 text-slate-200"
        }`}
      >
        <div
          className={`flex items-center justify-between pb-2 border-b ${
            isLight ? "border-slate-200" : "border-slate-700"
          }`}
        >
          <div className="flex items-center space-x-2">
            <Keyboard className={`w-5 h-5 ${isLight ? "text-cyan-700" : "text-cyan-400"}`} />
            <h2 className={`text-sm font-bold uppercase tracking-wider ${isLight ? "text-slate-900" : "text-white"}`}>
              VCFscape Shortcuts
            </h2>
          </div>
          <button
            onClick={onClose}
            className={`p-1 rounded-xs transition-colors ${
              isLight
                ? "text-slate-500 hover:text-slate-900 hover:bg-slate-100"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-1.5 max-h-[60vh] overflow-y-auto pr-1">
          {hotkeys.map((h) => (
            <div
              key={h.key}
              className={`flex items-center justify-between p-2 rounded-xs border ${
                isLight
                  ? "bg-slate-50 border-slate-200"
                  : "bg-[#0b0f17] border-slate-800/80"
              }`}
            >
              <div className="flex items-center space-x-2.5">
                <kbd
                  className={`px-2 py-0.5 font-bold rounded-xs text-xs shadow-xs min-w-[28px] text-center border ${
                    isLight
                      ? "bg-white text-indigo-700 border-slate-300"
                      : "bg-slate-800 text-amber-300 border-slate-700"
                  }`}
                >
                  {h.key}
                </kbd>
                <span className={`font-semibold ${isLight ? "text-slate-900" : "text-slate-200"}`}>
                  {h.action}
                </span>
              </div>
              <span
                className={`text-[11px] text-right font-sans max-w-[280px] ${
                  isLight ? "text-slate-600" : "text-slate-400"
                }`}
              >
                {h.desc}
              </span>
            </div>
          ))}
        </div>

        <div className={`pt-2 border-t flex justify-end ${isLight ? "border-slate-200" : "border-slate-800"}`}>
          <button
            onClick={onClose}
            className={`px-4 py-1.5 font-bold text-xs rounded-xs transition-colors ${
              isLight
                ? "bg-cyan-600 hover:bg-cyan-500 text-white"
                : "bg-cyan-500 hover:bg-cyan-400 text-black"
            }`}
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
};
