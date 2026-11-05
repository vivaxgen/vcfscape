"""
Cohort definition and real-time population genetics statistical computations.
Decomposes multi-allelic sites, computes cohort-stratified allele frequencies,
depth metrics, missingness, and polygenomic (MOI) rates.
"""

from typing import Dict, List, Optional, Set, Any
import statistics

class CohortStats:
    """Detailed summary statistics for a variant within a sample cohort."""
    def __init__(self, cohort_name: str, total_samples: int):
        self.cohort_name: str = cohort_name
        self.total_samples: int = total_samples
        self.called_samples: int = 0
        self.missing_samples: int = 0
        self.missingness_rate: float = 0.0

        # Allele counts & frequencies: 0 is REF, 1+ are ALTs
        self.an: int = 0  # Total allele count
        self.allele_counts: Dict[int, int] = {}
        self.allele_frequencies: Dict[int, float] = {}

        # Read depth metrics
        self.mean_depth: float = 0.0
        self.median_depth: float = 0.0
        self.min_depth: int = 0
        self.max_depth: int = 0

        # Malaria polygenomic / complexity of infection (heterozygosity)
        self.polygenomic_samples: int = 0
        self.polygenomic_rate: float = 0.0

        # Genotype counts
        self.hom_ref: int = 0
        self.het_or_poly: int = 0
        self.hom_alt: int = 0
        self.missing_gt: int = 0

COHORT_COLORS = [
    "#10b981",  # emerald
    "#3b82f6",  # blue
    "#a855f7",  # purple
    "#f59e0b",  # amber
    "#ec4899",  # pink
    "#06b6d4",  # cyan
    "#84cc16",  # lime
    "#f97316",  # orange
]


class Cohort:
    """A designated subset of samples (e.g. Clinical vs Asymptomatic, or Geographic region)."""
    def __init__(self, name: str, sample_ids: List[str], description: str = "", color: str = "#3b82f6", active: bool = True):
        self.name: str = name
        self.sample_ids: List[str] = list(sample_ids)
        self.sample_set: Set[str] = set(sample_ids)
        self.description: str = description
        self.color: str = color
        self.active: bool = active

    def contains(self, sample_id: str) -> bool:
        return sample_id in self.sample_set


