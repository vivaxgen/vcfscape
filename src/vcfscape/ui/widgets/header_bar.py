"""
HeaderBar Widget for VCFscape - VCF inspector part of vivaxGEN Project.
Compact, single-line borderless header displaying essential metadata.
"""

from typing import Optional
from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text

class HeaderBar(Widget):
    """Header bar rendering filename, genome, counts, view mode, and format tag."""

    filename = reactive("")
    total_variants = reactive(None)
    total_samples = reactive(0)
    view_mode = reactive("Normal")
    format_tag = reactive("GT")
    active_cohorts = reactive(1)
    backend = reactive("cyvcf2")

    def __init__(
        self,
        filename: str = "",
        total_variants: Optional[int] = None,
        total_samples: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.filename = filename
        self.total_variants = total_variants
        self.total_samples = total_samples

    def render(self) -> Text:
        text = Text()
        text.append(" VCFSCAPE ", style="bold black on bright_cyan")
        text.append(" ")
        text.append(f"{self.filename}", style="bold white")
        text.append(" │ ", style="bright_black")
        text.append("Genome: ", style="dim")
        text.append("Pf3D7_v3", style="bold yellow")
        text.append(" │ ", style="bright_black")
        text.append("Vars: ", style="dim")
        if isinstance(self.total_variants, int) and self.total_variants > 0:
            text.append(f"{self.total_variants:,}", style="bold green")
        elif self.total_variants == 0:
            text.append("0", style="bold green")
        else:
            text.append("Counting...", style="italic bright_cyan")
        text.append(" │ ", style="bright_black")
        text.append("Samples: ", style="dim")
        text.append(f"{self.total_samples:,}", style="bold green")
        text.append(" │ ", style="bright_black")
        text.append("View: ", style="dim")
        text.append(f"[{self.view_mode}]", style="bold magenta")
        text.append(" │ ", style="bright_black")
        text.append("Tag: ", style="dim")
        text.append(f"[{self.format_tag}]", style="bold cyan")
        text.append(" │ ", style="bright_black")
        text.append(f"{self.backend}", style="dim")
        return text
