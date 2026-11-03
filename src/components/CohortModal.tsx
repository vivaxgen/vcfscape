import React, { useState, useMemo, useEffect } from "react";
import { Cohort, ThemeMode } from "../types/vcf";
import {
  Users,
  X,
  Plus,
  Copy,
  Trash2,
  Check,
  Search,
  CheckSquare,
  Square,
  RefreshCw,
  Sparkles,
  Info,
} from "lucide-react";

interface CohortModalProps {
  isOpen: boolean;
  onClose: () => void;
  cohorts: Cohort[];
  allSamples: string[];
  theme?: ThemeMode;
  onSaveCohort: (cohort: Cohort, oldName?: string) => void;
  onCloneCohort: (sourceName: string) => void;
  onDeleteCohort: (name: string) => void;
}

const PALETTE = [
  "#10b981", // emerald
  "#3b82f6", // blue
  "#a855f7", // purple
  "#f59e0b", // amber
  "#ec4899", // pink
  "#06b6d4", // cyan
  "#84cc16", // lime
  "#f97316", // orange
  "#6366f1", // indigo
  "#ef4444", // red
];

export const CohortModal: React.FC<CohortModalProps> = ({
  isOpen,
  onClose,
  cohorts,
  allSamples,
  theme = "dark",
  onSaveCohort,
  onCloneCohort,
  onDeleteCohort,
}) => {
  const isLight = theme === "light";

  const [selectedCohortName, setSelectedCohortName] = useState<string>(
    cohorts[0]?.name || "All Samples"
  );
  const [isCreatingNew, setIsCreatingNew] = useState<boolean>(false);

  // Form State
  const [name, setName] = useState<string>("");
  const [description, setDescription] = useState<string>("");
  const [color, setColor] = useState<string>(PALETTE[1]);
  const [selectedSamples, setSelectedSamples] = useState<Set<string>>(new Set());

  // Search & Filter State
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [filterMode, setFilterMode] = useState<"all" | "selected">("all");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [confirmDelete, setConfirmDelete] = useState<boolean>(false);

  // Sync active cohort into form when selectedCohortName changes or modal opens
  useEffect(() => {
    if (!isOpen) return;

    if (isCreatingNew) {
      setName(`Cohort ${cohorts.length + 1}`);
      setDescription("Custom defined isolate group");
      setColor(PALETTE[cohorts.length % PALETTE.length]);
      setSelectedSamples(new Set());
      setConfirmDelete(false);
      setErrorMessage("");
      return;
    }

    const current = cohorts.find((c) => c.name === selectedCohortName) || cohorts[0];
    if (current) {
      setName(current.name);
      setDescription(current.description || "");
      setColor(current.color || PALETTE[1]);
      setSelectedSamples(new Set(current.sampleIds));
      setConfirmDelete(false);
      setErrorMessage("");
    }
  }, [selectedCohortName, isCreatingNew, isOpen, cohorts]);

  // Keyboard shortcut inside modal: Esc to close, Ctrl+I to invert
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === "i" || e.key === "I")) {
        e.preventDefault();
        handleInvertSelection();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A") && !(e.target instanceof HTMLInputElement)) {
        e.preventDefault();
        handleSelectAll();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, allSamples, selectedSamples]);

  // Filtered sample list
  const filteredSamples = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return allSamples.filter((sampleId) => {
      const matchesSearch = !term || sampleId.toLowerCase().includes(term);
      if (!matchesSearch) return false;
      if (filterMode === "selected") {
        return selectedSamples.has(sampleId);
      }
      return true;
    });
  }, [allSamples, searchTerm, filterMode, selectedSamples]);

  // Toggle single sample checkbox
  const handleToggleSample = (sampleId: string) => {
    setSelectedSamples((prev) => {
      const next = new Set(prev);
      if (next.has(sampleId)) {
        next.delete(sampleId);
      } else {
        next.add(sampleId);
      }
      return next;
    });
  };

  // Bulk actions
  const handleSelectAll = () => {
    const term = searchTerm.trim().toLowerCase();
    setSelectedSamples((prev) => {
      const next = new Set(prev);
      allSamples.forEach((s) => {
        if (!term || s.toLowerCase().includes(term)) {
          next.add(s);
        }
      });
      return next;
    });
  };

  const handleDeselectAll = () => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) {
      setSelectedSamples(new Set());
    } else {
      setSelectedSamples((prev) => {
        const next = new Set(prev);
        allSamples.forEach((s) => {
          if (s.toLowerCase().includes(term)) {
            next.delete(s);
          }
        });
        return next;
      });
    }
  };

  const handleInvertSelection = () => {
    setSelectedSamples((prev) => {
      const next = new Set<string>();
      allSamples.forEach((s) => {
        if (!prev.has(s)) {
          next.add(s);
        }
      });
      return next;
    });
  };

  // Actions
  const handleSave = () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setErrorMessage("Cohort name cannot be empty.");
      return;
    }

    if (isCreatingNew) {
      const exists = cohorts.some((c) => c.name.toLowerCase() === trimmedName.toLowerCase());
      if (exists) {
        setErrorMessage(`A cohort named "${trimmedName}" already exists.`);
        return;
      }
      onSaveCohort({
        name: trimmedName,
        sampleIds: Array.from(selectedSamples),
        description,
        color,
        active: true,
      });
    } else {
      const exists = cohorts.some(
        (c) => c.name.toLowerCase() === trimmedName.toLowerCase() && c.name !== selectedCohortName
      );
      if (exists) {
        setErrorMessage(`Another cohort named "${trimmedName}" already exists.`);
        return;
      }
      onSaveCohort(
        {
          name: trimmedName,
          sampleIds: Array.from(selectedSamples),
          description,
          color,
          active: true,
        },
        selectedCohortName
      );
    }

    setIsCreatingNew(false);
    setSelectedCohortName(trimmedName);
    onClose();
  };

  const handleClone = () => {
    if (isCreatingNew) return;
    onCloneCohort(selectedCohortName);
  };

  const handleDelete = () => {
    if (isCreatingNew || selectedCohortName === "All Samples") return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    onDeleteCohort(selectedCohortName);
    setConfirmDelete(false);
    setSelectedCohortName("All Samples");
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs select-none">
      <div
        className={`w-full max-w-4xl h-[90vh] max-h-[720px] rounded-lg shadow-2xl flex flex-col overflow-hidden border font-mono transition-colors duration-150 ${
          isLight
            ? "bg-[#f8fafc] border-[#cbd5e1] text-slate-900"
            : "bg-[#111827] border-[#1e293b] text-slate-100"
        }`}
      >
        {/* 1. Modal Header */}
        <div
          className={`flex items-center justify-between px-5 py-3.5 border-b ${
            isLight ? "bg-white border-slate-200" : "bg-[#161f30] border-slate-800"
          }`}
        >
          <div className="flex items-center space-x-2.5">
            <div className="p-1.5 rounded-md bg-purple-600/20 text-purple-400">
              <Users className="w-5 h-5 text-purple-500" />
            </div>
            <div>
              <h2 className="text-sm font-bold tracking-wide uppercase">
                Cohort Definition & Sample Groups
              </h2>
              <p className={`text-[11px] ${isLight ? "text-slate-500" : "text-slate-400"}`}>
                Define custom cohorts, filter isolates, clone groups, and compute stratified metrics.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className={`p-1.5 rounded-md transition-colors ${
              isLight
                ? "text-slate-400 hover:text-slate-700 hover:bg-slate-100"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 2. Main Two-Column Layout */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left Column: Cohort List & Switcher */}
          <div
            className={`w-64 flex-shrink-0 flex flex-col border-r divide-y overflow-y-auto ${
              isLight ? "bg-slate-50/70 border-slate-200 divide-slate-200" : "bg-[#0d1421] border-slate-800 divide-slate-800"
            }`}
          >
            <div className="p-3">
              <button
                onClick={() => setIsCreatingNew(true)}
                className="w-full flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-md bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold shadow-xs transition-colors"
              >
                <Plus className="w-4 h-4" />
                <span>New Cohort</span>
              </button>
            </div>

            <div className="flex-1 p-2 space-y-1 overflow-y-auto scrollbar-thin">
              <span className={`px-2 text-[10px] font-bold uppercase tracking-wider ${isLight ? "text-slate-400" : "text-slate-500"}`}>
                Existing Cohorts
              </span>
              {cohorts.map((c) => {
                const isSelected = !isCreatingNew && selectedCohortName === c.name;
                return (
                  <div
                    key={c.name}
                    onClick={() => {
                      setIsCreatingNew(false);
                      setSelectedCohortName(c.name);
                    }}
                    className={`flex items-center justify-between p-2 rounded-md cursor-pointer text-xs transition-colors ${
                      isSelected
                        ? isLight
                          ? "bg-purple-100 text-purple-900 font-semibold border border-purple-200"
                          : "bg-purple-950/60 text-purple-200 font-semibold border border-purple-800/80"
                        : isLight
                        ? "text-slate-700 hover:bg-slate-200/60"
                        : "text-slate-300 hover:bg-slate-800/60"
                    }`}
                  >
                    <div className="flex items-center space-x-2 truncate">
                      <span
                        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: c.color || "#3b82f6" }}
                      />
                      <span className="truncate">{c.name}</span>
                    </div>
                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-xs ${
                      isLight ? "bg-slate-200 text-slate-600" : "bg-slate-800 text-slate-400"
                    }`}>
                      {c.sampleIds.length}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Column: Cohort Editor & Sample Checklist */}
          <div className="flex-1 flex flex-col p-4 space-y-3 overflow-hidden">
            {/* Top Editor Row: Name, Description, Color */}
            <div className={`p-3 rounded-md border space-y-2.5 ${
              isLight ? "bg-white border-slate-200 shadow-2xs" : "bg-[#151c2a] border-slate-800"
            }`}>
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wider text-purple-500">
                  {isCreatingNew ? "Creating New Cohort" : `Editing: ${selectedCohortName}`}
                </span>
                {!isCreatingNew && (
                  <div className="flex items-center space-x-1.5">
                    <button
                      onClick={handleClone}
                      className={`flex items-center space-x-1 px-2 py-1 rounded-xs text-[11px] border transition-colors ${
                        isLight
                          ? "bg-slate-100 hover:bg-slate-200 text-slate-700 border-slate-300"
                          : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                      }`}
                      title="Clone this cohort's sample selection into a new cohort"
                    >
                      <Copy className="w-3.5 h-3.5" />
                      <span>Clone</span>
                    </button>
                    {selectedCohortName !== "All Samples" && (
                      <button
                        onClick={handleDelete}
                        className={`flex items-center space-x-1 px-2 py-1 rounded-xs text-[11px] border transition-colors ${
                          confirmDelete
                            ? "bg-red-600 hover:bg-red-700 text-white border-red-700 font-bold"
                            : isLight
                            ? "bg-red-50 hover:bg-red-100 text-red-700 border-red-200"
                            : "bg-red-950/40 hover:bg-red-900/60 text-red-400 border-red-900/60"
                        }`}
                        title="Delete this cohort"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        <span>{confirmDelete ? "Confirm Delete?" : "Delete"}</span>
                      </button>
                    )}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className={`block mb-1 text-[11px] font-semibold ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                    Cohort Name:
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value);
                      setErrorMessage("");
                    }}
                    placeholder="e.g. Asymptomatic Responders"
                    className={`w-full px-2.5 py-1.5 rounded-md border text-xs outline-none focus:ring-1 focus:ring-purple-500 font-sans ${
                      isLight
                        ? "bg-slate-50 border-slate-300 text-slate-900"
                        : "bg-[#0b0f17] border-slate-700 text-white"
                    }`}
                  />
                </div>

                <div>
                  <label className={`block mb-1 text-[11px] font-semibold ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                    Description:
                  </label>
                  <input
                    type="text"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Optional details or criteria"
                    className={`w-full px-2.5 py-1.5 rounded-md border text-xs outline-none focus:ring-1 focus:ring-purple-500 font-sans ${
                      isLight
                        ? "bg-slate-50 border-slate-300 text-slate-900"
                        : "bg-[#0b0f17] border-slate-700 text-white"
                    }`}
                  />
                </div>
              </div>

              {/* Color Presets */}
              <div className="flex items-center space-x-2 text-xs pt-1">
                <span className={`text-[11px] font-semibold ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                  Color Tag:
                </span>
                <div className="flex items-center space-x-1.5">
                  {PALETTE.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setColor(c)}
                      className={`w-5 h-5 rounded-full transition-transform flex items-center justify-center ${
                        color === c ? "scale-115 ring-2 ring-purple-400" : "hover:scale-105"
                      }`}
                      style={{ backgroundColor: c }}
                    >
                      {color === c && <Check className="w-3 h-3 text-white" />}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Error Message */}
            {errorMessage && (
              <div className="px-3 py-1.5 rounded-md bg-red-500/10 border border-red-500/30 text-red-500 text-xs flex items-center space-x-1.5">
                <Info className="w-4 h-4 flex-shrink-0" />
                <span>{errorMessage}</span>
              </div>
            )}

            {/* Middle Toolbar: Search & Selection Controls */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <div className="flex items-center space-x-2 flex-1 max-w-sm">
                <div className="relative w-full">
                  <Search className={`w-3.5 h-3.5 absolute left-2.5 top-2.5 ${isLight ? "text-slate-400" : "text-slate-500"}`} />
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="Search samples by ID (e.g. KL_001)..."
                    className={`w-full pl-8 pr-2 py-1.5 rounded-md border text-xs outline-none focus:ring-1 focus:ring-purple-500 ${
                      isLight
                        ? "bg-white border-slate-300 text-slate-900"
                        : "bg-[#0b0f17] border-slate-700 text-white"
                    }`}
                  />
                </div>
              </div>

              {/* Quick Actions: Select All, Clear All, Invert Selection */}
              <div className="flex items-center space-x-1.5">
                <button
                  onClick={handleSelectAll}
                  className={`px-2 py-1 rounded-xs text-[11px] border font-medium transition-colors ${
                    isLight
                      ? "bg-white hover:bg-slate-100 text-slate-700 border-slate-300 shadow-2xs"
                      : "bg-[#161f30] hover:bg-slate-800 text-slate-300 border-slate-700"
                  }`}
                >
                  Select All
                </button>
                <button
                  onClick={handleDeselectAll}
                  className={`px-2 py-1 rounded-xs text-[11px] border font-medium transition-colors ${
                    isLight
                      ? "bg-white hover:bg-slate-100 text-slate-700 border-slate-300 shadow-2xs"
                      : "bg-[#161f30] hover:bg-slate-800 text-slate-300 border-slate-700"
                  }`}
                >
                  Clear All
                </button>
                <button
                  onClick={handleInvertSelection}
                  className={`flex items-center space-x-1 px-2.5 py-1 rounded-xs text-[11px] border font-semibold transition-colors ${
                    isLight
                      ? "bg-amber-50 hover:bg-amber-100 text-amber-800 border-amber-300 shadow-2xs"
                      : "bg-amber-950/40 hover:bg-amber-900/60 text-amber-300 border-amber-800"
                  }`}
                  title="Invert Selection (Ctrl+I): flips checked and unchecked samples"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span>Invert Selection</span>
                </button>
                <button
                  onClick={() => setFilterMode((prev) => (prev === "all" ? "selected" : "all"))}
                  className={`px-2 py-1 rounded-xs text-[11px] border transition-colors ${
                    filterMode === "selected"
                      ? "bg-purple-600 text-white border-purple-600 font-semibold"
                      : isLight
                      ? "bg-white hover:bg-slate-100 text-slate-600 border-slate-300"
                      : "bg-[#161f30] hover:bg-slate-800 text-slate-400 border-slate-700"
                  }`}
                >
                  {filterMode === "selected" ? "Selected Only" : "Show All"}
                </button>
              </div>
            </div>

            {/* Selection Summary Count */}
            <div className="flex items-center justify-between text-xs px-1">
              <span className={`font-semibold ${isLight ? "text-purple-800" : "text-purple-400"}`}>
                Selected: {selectedSamples.size} / {allSamples.length} isolates ({((selectedSamples.size / allSamples.length) * 100).toFixed(1)}%)
              </span>
              <span className={`text-[11px] ${isLight ? "text-slate-500" : "text-slate-400"}`}>
                Showing {filteredSamples.length} matching isolates
              </span>
            </div>

            {/* Sample Checklist Grid */}
            <div
              className={`flex-1 rounded-md border p-2 overflow-y-auto scrollbar-thin grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1.5 ${
                isLight ? "bg-white border-slate-200" : "bg-[#0b0f17] border-slate-800"
              }`}
            >
              {filteredSamples.map((sampleId) => {
                const isChecked = selectedSamples.has(sampleId);
                return (
                  <div
                    key={sampleId}
                    onClick={() => handleToggleSample(sampleId)}
                    className={`flex items-center justify-between p-1.5 rounded-md cursor-pointer text-xs border transition-colors ${
                      isChecked
                        ? isLight
                          ? "bg-purple-50 text-purple-900 border-purple-300 font-medium shadow-2xs"
                          : "bg-purple-950/40 text-purple-200 border-purple-800 font-medium"
                        : isLight
                        ? "bg-slate-50 hover:bg-slate-100 text-slate-600 border-slate-200"
                        : "bg-[#111827] hover:bg-slate-800 text-slate-400 border-slate-800"
                    }`}
                  >
                    <div className="flex items-center space-x-1.5 truncate">
                      {isChecked ? (
                        <CheckSquare className="w-3.5 h-3.5 text-purple-500 flex-shrink-0" />
                      ) : (
                        <Square className={`w-3.5 h-3.5 flex-shrink-0 ${isLight ? "text-slate-400" : "text-slate-600"}`} />
                      )}
                      <span className="font-mono truncate">{sampleId}</span>
                    </div>
                  </div>
                );
              })}
              {filteredSamples.length === 0 && (
                <div className="col-span-full py-8 text-center text-xs text-slate-500 italic">
                  No sample isolates match the search criteria.
                </div>
              )}
            </div>

            {/* Bottom Footer Actions */}
            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-slate-800/40">
              <button
                onClick={onClose}
                className={`px-4 py-1.5 rounded-md text-xs font-semibold border transition-colors ${
                  isLight
                    ? "bg-white hover:bg-slate-100 text-slate-700 border-slate-300"
                    : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                }`}
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="px-5 py-1.5 rounded-md text-xs font-semibold bg-purple-600 hover:bg-purple-700 text-white shadow-xs transition-colors flex items-center space-x-1.5"
              >
                <Check className="w-4 h-4" />
                <span>Save Cohort</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