class CohortManager:
    """Manages cohorts and computes on-the-fly multi-allelic population metrics."""

    def __init__(self, all_samples: List[str], auto_detect: bool = False):
        self.all_samples: List[str] = list(all_samples)
        self.cohorts: Dict[str, Cohort] = {}
        self._init_default_cohorts(auto_detect=auto_detect)

    def _init_default_cohorts(self, auto_detect: bool = False):
        """Initializes baseline All Samples cohort. Does not perform automatic initial cohorts by default."""
        # Always have All Samples baseline cohort
        self.cohorts["All Samples"] = Cohort(
            "All Samples",
            list(self.all_samples),
            "All isolates in VCF",
            color="#10b981",
            active=True
        )

        if not auto_detect:
            return

        # Detect prefixes only if explicitly requested
        prefix_groups: Dict[str, List[str]] = {}
        for s in self.all_samples:
            prefix = s.split("_")[0] if "_" in s else (s[:2] if len(s) >= 4 else "Other")
            prefix_groups.setdefault(prefix, []).append(s)

        color_idx = 1
        if len(prefix_groups) > 1:
            for prefix, s_list in prefix_groups.items():
                if len(s_list) >= 2:
                    name = f"Cohort {prefix}"
                    desc = f"Samples with prefix {prefix} (n={len(s_list)})"
                    c_color = COHORT_COLORS[color_idx % len(COHORT_COLORS)]
                    color_idx += 1
                    self.cohorts[name] = Cohort(name, s_list, desc, color=c_color, active=True)
        else:
            # Fallback split 50/50
            mid = len(self.all_samples) // 2
            if mid > 0:
                self.cohorts["Cohort 1"] = Cohort("Cohort 1", self.all_samples[:mid], "First group", color="#3b82f6", active=True)
                self.cohorts["Cohort 2"] = Cohort("Cohort 2", self.all_samples[mid:], "Second group", color="#a855f7", active=True)

    def add_cohort(self, name: str, sample_ids: List[str], description: str = "", color: str = "", active: bool = True) -> Cohort:
        if not color:
            color = COHORT_COLORS[len(self.cohorts) % len(COHORT_COLORS)]
        # Filter samples to only those valid
        valid_samples = [s for s in sample_ids if s in self.all_samples]
        cohort = Cohort(name, valid_samples, description, color=color, active=active)
        self.cohorts[name] = cohort
        return cohort

    def update_cohort(
        self,
        old_name: str,
        new_name: Optional[str] = None,
        sample_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Cohort:
        if old_name not in self.cohorts:
            raise KeyError(f"Cohort '{old_name}' not found.")
        cohort = self.cohorts[old_name]

        if sample_ids is not None:
            valid_samples = [s for s in sample_ids if s in self.all_samples]
            cohort.sample_ids = valid_samples
            cohort.sample_set = set(valid_samples)

        if description is not None:
            cohort.description = description

        if color is not None:
            cohort.color = color

        target_name = old_name
        if new_name and new_name != old_name:
            if new_name in self.cohorts and new_name != old_name:
                raise ValueError(f"Cohort '{new_name}' already exists.")
            del self.cohorts[old_name]
            cohort.name = new_name
            self.cohorts[new_name] = cohort
            target_name = new_name

        return self.cohorts[target_name]

    def delete_cohort(self, name: str) -> bool:
        if name == "All Samples":
            return False
        if name in self.cohorts:
            del self.cohorts[name]
            return True
        return False

    def clone_cohort(self, source_name: str, new_name: Optional[str] = None, new_color: Optional[str] = None) -> Cohort:
        if source_name not in self.cohorts:
            raise KeyError(f"Source cohort '{source_name}' not found.")
        source = self.cohorts[source_name]

        if not new_name:
            base_name = f"{source.name} (Copy)"
            candidate = base_name
            counter = 2
            while candidate in self.cohorts:
                candidate = f"{source.name} (Copy {counter})"
                counter += 1
            new_name = candidate

        if not new_color:
            new_color = COHORT_COLORS[len(self.cohorts) % len(COHORT_COLORS)]

        return self.add_cohort(
            name=new_name,
            sample_ids=list(source.sample_ids),
            description=f"Cloned from {source.name}",
            color=new_color,
            active=True,
        )

    def invert_selection(self, selected_samples: List[str]) -> List[str]:
        """Invert selection: returns all dataset samples not currently in selected_samples."""
        selected_set = set(selected_samples)
        return [s for s in self.all_samples if s not in selected_set]

    def toggle_cohort(self, name: str) -> bool:
        if name in self.cohorts and name != "All Samples":
            self.cohorts[name].active = not self.cohorts[name].active
            return self.cohorts[name].active
        return True

    def calculate_variant_stats(self, variant_record: Dict[str, Any], num_alleles: int) -> Dict[str, CohortStats]:
        """
        Calculate metrics for all active cohorts given a variant record.
        variant_record expected to contain:
          - 'genotypes': {sample_id: (a1, a2) or (a1,)}
          - 'depths': {sample_id: int}
          - 'ad': {sample_id: [ref_ad, alt1_ad, ...]}
        """
        results: Dict[str, CohortStats] = {}
        genotypes = variant_record.get("genotypes", {})
        depths = variant_record.get("depths", {})

        for name, cohort in self.cohorts.items():
            if not cohort.active:
                continue

            cohort_samples = [s for s in cohort.sample_ids if s in genotypes]
            c_stats = CohortStats(name, len(cohort.sample_ids))

            allele_counts: Dict[int, int] = {i: 0 for i in range(num_alleles)}
            total_an = 0
            dp_values: List[int] = []
            poly_count = 0
            called_count = 0
            missing_count = 0

            for s in cohort.sample_ids:
                gt = genotypes.get(s, None)
                dp = depths.get(s, 0)
                if dp is not None and dp > 0:
                    dp_values.append(dp)

                if gt is None or len(gt) == 0 or -1 in gt or None in gt:
                    missing_count += 1
                    c_stats.missing_gt += 1
                else:
                    called_count += 1
                    # Check unique alleles in sample for polygenomic infection
                    unique_alleles = set(gt)
                    if len(unique_alleles) > 1:
                        poly_count += 1
                        c_stats.het_or_poly += 1
                    elif 0 in unique_alleles:
                        c_stats.hom_ref += 1
                    else:
                        c_stats.hom_alt += 1

                    for allele in gt:
                        if allele >= 0:
                            total_an += 1
                            allele_counts[allele] = allele_counts.get(allele, 0) + 1

            c_stats.called_samples = called_count
            c_stats.missing_samples = missing_count
            c_stats.missingness_rate = (missing_count / c_stats.total_samples) if c_stats.total_samples > 0 else 0.0
            c_stats.an = total_an
            c_stats.allele_counts = allele_counts

            # Compute AF
            for i in range(num_alleles):
                c_stats.allele_frequencies[i] = (allele_counts.get(i, 0) / total_an) if total_an > 0 else 0.0

            # Depth
            if dp_values:
                c_stats.mean_depth = sum(dp_values) / len(dp_values)
                c_stats.median_depth = statistics.median(dp_values)
                c_stats.min_depth = min(dp_values)
                c_stats.max_depth = max(dp_values)
            else:
                c_stats.mean_depth = 0.0
                c_stats.median_depth = 0.0
                c_stats.min_depth = 0
                c_stats.max_depth = 0

            # Polygenomic / MOI rate
            c_stats.polygenomic_samples = poly_count
            c_stats.polygenomic_rate = (poly_count / called_count) if called_count > 0 else 0.0

            results[name] = c_stats

        return results
