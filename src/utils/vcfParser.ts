/**
 * Client-side VCF parser for Malaria VCF Inspector Web Simulator.
 * Supports direct file loading (.vcf and .vcf.gz) with malaria marker annotation.
 */

import { Variant, Cohort } from "../types/vcf";

export interface ParsedVcfResult {
  filename: string;
  totalVariants: number;
  totalSamples: number;
  samples: string[];
  cohorts: Cohort[];
  variants: Variant[];
}

const KNOWN_DRUG_MARKERS: Record<string, { gene: string; mutation: string; drug: string; status: string; details: string }> = {
  "Pf3D7_07_v3:403625": { gene: "pfcrt", mutation: "K76T", drug: "Chloroquine", status: "Validated Resistance", details: "Diagnostic marker for CQ treatment failure" },
  "Pf3D7_13_v3:1725256": { gene: "pfk13", mutation: "C580Y", drug: "Artemisinin", status: "WHO Validated", details: "Major artemisinin partial resistance marker" },
  "Pf3D7_13_v3:1725287": { gene: "pfk13", mutation: "R539T", drug: "Artemisinin", status: "WHO Validated", details: "Associated with delayed parasite clearance" },
  "Pf3D7_13_v3:1725301": { gene: "pfk13", mutation: "Y493H", drug: "Artemisinin", status: "WHO Validated", details: "Candidate artemisinin resistance marker" },
  "Pf3D7_05_v3:958145": { gene: "pfmdr1", mutation: "N86Y", drug: "Amodiaquine / AL", status: "Validated Modulation", details: "Alters sensitivity to lumefantrine & amodiaquine" },
  "Pf3D7_05_v3:958444": { gene: "pfmdr1", mutation: "Y184F", drug: "Lumefantrine", status: "Candidate Marker", details: "Common in sub-Saharan Africa" },
  "Pf3D7_04_v3:748239": { gene: "pfdhfr", mutation: "S108N", drug: "Pyrimethamine", status: "Validated Resistance", details: "Key antifolate resistance mutation" },
  "Pf3D7_08_v3:549681": { gene: "pfdhps", mutation: "A437G", drug: "Sulfadoxine", status: "Validated Resistance", details: "Sulfadoxine-pyrimethamine resistance marker" },
};

export function parseVcfText(content: string, filename: string): ParsedVcfResult {
  const lines = content.split(/\r?\n/);
  let samples: string[] = [];
  const variants: Variant[] = [];

  for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
    const line = lines[lineIdx].trim();
    if (!line) continue;

    if (line.startsWith("#CHROM")) {
      const parts = line.split("\t");
      samples = parts.slice(9).map((s) => s.trim());
      continue;
    }

    if (line.startsWith("#")) continue;

    const cols = line.split("\t");
    if (cols.length < 8) continue;

    const chrom = cols[0];
    const pos = parseInt(cols[1], 10);
    const varId = cols[2] !== "." ? cols[2] : ".";
    const ref = cols[3];
    const alt = cols[4].split(",").map((a) => a.trim());
    const qual = cols[5] !== "." ? parseFloat(cols[5]) : 0;
    const filter = cols[6];
    const infoRaw = cols[7];
    const formatKeys = cols.length > 8 ? cols[8].split(":") : ["GT"];

    // Parse INFO
    const info: Record<string, string> = {};
    if (infoRaw !== ".") {
      infoRaw.split(";").forEach((part) => {
        const [k, v] = part.split("=");
        if (k) info[k] = v || "true";
      });
    }

    // Determine variant type
    const isMulti = alt.length > 1;
    const isIndel = ref.length !== 1 || alt.some((a) => a.length !== 1);
    let varType: Variant["varType"] = "SNP";
    if (isMulti && isIndel) varType = "Multi-Allelic INDEL";
    else if (isMulti) varType = "Multi-Allelic SNP";
    else if (isIndel) varType = "INDEL";

    // Known drug marker lookup
    const locusKey = `${chrom}:${pos}`;
    const marker = KNOWN_DRUG_MARKERS[locusKey];

    const gene = info.GENE || (marker ? marker.gene : ".");
    const impact = info.IMPACT || (marker ? "Missense / Resistance" : "Intergenic");
    const mutation = info.MUT || (marker ? marker.mutation : `${ref}${pos}${alt.join("/")}`);
    const drug = info.DRUG || (marker ? marker.drug : undefined);
    const drugStatus = marker ? marker.status : undefined;
    const drugDetails = marker ? marker.details : undefined;

    // Parse sample genotype cells
    const sampleCells: Variant["samples"] = {};
    samples.forEach((sampleName, sIdx) => {
      const colVal = cols[9 + sIdx] || "./.";
      const subVals = colVal.split(":");
      const sMap: Record<string, string> = {};
      formatKeys.forEach((fk, fkIdx) => {
        sMap[fk] = subVals[fkIdx] || ".";
      });

      const gt = sMap.GT || "./.";
      const dp = parseInt(sMap.DP || "0", 10) || 0;
      const ad = sMap.AD || ".";
      const gq = parseInt(sMap.GQ || "0", 10) || 0;
      const pl = sMap.PL || undefined;

      sampleCells[sampleName] = { GT: gt, DP: dp, AD: ad, GQ: gq, PL: pl };
    });

    variants.push({
      id: `var_${variants.length}_${chrom}_${pos}`,
      chrom,
      pos,
      varId,
      ref,
      alt,
      qual: isNaN(qual) ? 0 : qual,
      filter: filter || "PASS",
      gene,
      impact,
      mutation,
      drug,
      drugStatus,
      drugDetails,
      varType,
      info,
      formatKeys,
      samples: sampleCells,
    });
  }

  // Default cohorts: only All Samples baseline (no automatic initial cohorts)
  const cohorts: Cohort[] = [
    {
      name: "All Samples",
      sampleIds: [...samples],
      description: `All ${samples.length} isolates in VCF`,
      active: true,
      color: "#10b981",
    },
  ];

  return {
    filename,
    totalVariants: variants.length,
    totalSamples: samples.length,
    samples,
    cohorts,
    variants,
  };
}

export async function readVcfFile(file: File): Promise<ParsedVcfResult> {
  let text = "";
  if (file.name.endsWith(".gz")) {
    if (typeof DecompressionStream !== "undefined") {
      const ds = new DecompressionStream("gzip");
      const decompressedStream = file.stream().pipeThrough(ds);
      const resp = new Response(decompressedStream);
      text = await resp.text();
    } else {
      throw new Error("Gzip decompression not supported in this browser environment.");
    }
  } else {
    text = await file.text();
  }

  return parseVcfText(text, file.name);
}
