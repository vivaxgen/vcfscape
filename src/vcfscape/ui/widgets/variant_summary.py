"""
Variant Summary Widget for Malaria VCF TUI.
Ultra-compact panel displaying locus, gene annotation, mutation impact,
variant classification, quality metrics, and WHO drug resistance status
without wasted vertical space or borders.
"""

from typing import Optional
from textual.widget import Widget
from rich.text import Text
from vcfscape.core.vcf_reader import VariantRecord


class VariantSummary(Widget):
    """Displays molecular and resistance epidemiology compactly without borders."""

    DEFAULT_CSS = """
    VariantSummary {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.record: Optional[VariantRecord] = None

    def update_record(self, record: VariantRecord):
        self.record = record
        self.refresh()

    def render(self) -> Text:
        if not self.record:
            return Text(" VARIANT SUMMARY  (No variant selected)", style="dim italic")

        r = self.record
        text = Text()

        # 1. Header line
        text.append(" VARIANT SUMMARY ", style="bold black on bright_cyan")
        filter_style = "bold green" if r.filter == "PASS" else "bold red"
        text.append(f" [{r.filter}]\n", style=filter_style)

        # 2. Locus, ID & Type
        chrom_short = r.chrom.replace("Pf3D7_", "Pf").replace("_v3", "")
        qual_str = f"{r.qual:.0f}" if r.qual is not None else "."
        text.append("Locus: ", style="dim")
        text.append(f"{chrom_short}:{r.pos:,} ", style="bold white")
        text.append(f"Q:{qual_str}\n", style="bright_green")

        # 3. Gene, Mutation & Impact
        text.append("Gene:  ", style="dim")
        gene_style = "bold yellow" if r.drug_annotation else "bold white"
        text.append(f"{r.gene} ", style=gene_style)
        text.append(f"{r.mutation} ", style="bold magenta")
        text.append(f"({r.impact})\n", style="bright_magenta")

        # 4. Allele breakdown & Classification
        text.append("Var:   ", style="dim")
        text.append(f"{r.ref}->{','.join(r.alt)} ", style="white")
        text.append(f"({r.var_type})\n", style="bold bright_yellow" if "Multi" in r.var_type else "dim")

        # 5. Antimalarial Drug Resistance Surveillance Status
        if r.drug_annotation:
            ann = r.drug_annotation
            text.append("Drug:  ", style="bold red")
            text.append(f"{ann.drug} ", style="bold red")
            text.append(f"[{ann.status}]\n", style="bold yellow")
            details = ann.details[:30] + "..." if len(ann.details) > 30 else ann.details
            text.append(f"       {details}", style="italic white")
        else:
            text.append("Drug:  None (Surveillance locus)", style="dim")

        return text
