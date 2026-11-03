"""
FooterBar Widget for VCFscape - VCF inspector part of vivaxGEN Project.
Compact bottom bar displaying hotkey reference and live operation/selection log.
"""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text


class FooterBar(Widget):
    """Footer bar displaying keybindings guide and operational log."""

    DEFAULT_CSS = """
    FooterBar {
        height: 2;
        dock: bottom;
        background: #090d14;
        color: #94a3b8;
    }
    """

    log_message = reactive("Ready. Use Arrow keys to navigate cells.")

    def set_log(self, message: str) -> None:
        """Update live operational message in footer bar."""
        self.log_message = message

    def render(self) -> Text:
        """Render hotkeys bar and live log message."""
        text = Text()

        # Row 1: Keybindings
        text.append(" [1] ", style="bold bright_cyan")
        text.append("GT ", style="white")
        text.append("[2] ", style="bold bright_cyan")
        text.append("DP ", style="white")
        text.append("[3] ", style="bold bright_cyan")
        text.append("AD ", style="white")
        text.append("[4] ", style="bold bright_cyan")
        text.append("GQ ", style="white")
        text.append("│ ", style="bright_black")
        text.append("[v] ", style="bold yellow")
        text.append("View ", style="white")
        text.append("[s] ", style="bold yellow")
        text.append("Split ", style="white")
        text.append("[+/-] ", style="bold yellow")
        text.append("Resize ", style="white")
        text.append("[c] ", style="bold yellow")
        text.append("Cohorts ", style="white")
        text.append("[f] ", style="bold yellow")
        text.append("Filter ", style="white")
        text.append("[t] ", style="bold yellow")
        text.append("Theme ", style="white")
        text.append("[?] ", style="bold yellow")
        text.append("Help ", style="white")
        text.append("[q] ", style="bold red")
        text.append("Quit", style="white")
        text.append("\n")

        # Row 2: Live status log
        text.append(" LOG ", style="bold black on bright_yellow")
        text.append(f" {self.log_message}", style="bold white")

        return text
