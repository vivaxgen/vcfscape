import React, { useState } from "react";
import { X, Copy, Check, Terminal, Package, GitBranch, Play } from "lucide-react";
import { ThemeMode } from "../types/vcf";

interface PixiGuideModalProps {
  isOpen: boolean;
  onClose: () => void;
  theme?: ThemeMode;
}

export const PixiGuideModal: React.FC<PixiGuideModalProps> = ({ isOpen, onClose, theme = "dark" }) => {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const isLight = theme === "light";

  if (!isOpen) return null;

  const copyToClipboard = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const snippets = [
    {
      title: "Run Web Version with Python (No Node.js Needed)",
      cmd: `vcfscape-web\n# or: vcfscape --web\n# or: ./run_web.sh`,
      desc: "Instant zero-dependency local web server powered by Python's built-in HTTP server; opens browser at http://localhost:3000."
    },
    {
      title: "Run Web Version with Pixi Tasks",
      cmd: `pixi run web\n# or for live Vite development: pixi run dev-web`,
      desc: "Executes the pre-configured pixi task in your local environment."
    },
    {
      title: "Direct Execution with uv (No Install Needed)",
      cmd: `uv run --with "git+https://github.com/<user>/vcfscape.git" vcfscape-web`,
      desc: "Instant one-liner to clone and launch the web simulator in an ephemeral environment."
    },
    {
      title: "Local Development & Live Editing (.tsx files)",
      cmd: `npm install\nnpm run dev\n# Or with Pixi: pixi run dev-web`,
      desc: "Starts the live Vite dev server at http://localhost:3000 with Hot Module Replacement for editing React/TSX files."
    },
    {
      title: "Build Web Version & Sync to Python Package",
      cmd: `npm run build:bundle\n# Or with Pixi: pixi run build-bundle`,
      desc: "Compiles TypeScript and Vite production assets directly into src/vcfscape/web_dist/ for Python's vcfscape-web launcher."
    },
    {
      title: "Preview Production Build Locally",
      cmd: `npm run build && npm run preview`,
      desc: "Builds production assets to dist/ and runs a local static preview server."
    },
    {
      title: "Install Package via Pixi (PyPI from Git)",
      cmd: `pixi add --pypi "git+https://github.com/<user>/vcfscape.git"`,
      desc: "Installs directly into your Pixi project environment as a PyPI dependency from git."
    },
    {
      title: "Run Terminal TUI via uv or pip",
      cmd: `uv run --with "git+https://github.com/<user>/vcfscape.git" vcfscape --demo\n# or with pip:\npip install -e . && vcfscape --demo`,
      desc: "Launches the rich Textual terminal user interface."
    },
    {
      title: "Run Unit Test Suite",
      cmd: `python3 -m unittest discover tests`,
      desc: "Executes automated unit tests (VCF reader, multi-allelic indels, cohorts, WHO markers, web server)."
    }
  ];

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4">
      <div
        className={`border rounded-xs max-w-2xl w-full p-5 space-y-4 shadow-2xl text-xs font-mono ${
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
            <Package className={`w-5 h-5 ${isLight ? "text-amber-700" : "text-amber-400"}`} />
            <h2 className={`text-sm font-bold uppercase tracking-wider ${isLight ? "text-slate-900" : "text-white"}`}>
              Execution & Installation Guide
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

        <p className={`text-[11px] leading-relaxed ${isLight ? "text-slate-600" : "text-slate-300"}`}>
          This package supports both the Python Textual terminal TUI and this interactive Web version.
          You can execute the Web version on your local machine using Python's standard library (no Node.js required)
          or through Pixi tasks.
        </p>

        <div className="space-y-3 max-h-[55vh] overflow-y-auto pr-1">
          {snippets.map((s, idx) => (
            <div
              key={idx}
              className={`p-3 rounded-xs space-y-1.5 border ${
                isLight
                  ? "bg-slate-50 border-slate-200"
                  : "bg-[#0b0f17] border-slate-800/80"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className={`font-semibold ${isLight ? "text-slate-900" : "text-white"}`}>
                  {s.title}
                </span>
                <button
                  onClick={() => copyToClipboard(s.cmd, idx)}
                  className={`flex items-center space-x-1 px-1.5 py-0.5 rounded-2xs text-[10px] transition-colors border ${
                    isLight
                      ? "bg-white hover:bg-slate-100 text-slate-700 border-slate-300"
                      : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                  }`}
                >
                  {copiedIndex === idx ? (
                    <>
                      <Check className="w-3 h-3 text-emerald-500" />
                      <span className="text-emerald-500 font-bold">Copied</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      <span>Copy</span>
                    </>
                  )}
                </button>
              </div>
              <pre
                className={`p-2 rounded-xs overflow-x-auto text-[11px] border leading-snug ${
                  isLight
                    ? "bg-white text-slate-900 border-slate-200"
                    : "bg-[#05080e] text-emerald-300 border-slate-900"
                }`}
              >
                <code>{s.cmd}</code>
              </pre>
              <p className={`text-[10px] font-sans ${isLight ? "text-slate-500" : "text-slate-400"}`}>
                {s.desc}
              </p>
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
            Close Guide
          </button>
        </div>
      </div>
    </div>
  );
};
