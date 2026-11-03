import React from "react";
import { Variant, ThemeMode } from "../types/vcf";
import { ShieldAlert, Dna, Info } from "lucide-react";

interface VariantSummaryProps {
  variant: Variant | null;
  theme?: ThemeMode;
}

export const VariantSummary: React.FC<VariantSummaryProps> = ({ variant, theme = "dark" }) => {
  const isLight = theme === "light";

  if (!variant) {
    return (
      <div className={`p-3 italic text-xs ${isLight ? "text-slate-400" : "text-slate-500"}`}>
        No variant selected
      </div>
    );
  }

  const v = variant;

  return (
    <div className="p-3 space-y-3 text-xs select-none">
      <div
        className={`flex items-center justify-between pb-1 border-b ${
          isLight ? "border-slate-300" : "border-slate-700/60"
        }`}
      >
        <span
          className={`font-bold uppercase tracking-wider text-[11px] flex items-center space-x-1 ${
            isLight ? "text-cyan-800" : "text-cyan-400"
          }`}
        >
          <Dna className="w-3.5 h-3.5" />
          <span>Variant Summary</span>
        </span>
        <span
          className={`px-1.5 py-0.2 text-[10px] font-bold rounded-xs border ${
            v.filter === "PASS"
              ? isLight
                ? "bg-emerald-100 text-emerald-800 border-emerald-300"
                : "bg-emerald-950 text-emerald-400 border-emerald-800"
              : isLight
              ? "bg-rose-100 text-rose-800 border-rose-300"
              : "bg-rose-950 text-rose-400 border-rose-800"
          }`}
        >
          {v.filter}
        </span>
      </div>

      {/* Locus & Coordinates */}
      <div className="space-y-1">
        <div className="flex justify-between">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>Locus:</span>
          <span className={`font-mono font-medium ${isLight ? "text-slate-900" : "text-white"}`}>
            {v.chrom}:{v.pos.toLocaleString()}
          </span>
        </div>
        <div className="flex justify-between">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>ID / dbSNP:</span>
          <span className={`font-mono font-bold ${isLight ? "text-cyan-800" : "text-cyan-300"}`}>
            {v.varId}
          </span>
        </div>
        <div className="flex justify-between">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>Quality (QUAL):</span>
          <span className={`font-mono font-bold ${isLight ? "text-emerald-700" : "text-emerald-400"}`}>
            {v.qual}
          </span>
        </div>
        <div className="flex justify-between">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>Type:</span>
          <span
            className={`font-mono font-bold ${
              v.varType.includes("Multi")
                ? isLight
                  ? "text-amber-700"
                  : "text-amber-400"
                : isLight
                ? "text-slate-800"
                : "text-slate-200"
            }`}
          >
            {v.varType}
          </span>
        </div>
      </div>

      {/* Gene & Mutation Details */}
      <div
        className={`p-2 rounded-xs space-y-1 border ${
          isLight
            ? "bg-white border-slate-200 shadow-2xs"
            : "bg-[#0b0f17] border-slate-800"
        }`}
      >
        <div className="flex justify-between">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>Gene:</span>
          <span className={`font-bold font-mono ${isLight ? "text-amber-800" : "text-amber-300"}`}>
            {v.gene}
          </span>
        </div>
        <div className="flex justify-between">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>Mutation:</span>
          <span className={`font-bold font-mono ${isLight ? "text-purple-700" : "text-fuchsia-400"}`}>
            {v.mutation}
          </span>
        </div>
        <div className="flex justify-between">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>Impact:</span>
          <span className={`font-mono ${isLight ? "text-slate-800" : "text-slate-200"}`}>
            {v.impact}
          </span>
        </div>
      </div>

      {/* Alleles & Length Differences */}
      <div className="space-y-1 text-[11px]">
        <div className={`font-semibold text-[10px] uppercase ${isLight ? "text-slate-600" : "text-slate-400"}`}>
          Allele Breakdown:
        </div>
        <div className="flex items-center space-x-2">
          <span className={isLight ? "text-slate-600" : "text-slate-400"}>REF:</span>
          <span
            className={`font-mono px-1 py-0.5 rounded-xs border ${
              isLight
                ? "bg-slate-100 text-slate-800 border-slate-300"
                : "bg-slate-800 text-slate-200 border-slate-700"
            }`}
          >
            {v.ref} ({v.ref.length}bp)
          </span>
        </div>
        <div className="flex items-start space-x-2 pt-0.5">
          <span className={`mt-0.5 ${isLight ? "text-slate-600" : "text-slate-400"}`}>ALT:</span>
          <div className="flex flex-wrap gap-1">
            {v.alt.map((a, idx) => {
              const delta = a.length - v.ref.length;
              const deltaStr = delta !== 0 ? ` (${delta > 0 ? "+" : ""}${delta}bp)` : "";
              return (
                <span
                  key={idx}
                  className={`font-mono px-1 py-0.5 rounded-xs border ${
                    isLight
                      ? "bg-cyan-50 border-cyan-300 text-cyan-900"
                      : "bg-cyan-950/60 border-cyan-800 text-cyan-300"
                  }`}
                >
                  [{idx + 1}] {a}
                  <span className={`text-[10px] ${isLight ? "text-amber-800 font-bold" : "text-amber-300"}`}>
                    {deltaStr}
                  </span>
                </span>
              );
            })}
          </div>
        </div>
      </div>

      {/* Antimalarial Drug Resistance Surveillance Card */}
      {v.drug ? (
        <div
          className={`rounded-xs p-2.5 space-y-1 text-[11px] border ${
            isLight
              ? "bg-rose-50 border-rose-300"
              : "bg-rose-950/40 border-rose-700/60"
          }`}
        >
          <div
            className={`flex items-center space-x-1.5 font-bold text-xs uppercase tracking-wide ${
              isLight ? "text-rose-900" : "text-rose-300"
            }`}
          >
            <ShieldAlert className={`w-3.5 h-3.5 flex-shrink-0 ${isLight ? "text-rose-700" : "text-rose-400"}`} />
            <span>Drug Resistance Marker</span>
          </div>
          <div className="flex justify-between pt-1">
            <span className={isLight ? "text-slate-600" : "text-slate-400"}>Antimalarial:</span>
            <span className={`font-bold ${isLight ? "text-rose-900" : "text-rose-200"}`}>{v.drug}</span>
          </div>
          <div className="flex justify-between">
            <span className={isLight ? "text-slate-600" : "text-slate-400"}>WHO Status:</span>
            <span className={`font-semibold ${isLight ? "text-amber-800" : "text-amber-300"}`}>
              {v.drugStatus}
            </span>
          </div>
          <p
            className={`text-[10px] leading-tight pt-1 border-t ${
              isLight
                ? "border-rose-200 text-slate-700"
                : "border-rose-900/60 text-slate-300"
            }`}
          >
            {v.drugDetails}
          </p>
        </div>
      ) : (
        <div
          className={`p-2 rounded-xs text-[11px] flex items-center space-x-1.5 border ${
            isLight
              ? "bg-slate-100 border-slate-200 text-slate-600"
              : "bg-slate-900/60 border-slate-800 text-slate-400"
          }`}
        >
          <Info className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
          <span>Non-resistance surveillance locus</span>
        </div>
      )}
    </div>
  );
};
