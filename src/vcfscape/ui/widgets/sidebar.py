"""
Right Sidebar Container Widget for Malaria VCF TUI.
Ultra-compact, space-saving sidebar displaying:
1. VariantSummary (locus, gene, impact, drug resistance)
2. CohortListWidget (active cohorts & filter)
3. CellInspector (active sample genotype, depth, and allelic depths)
Rendered cleanly without bulky borders to fit entirely on-screen without vertical scrolling.
"""

from typing import Optional, Dict, Any
from textual.widget import Widget
from textual.containers import Container
from rich.text import Text
from vcfscape.core.cohorts import CohortManager
from vcfscape.core.vcf_reader import VariantRecord
from vcfscape.ui.widgets.variant_summary import VariantSummary


class CellInspector(Widget):
    """Compact window displaying all FORMAT values for the focused sample cell."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sample_id: Optional[str] = None
        self.sample_fields: Dict[str, Any] = {}

    def update_cell(self, sample_id: Optional[str], sample_fields: Dict[str, Any]):
        self.sample_id = sample_id
        self.sample_fields = sample_fields
        self.refresh()

    def render(self) -> Text:
        text = Text()
        if not self.sample_id:
            text.append(" CELL INSPECTOR ", style="bold black on bright_yellow")
            text.append(" (Select cell to inspect)", style="dim italic")
            return text

        text.append(" CELL INSPECTOR ", style="bold black on bright_yellow")
        text.append(f" [{self.sample_id}]\n", style="bold white")

        gt = str(self.sample_fields.get("GT", "./."))
        gt_desc = ""
        if "/" in gt:
            parts = gt.split("/")
            if len(set(parts)) > 1:
                gt_desc = "(Het)"
            elif "0" in parts:
                gt_desc = "(HomRef)"
            else:
                gt_desc = "(HomAlt)"

        dp = str(self.sample_fields.get("DP", "."))
        gq = str(self.sample_fields.get("GQ", "."))
        ad = str(self.sample_fields.get("AD", "."))

        text.append("GT: ", style="dim")
        gt_style = "bold magenta" if "Het" in gt_desc else ("bold cyan" if "Alt" in gt_desc else "dim white")
        text.append(f"{gt} {gt_desc}  ", style=gt_style)
        text.append("DP: ", style="dim")
        text.append(f"{dp}x  ", style="bold green")
        text.append("GQ: ", style="dim")
        text.append(f"{gq}\n", style="white")

        text.append("AD: ", style="dim")
        text.append(f"{ad} [REF, ALT1...]", style="bright_yellow")

        return text


class CohortListWidget(Widget):
    """Compact view of active sample cohorts and real-time filter."""

    def __init__(self, cohort_manager: CohortManager, **kwargs):
        super().__init__(**kwargs)
        self.cohort_manager = cohort_manager
        self.active_filter = "ALL"

    def set_filter(self, filter_name: str):
        self.active_filter = filter_name
        self.refresh()

    def on_click(self) -> None:
        if hasattr(self.app, "action_open_cohort_manager"):
            self.app.action_open_cohort_manager()

    def render(self) -> Text:
        text = Text()
        text.append(" COHORTS & FILTERS ", style="bold black on bright_magenta")
        text.append(" [c=manage/define, f=filter]\n", style="dim")

        # Display active cohorts compactly: 2 per line
        items = list(self.cohort_manager.cohorts.items())
        line_items = []
        for name, c in items:
            check = "[x]" if c.active else "[ ]"
            color = "green" if c.active else "dim"
            short_name = name.replace("Cohort ", "").replace(" Samples", "")
            line_items.append((check, short_name, len(c.sample_ids), color))

        for i in range(0, len(line_items), 2):
            for j in range(i, min(i + 2, len(line_items))):
                chk, sname, count, col = line_items[j]
                text.append(f"{chk} ", style="bold " + col)
                text.append(f"{sname} ", style=col)
                text.append(f"(n={count}) ", style="dim")
            text.append("\n")

        # Real-time Filter Buttons matching web simulator
        text.append("Filter: ", style="dim")
        for f in ["ALL", "DRUG_RESISTANT", "INDEL", "SNP"]:
            short_f = f.replace("_RESISTANT", "").replace("DRUG", "DRUG_RES")
            if self.active_filter == f:
                text.append(f"[{short_f}] ", style="bold black on bright_cyan")
            else:
                text.append(f" {short_f}  ", style="dim")

        return text


class SidebarPanel(Container):
    """Right sidebar panel containing Variant Summary, Cohort List, and Cell Inspector."""

    def __init__(self, cohort_manager: CohortManager, **kwargs):
        super().__init__(**kwargs)
        self.cohort_manager = cohort_manager
        self.variant_summary = VariantSummary()
        self.cohort_widget = CohortListWidget(cohort_manager)
        self.cell_inspector = CellInspector()

    def compose(self):
        yield self.variant_summary
        yield self.cohort_widget
        yield self.cell_inspector

    def update_selection(self, record: VariantRecord, sample_id: Optional[str] = None):
        self.variant_summary.update_record(record)
        if sample_id:
            s_data = record.sample_data.get(sample_id, {})
            self.cell_inspector.update_cell(sample_id, s_data)
        else:
            self.cell_inspector.update_cell(None, {})
