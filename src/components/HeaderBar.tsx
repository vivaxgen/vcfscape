import React, { useRef } from "react";
import { ViewMode, FormatTag, ThemeMode } from "../types/vcf";
import { Download, HelpCircle, Sun, Moon, FolderOpen, ShieldCheck, MapPin } from "lucide-react";

interface HeaderBarProps {
  filename: string;
  totalVariants: number;
  totalSamples: number;
  viewMode: ViewMode;
  formatTag: FormatTag;
  theme: ThemeMode;
  isSecured?: boolean;
  onToggleTheme: () => void;
  onOpenPixiGuide: () => void;
  onOpenHelp: () => void;
  onOpenFile?: (file: File) => void;
  onOpenJumpModal?: () => void;
}

export const HeaderBar: React.FC<HeaderBarProps> = ({
  filename,
  totalVariants,
  totalSamples,
  viewMode,
  formatTag,
  theme,
  isSecured,
  onToggleTheme,
  onOpenPixiGuide,
  onOpenHelp,
  onOpenFile,
  onOpenJumpModal,
}) => {
  const isLight = theme === "light";
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && onOpenFile) {
      onOpenFile(file);
    }
    // reset input so the same file can be selected again if needed
    if (e.target) {
      e.target.value = "";
    }
  };

  return (
    <header
      className={`h-8 border-b px-3 flex items-center justify-between text-xs select-none transition-colors duration-150 ${
        isLight
          ? "bg-[#e2e8f0] border-[#cbd5e1] text-slate-800"
          : "bg-[#1e293b] border-[#334155] text-slate-200"
      }`}
    >
      <div className="flex items-center space-x-2 overflow-hidden">
        <span
          className={`font-bold px-1.5 py-0.5 rounded-xs tracking-wider uppercase text-[10px] ${
            isLight
              ? "bg-cyan-600 text-white"
              : "bg-cyan-400 text-black"
          }`}
          title="VCFscape - VCF inspector part of vivaxGEN Project"
        >
          VCFSCAPE
        </span>
        {isSecured && (
          <span
            className={`inline-flex items-center space-x-1 font-semibold px-1.5 py-0.5 rounded-xs text-[10px] ${
              isLight
                ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                : "bg-emerald-950/80 text-emerald-300 border border-emerald-700/50"
            }`}
            title="Web session authenticated with secure URL token"
          >
            <ShieldCheck className="w-3 h-3 text-emerald-500" />
            <span className="hidden sm:inline">Token Secured</span>
          </span>
        )}
        <span className={`font-semibold truncate ${isLight ? "text-slate-900" : "text-white"}`}>
          {filename}
        </span>
        <span className={isLight ? "text-slate-400" : "text-slate-500"}>│</span>
        <span className={`${isLight ? "text-slate-600" : "text-slate-400"} hidden sm:inline`}>
          Genome:
        </span>
        <span className={`${isLight ? "text-amber-700" : "text-amber-400"} font-bold hidden sm:inline`}>
          Pf3D7_v3
        </span>
        <span className={`${isLight ? "text-slate-400" : "text-slate-500"} hidden sm:inline`}>
          │
        </span>
        <span className={isLight ? "text-slate-600" : "text-slate-400"}>Vars:</span>
        <span className={`${isLight ? "text-emerald-700" : "text-emerald-400"} font-bold`}>
          {totalVariants}
        </span>
        <span className={isLight ? "text-slate-400" : "text-slate-500"}>│</span>
        <span className={isLight ? "text-slate-600" : "text-slate-400"}>Samples:</span>
        <span className={`${isLight ? "text-emerald-700" : "text-emerald-400"} font-bold`}>
          {totalSamples}
        </span>
        <span className={isLight ? "text-slate-400" : "text-slate-500"}>│</span>
        <span className={isLight ? "text-slate-600" : "text-slate-400"}>View:</span>
        <span className={`${isLight ? "text-purple-700" : "text-purple-400"} font-bold capitalize`}>
          [{viewMode}]
        </span>
        <span className={isLight ? "text-slate-400" : "text-slate-500"}>│</span>
        <span className={isLight ? "text-slate-600" : "text-slate-400"}>Tag:</span>
        <span className={`${isLight ? "text-cyan-700" : "text-cyan-400"} font-bold`}>
          [{formatTag}]
        </span>
      </div>

      <div className="flex items-center space-x-2 flex-shrink-0">
        {/* Open VCF file picker */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".vcf,.vcf.gz,.gz"
          onChange={handleFileChange}
          className="hidden"
          data-testid="vcf-file-input"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          className={`flex items-center space-x-1 px-2 py-0.5 rounded-xs text-[11px] font-mono border transition-colors ${
            isLight
              ? "bg-cyan-50 hover:bg-cyan-100 text-cyan-800 border-cyan-300 shadow-2xs"
              : "bg-[#0f172a] hover:bg-[#334155] text-cyan-300 border-cyan-500/30"
          }`}
          title="Open local VCF file (.vcf or .vcf.gz)"
        >
          <FolderOpen className="w-3 h-3" />
          <span>Open VCF</span>
        </button>

        {/* Jump to Locus / Gene modal */}
        {onOpenJumpModal && (
          <button
            onClick={onOpenJumpModal}
            className={`flex items-center space-x-1 px-2 py-0.5 rounded-xs text-[11px] font-mono border transition-colors ${
              isLight
                ? "bg-sky-50 hover:bg-sky-100 text-sky-800 border-sky-300 shadow-2xs"
                : "bg-[#0f172a] hover:bg-[#334155] text-sky-300 border-sky-500/30"
            }`}
            title="Jump to Genomic Locus / Gene (HotKey: 'g')"
          >
            <MapPin className="w-3 h-3 text-sky-400" />
            <span>Jump Locus</span>
            <kbd className={`px-1 py-0.2 rounded-2xs text-[9px] border ${isLight ? "bg-slate-100 text-slate-600 border-slate-300" : "bg-slate-800 text-slate-400 border-slate-700"}`}>
              g
            </kbd>
          </button>
        )}

        {/* Dark/Light Theme Toggle with 't' hotkey cue */}
        <button
          onClick={onToggleTheme}
          className={`flex items-center space-x-1.5 px-2 py-0.5 rounded-xs text-[11px] font-mono border transition-colors ${
            isLight
              ? "bg-white hover:bg-slate-100 text-slate-800 border-slate-300 shadow-2xs"
              : "bg-[#0f172a] hover:bg-[#334155] text-slate-200 border-slate-700"
          }`}
          title="Toggle Dark / Light Theme (HotKey: 't')"
          aria-label="Toggle Dark or Light theme"
        >
          {isLight ? (
            <>
              <Moon className="w-3.5 h-3.5 text-indigo-600" />
              <span className="font-semibold text-slate-700">Light</span>
              <kbd className="px-1 py-0.2 bg-slate-100 text-slate-600 rounded-2xs text-[9px] border border-slate-300">
                t
              </kbd>
            </>
          ) : (
            <>
              <Sun className="w-3.5 h-3.5 text-amber-400" />
              <span className="font-semibold text-amber-300">Dark</span>
              <kbd className="px-1 py-0.2 bg-slate-800 text-slate-400 rounded-2xs text-[9px] border border-slate-700">
                t
              </kbd>
            </>
          )}
        </button>

        <button
          onClick={onOpenPixiGuide}
          className={`flex items-center space-x-1 px-2 py-0.5 rounded-xs text-[11px] transition-colors border ${
            isLight
              ? "bg-amber-50 hover:bg-amber-100 text-amber-900 border-amber-300"
              : "bg-[#0f172a] hover:bg-[#334155] text-amber-300 border-amber-500/30"
          }`}
          title="Pixi, uv, and pip Git installation commands"
        >
          <Download className="w-3 h-3" />
          <span>Pixi / Git Install</span>
        </button>

        <button
          onClick={onOpenHelp}
          className={`p-1 rounded-xs transition-colors ${
            isLight
              ? "hover:bg-slate-300 text-slate-700"
              : "hover:bg-[#334155] text-slate-300"
          }`}
          title="Keyboard shortcuts & help (?)"
        >
          <HelpCircle className="w-3.5 h-3.5" />
        </button>
      </div>
    </header>
  );
};
