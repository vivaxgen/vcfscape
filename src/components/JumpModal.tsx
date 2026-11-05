import React, { useState } from "react";
import { ThemeMode } from "../types/vcf";

interface JumpModalProps {
  isOpen: boolean;
  onClose: () => void;
  theme: ThemeMode;
  onJump: (chrom: string, pos: number) => void;
}

const PRESETS = [
  { gene: "pfcrt (Chr 7)", chrom: "Pf3D7_07_v3", pos: 403000, desc: "Chloroquine resistance" },
  { gene: "pfk13 (Chr 13)", chrom: "Pf3D7_13_v3", pos: 1725000, desc: "Artemisinin partial resistance" },
  { gene: "pfmdr1 (Chr 5)", chrom: "Pf3D7_05_v3", pos: 958000, desc: "Multidrug resistance" },
  { gene: "pfdhfr (Chr 4)", chrom: "Pf3D7_04_v3", pos: 748000, desc: "Pyrimethamine resistance" },
  { gene: "pfdhps (Chr 8)", chrom: "Pf3D7_08_v3", pos: 549000, desc: "Sulfadoxine resistance" },
];

export const JumpModal: React.FC<JumpModalProps> = ({
  isOpen,
  onClose,
  theme,
  onJump,
}) => {
  const [inputVal, setInputVal] = useState("");
  const isLight = theme === "light";

  if (!isOpen) return null;

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const val = inputVal.trim();
    if (!val) return;

    if (val.includes(":")) {
      const parts = val.split(":");
      let chrom = parts[0].trim();
      if (chrom.toLowerCase().startsWith("pf3d7")) {
        chrom = "Pf3D7" + chrom.slice(5);
      }
      const pos = parseInt(parts[1].replace(/,/g, "").trim(), 10);
      if (!isNaN(pos)) {
        onJump(chrom, pos);
        onClose();
        return;
      }
    }

    // Check gene presets
    const lower = val.toLowerCase();
    const matched = PRESETS.find(
      (p) => p.gene.toLowerCase().includes(lower) || p.desc.toLowerCase().includes(lower)
    );
    if (matched) {
      onJump(matched.chrom, matched.pos);
      onClose();
      return;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
      <div
        className={`w-full max-w-md rounded-lg shadow-2xl border p-6 font-mono ${
          isLight ? "bg-white border-slate-200 text-slate-900" : "bg-[#161e2e] border-slate-700 text-slate-100"
        }`}
      >
        <div className="flex items-center justify-between pb-3 border-b border-slate-700">
          <h2 className="text-base font-bold text-sky-400">Genomic Locus & Gene Jumper</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-lg font-bold px-2"
          >
            &times;
          </button>
        </div>

        <p className="text-xs text-slate-400 mt-3 mb-4 leading-relaxed">
          Instantly seek directly into large multi-gigabyte VCFs by genomic coordinate or marker gene without loading entire files.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase text-slate-300 mb-1">
              Genomic Locus or Gene
            </label>
            <input
              type="text"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              placeholder="e.g. Pf3D7_07_v3:403000 or 'crt'"
              autoFocus
              className={`w-full px-3 py-2 text-sm rounded-md border font-mono outline-none ${
                isLight
                  ? "bg-slate-50 border-slate-300 text-slate-900 focus:border-sky-500"
                  : "bg-slate-900 border-slate-600 text-slate-100 focus:border-sky-400"
              }`}
            />
          </div>

          <div>
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Quick Drug-Resistance Loci
            </div>
            <div className="grid grid-cols-1 gap-1.5 max-h-48 overflow-y-auto">
              {PRESETS.map((p) => (
                <button
                  key={p.gene}
                  type="button"
                  onClick={() => {
                    onJump(p.chrom, p.pos);
                    onClose();
                  }}
                  className={`text-left px-3 py-2 rounded-md text-xs transition-colors flex items-center justify-between ${
                    isLight
                      ? "bg-slate-100 hover:bg-sky-50 text-slate-800 hover:text-sky-800"
                      : "bg-slate-800/70 hover:bg-slate-700 text-slate-200 hover:text-sky-300"
                  }`}
                >
                  <span className="font-bold text-sky-400">{p.gene}</span>
                  <span className="text-[11px] text-slate-400">
                    {p.chrom}:{p.pos.toLocaleString()}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-slate-700">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-1.5 text-xs rounded-md bg-slate-700 hover:bg-slate-600 text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-1.5 text-xs rounded-md bg-sky-600 hover:bg-sky-500 text-white font-semibold shadow-xs"
            >
              Jump to Locus
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
