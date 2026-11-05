import React, { useRef, useEffect, useState, useCallback } from "react";
import { Variant, ViewMode, FormatTag, ThemeMode } from "../types/vcf";

interface VariantTableProps {
  variants: Variant[];
  totalVariantsCount?: number;
  samples: string[];
  selectedVariantIndex: number;
  selectedSampleIndex: number;
  viewMode: ViewMode;
  formatTag: FormatTag;
  theme: ThemeMode;
  onSelectCell: (variantIndex: number, sampleIndex: number) => void;
  onNeedMoreRows?: (offset: number, limit: number) => void;
}

export const VariantTable: React.FC<VariantTableProps> = ({
  variants,
  totalVariantsCount,
  samples,
  selectedVariantIndex,
  selectedSampleIndex,
  viewMode,
  formatTag,
  theme,
  onSelectCell,
  onNeedMoreRows,
}) => {
  const leftTableRef = useRef<HTMLDivElement>(null);
  const rightTableRef = useRef<HTMLDivElement>(null);
  const isSyncingRef = useRef<boolean>(false);
  const lastRequestedOffsetRef = useRef<number>(-1);
  const isLight = theme === "light";

  const ROW_HEIGHT = 28; // exactly 28px per row
  const OVERSCAN = 20;   // render 20 rows above and below viewport for fluid scrolling

  const [scrollTop, setScrollTop] = useState<number>(0);
  const [viewportHeight, setViewportHeight] = useState<number>(600);

  // Initialize and update viewport height on resize
  useEffect(() => {
    const updateHeight = () => {
      if (leftTableRef.current) {
        setViewportHeight(leftTableRef.current.clientHeight || 600);
      }
    };
    updateHeight();
    window.addEventListener("resize", updateHeight);
    return () => window.removeEventListener("resize", updateHeight);
  }, []);

  // Check if approaching bottom of loaded variants and request more from backend
  const checkNeedMoreRows = useCallback((currentScrollTop: number) => {
    if (!onNeedMoreRows) return;
    const totalCount = totalVariantsCount && totalVariantsCount > variants.length ? totalVariantsCount : variants.length;
    const estBottomRow = Math.ceil((currentScrollTop + viewportHeight) / ROW_HEIGHT);
    if (estBottomRow >= variants.length - 40 && variants.length < totalCount) {
      if (lastRequestedOffsetRef.current !== variants.length) {
        lastRequestedOffsetRef.current = variants.length;
        onNeedMoreRows(variants.length, 100);
      }
    }
  }, [onNeedMoreRows, totalVariantsCount, variants.length, viewportHeight, ROW_HEIGHT]);

  // Synchronize vertical scroll from Left to Right
  const handleLeftScroll = () => {
    if (isSyncingRef.current) return;
    isSyncingRef.current = true;
    if (leftTableRef.current && rightTableRef.current) {
      const top = leftTableRef.current.scrollTop;
      rightTableRef.current.scrollTop = top;
      setScrollTop(top);
      checkNeedMoreRows(top);
    }
    requestAnimationFrame(() => {
      isSyncingRef.current = false;
    });
  };

  // Synchronize vertical scroll from Right to Left
  const handleRightScroll = () => {
    if (isSyncingRef.current) return;
    isSyncingRef.current = true;
    if (leftTableRef.current && rightTableRef.current) {
      const top = rightTableRef.current.scrollTop;
      leftTableRef.current.scrollTop = top;
      setScrollTop(top);
      checkNeedMoreRows(top);
    }
    requestAnimationFrame(() => {
      isSyncingRef.current = false;
    });
  };

  // Synchronized wheel event on either pane
  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      if (leftTableRef.current && rightTableRef.current) {
        const newTop = leftTableRef.current.scrollTop + e.deltaY;
        leftTableRef.current.scrollTop = newTop;
        rightTableRef.current.scrollTop = newTop;
        setScrollTop(newTop);
        checkNeedMoreRows(newTop);
      }
    }
  };

  // Auto-scroll selected row into view synchronously
  useEffect(() => {
    if (leftTableRef.current && rightTableRef.current) {
      const targetTop = selectedVariantIndex * ROW_HEIGHT;
      const currentTop = leftTableRef.current.scrollTop;
      const vpHeight = leftTableRef.current.clientHeight - 32;

      if (targetTop < currentTop) {
        leftTableRef.current.scrollTop = targetTop;
        rightTableRef.current.scrollTop = targetTop;
        setScrollTop(targetTop);
      } else if (targetTop + ROW_HEIGHT > currentTop + vpHeight) {
        const scrollTo = targetTop + ROW_HEIGHT - vpHeight;
        leftTableRef.current.scrollTop = scrollTo;
        rightTableRef.current.scrollTop = scrollTo;
        setScrollTop(scrollTo);
      }
    }
  }, [selectedVariantIndex, ROW_HEIGHT]);

  // Auto-scroll selected sample column horizontally into view
  useEffect(() => {
    const handleHorizontalScroll = () => {
      if (!rightTableRef.current || selectedSampleIndex < 0 || selectedSampleIndex >= samples.length) {
        return;
      }

      const container = rightTableRef.current;
      if (selectedSampleIndex === 0) {
        container.scrollLeft = 0;
        return;
      }

      const ths = container.querySelectorAll("thead th");
      const targetTh = ths[selectedSampleIndex] as HTMLElement | undefined;
      if (!targetTh) return;

      const containerRect = container.getBoundingClientRect();
      const thRect = targetTh.getBoundingClientRect();
      const halfScreen = Math.floor(container.clientWidth / 2);

      if (thRect.left < containerRect.left) {
        const cellLeftInContainer = container.scrollLeft + (thRect.left - containerRect.left);
        const targetScroll = Math.max(0, Math.min(container.scrollLeft - halfScreen, cellLeftInContainer - 16));
        container.scrollLeft = targetScroll;
      } else if (thRect.right > containerRect.right) {
        const cellRightInContainer = container.scrollLeft + (thRect.right - containerRect.left);
        const targetScroll = Math.max(container.scrollLeft + halfScreen, cellRightInContainer - container.clientWidth + 16);
        container.scrollLeft = targetScroll;
      }
    };

    handleHorizontalScroll();
    window.addEventListener("resize", handleHorizontalScroll);
    return () => window.removeEventListener("resize", handleHorizontalScroll);
  }, [selectedSampleIndex, samples.length, formatTag, viewMode]);

  const getFixedColumns = () => {
    switch (viewMode) {
      case "raw":
        return ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"];
      case "compact":
        return ["CHROM", "POS", "REF", "ALT"];
      case "essential":
        return ["CHROM", "POS"];
      case "normal":
      default:
        return ["CHROM", "POS", "REF", "ALT", "QUAL", "FILTER", "GENE"];
    }
  };

  const fixedCols = getFixedColumns();

  // Virtual Row Slice Calculation
  const totalCount = totalVariantsCount && totalVariantsCount > variants.length ? totalVariantsCount : variants.length;
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const endIndex = Math.min(variants.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + OVERSCAN);

  const topPadHeight = startIndex * ROW_HEIGHT;
  const bottomPadHeight = Math.max(0, (totalCount - endIndex) * ROW_HEIGHT);
  const visibleVariants = variants.slice(startIndex, endIndex);

  // Helper to format sample cell value & color
  const renderSampleValue = (v: Variant, sampleId: string) => {
    const sData = v.samples[sampleId];
    if (!sData) return <span className={isLight ? "text-slate-400 font-mono" : "text-slate-600 font-mono"}>./.</span>;

    const val = sData[formatTag];

    if (formatTag === "GT") {
      const gtStr = String(val);
      if (gtStr === "0/0" || gtStr === "0") {
        return <span className={`${isLight ? "text-slate-500" : "text-slate-500"} font-mono`}>{gtStr}</span>;
      }
      if (gtStr === "./." || gtStr === ".") {
        return <span className={`${isLight ? "text-slate-400" : "text-slate-600"} font-mono`}>./.</span>;
      }
      const parts = gtStr.replace("|", "/").split("/");
      const uniqueAlleles = new Set(parts);
      if (uniqueAlleles.size > 1) {
        return (
          <span className={`${isLight ? "text-purple-700" : "text-fuchsia-400"} font-bold font-mono`}>
            {gtStr}
          </span>
        );
      }
      return (
        <span className={`${isLight ? "text-cyan-700" : "text-cyan-400"} font-bold font-mono`}>
          {gtStr}
        </span>
      );
    }

    if (formatTag === "DP") {
      const dpVal = Number(val);
      if (dpVal === 0) return <span className={isLight ? "text-slate-400" : "text-slate-600"}>0</span>;
      const color =
        dpVal < 10
          ? isLight ? "text-rose-700 font-semibold" : "text-rose-400"
          : dpVal > 50
          ? isLight ? "text-emerald-700 font-bold" : "text-emerald-300 font-bold"
          : isLight ? "text-slate-800" : "text-slate-200";
      return <span className={`${color} font-mono`}>{dpVal}</span>;
    }

    if (formatTag === "AD") {
      return (
        <span className={`${isLight ? "text-amber-800" : "text-amber-300"} font-mono text-[10px]`}>
          {String(val)}
        </span>
      );
    }

    if (formatTag === "GQ") {
      const gqVal = Number(val);
      const color =
        gqVal < 30
          ? isLight ? "text-rose-700" : "text-rose-400"
          : gqVal >= 99
          ? isLight ? "text-emerald-700 font-bold" : "text-emerald-400 font-bold"
          : isLight ? "text-slate-800" : "text-slate-200";
      return <span className={`${color} font-mono`}>{gqVal}</span>;
    }

    return <span className="font-mono">{String(val)}</span>;
  };

  return (
    <div className={`flex-1 flex overflow-hidden border-none ${isLight ? "bg-white" : "bg-[#0b0f17]"}`}>
      {/* 1. Left Fixed Variant Columns Pane */}
      <div
        id="fixed_table"
        ref={leftTableRef}
        onScroll={handleLeftScroll}
        onWheel={handleWheel}
        className={`flex-shrink-0 overflow-y-scroll overflow-x-auto border-none scrollbar-thin ${
          isLight
            ? "bg-white scrollbar-thumb-slate-300"
            : "bg-[#0b0f17] scrollbar-thumb-slate-700"
        }`}
        style={{
          width:
            viewMode === "raw"
              ? "560px"
              : viewMode === "compact"
              ? "270px"
              : viewMode === "essential"
              ? "170px"
              : "420px",
        }}
      >
        <table className="min-w-full w-max text-left border-collapse border-none text-xs font-mono">
          <thead
            className={`sticky top-0 z-10 border-b shadow-xs h-8 min-h-[32px] max-h-[32px] ${
              isLight
                ? "bg-[#e2e8f0] text-slate-700 border-[#cbd5e1]"
                : "bg-[#1e293b] text-slate-300 border-slate-700"
            }`}
          >
            <tr className="h-8">
              {fixedCols.map((col) => (
                <th key={col} className="px-2 py-1 whitespace-nowrap font-bold border-none">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {topPadHeight > 0 && (
              <tr style={{ height: `${topPadHeight}px` }}>
                <td colSpan={fixedCols.length} />
              </tr>
            )}
            {visibleVariants.map((v, localIdx) => {
              const vIdx = startIndex + localIdx;
              const isRowSelected = selectedVariantIndex === vIdx;
              const isEven = vIdx % 2 === 0;
              const rowBg = isRowSelected
                ? isLight
                  ? "bg-blue-100/90 text-blue-950 font-semibold"
                  : "bg-[#1d4ed8]/30 font-semibold"
                : isEven
                ? isLight
                  ? "bg-white"
                  : "bg-[#0b0f17]"
                : isLight
                ? "bg-[#f8fafc]"
                : "bg-[#111827]";

              const chromShort = v.chrom.replace("Pf3D7_", "").replace("_v3", "");

              return (
                <tr
                  key={v.id || `var_${vIdx}`}
                  onClick={() => onSelectCell(vIdx, selectedSampleIndex)}
                  className={`${rowBg} ${
                    isLight ? "hover:bg-blue-50/70" : "hover:bg-slate-800/60"
                  } cursor-pointer transition-colors border-none h-7 min-h-[28px] max-h-[28px] overflow-hidden`}
                >
                  {viewMode === "raw" ? (
                    <>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[80px] ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                        {v.chrom}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-medium ${isLight ? "text-slate-900" : "text-white"}`}>
                        {v.pos.toLocaleString()}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap ${isLight ? "text-cyan-700 font-bold" : "text-cyan-400"}`}>
                        {v.varId}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[50px] ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                        {v.ref}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[60px] font-bold ${isLight ? "text-cyan-700" : "text-cyan-300"}`}>
                        {v.alt.join(",")}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-medium ${isLight ? "text-emerald-700" : "text-emerald-400"}`}>
                        {v.qual}
                      </td>
                      <td className="px-2 py-1 whitespace-nowrap">
                        <span className={v.filter === "PASS" ? isLight ? "text-emerald-700 font-bold" : "text-emerald-400 font-bold" : isLight ? "text-rose-700 font-bold" : "text-rose-400 font-bold"}>
                          {v.filter}
                        </span>
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap max-w-[130px] truncate ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                        {`GENE=${v.gene};MUT=${v.mutation}`}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap ${isLight ? "text-slate-500" : "text-slate-500"}`}>
                        {v.formatKeys.join(":")}
                      </td>
                    </>
                  ) : viewMode === "compact" ? (
                    <>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[80px] ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                        {chromShort}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-medium ${isLight ? "text-slate-900" : "text-white"}`}>
                        {v.pos.toLocaleString()}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[60px] ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                        {v.ref}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-bold truncate max-w-[70px] ${isLight ? "text-cyan-700" : "text-cyan-300"}`}>
                        {v.alt.join(",")}
                      </td>
                    </>
                  ) : viewMode === "essential" ? (
                    <>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[80px] ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                        {chromShort}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-medium ${isLight ? "text-slate-900" : "text-white"}`}>
                        {v.pos.toLocaleString()}
                      </td>
                    </>
                  ) : (
                    // Normal mode
                    <>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[80px] ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                        {chromShort}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-medium ${isLight ? "text-slate-900" : "text-white"}`}>
                        {v.pos.toLocaleString()}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap truncate max-w-[60px] ${isLight ? "text-slate-700" : "text-slate-300"}`}>
                        {v.ref}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-bold truncate max-w-[70px] ${isLight ? "text-cyan-700" : "text-cyan-300"}`}>
                        {v.alt.join(",")}
                      </td>
                      <td className={`px-2 py-1 whitespace-nowrap font-medium ${isLight ? "text-emerald-700" : "text-emerald-400"}`}>
                        {v.qual}
                      </td>
                      <td className="px-2 py-1 whitespace-nowrap">
                        <span className={v.filter === "PASS" ? isLight ? "text-emerald-700 font-bold" : "text-emerald-400" : isLight ? "text-rose-700 font-bold" : "text-rose-400"}>
                          {v.filter}
                        </span>
                      </td>
                      <td className="px-2 py-1 whitespace-nowrap">
                        <span className={`font-semibold ${v.drug ? isLight ? "text-amber-800 font-bold" : "text-amber-400" : isLight ? "text-slate-800" : "text-slate-300"}`}>
                          {v.gene}
                        </span>
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
            {bottomPadHeight > 0 && (
              <tr style={{ height: `${bottomPadHeight}px` }}>
                <td colSpan={fixedCols.length} />
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 2. Visual Vertical Split Divider */}
      <div
        className={`w-[3px] flex-shrink-0 cursor-col-resize hover:bg-cyan-500/50 transition-colors ${
          isLight ? "bg-[#cbd5e1]" : "bg-[#1e293b]"
        }`}
        title="Fixed Variant Columns │ Horizontally Scrollable Sample Matrix"
      />

      {/* 3. Right Horizontally Scrollable Sample Matrix Pane (Synchronized vertical scroll) */}
      <div
        ref={rightTableRef}
        onScroll={handleRightScroll}
        onWheel={handleWheel}
        className={`flex-1 overflow-auto scrollbar-thin ${
          isLight
            ? "scrollbar-thumb-slate-300 scrollbar-track-transparent bg-white"
            : "scrollbar-thumb-slate-700 scrollbar-track-transparent bg-[#0b0f17]"
        }`}
      >
        <table className="text-left border-collapse border-none text-xs font-mono table-fixed">
          <thead
            className={`sticky top-0 z-10 border-b shadow-xs h-8 min-h-[32px] max-h-[32px] ${
              isLight
                ? "bg-[#e2e8f0] text-slate-700 border-[#cbd5e1]"
                : "bg-[#1e293b] text-slate-300 border-slate-700"
            }`}
          >
            <tr className="h-8">
              {samples.map((s, sIdx) => {
                const isSampleSelected = selectedSampleIndex === sIdx;
                return (
                  <th
                    key={s}
                    onClick={() => onSelectCell(selectedVariantIndex, sIdx)}
                    className={`px-3 py-1 text-right whitespace-nowrap cursor-pointer transition-colors border-none min-w-[66px] w-[66px] ${
                      isSampleSelected
                        ? isLight
                          ? "text-blue-900 bg-blue-100 font-bold"
                          : "text-cyan-300 bg-slate-800 font-bold"
                        : isLight
                        ? "text-slate-700 hover:text-slate-900"
                        : "text-slate-200 hover:text-white"
                    }`}
                  >
                    {s}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {topPadHeight > 0 && (
              <tr style={{ height: `${topPadHeight}px` }}>
                <td colSpan={samples.length} />
              </tr>
            )}
            {visibleVariants.map((v, localIdx) => {
              const vIdx = startIndex + localIdx;
              const isRowSelected = selectedVariantIndex === vIdx;
              const isEven = vIdx % 2 === 0;
              const rowBg = isRowSelected
                ? isLight
                  ? "bg-blue-100/90"
                  : "bg-[#1d4ed8]/30"
                : isEven
                ? isLight
                  ? "bg-white"
                  : "bg-[#0b0f17]"
                : isLight
                ? "bg-[#f8fafc]"
                : "bg-[#111827]";

              return (
                <tr
                  key={v.id || `srow_${vIdx}`}
                  className={`${rowBg} ${
                    isLight ? "hover:bg-blue-50/70" : "hover:bg-slate-800/60"
                  } transition-colors border-none h-7 min-h-[28px] max-h-[28px] overflow-hidden`}
                >
                  {samples.map((s, sIdx) => {
                    const isCellActive = isRowSelected && selectedSampleIndex === sIdx;
                    return (
                      <td
                        key={s}
                        onClick={() => onSelectCell(vIdx, sIdx)}
                        className={`px-3 py-1 text-right whitespace-nowrap cursor-pointer border-none min-w-[66px] w-[66px] transition-colors ${
                          isCellActive
                            ? isLight
                              ? "bg-blue-600 text-white font-bold ring-2 ring-blue-500 z-10"
                              : "bg-[#1d4ed8] text-white font-bold ring-2 ring-cyan-400 z-10"
                            : isLight
                            ? "hover:bg-slate-200/50"
                            : "hover:bg-slate-700/40"
                        }`}
                      >
                        {renderSampleValue(v, s)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {bottomPadHeight > 0 && (
              <tr style={{ height: `${bottomPadHeight}px` }}>
                <td colSpan={samples.length} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
