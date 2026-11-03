export interface Variant {
  id: string;
  chrom: string;
  pos: number;
  varId: string;
  ref: string;
  alt: string[];
  qual: number;
  filter: string;
  gene: string;
  impact: string;
  mutation: string;
  drug?: string;
  drugStatus?: string;
  drugDetails?: string;
  varType: "SNP" | "INDEL" | "Multi-Allelic SNP" | "Multi-Allelic INDEL";
  info: Record<string, string>;
  formatKeys: string[];
  samples: Record<string, {
    GT: string;
    DP: number;
    AD: string;
    GQ: number;
    PL?: string;
  }>;
}

export type ViewMode = "normal" | "compact" | "essential" | "raw";
export type FormatTag = "GT" | "DP" | "AD" | "GQ";
export type ThemeMode = "dark" | "light";

export interface Cohort {
  name: string;
  sampleIds: string[];
  description: string;
  active: boolean;
  color?: string;
}

