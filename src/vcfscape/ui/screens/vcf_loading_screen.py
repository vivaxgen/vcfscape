"""
Centered modal popup dialog for VCF file loading, index scanning, and record counting.
Gives users an active visual cue with an animated spinner, filename, and live variant count progress.
"""

from __future__ import annotations
from typing import Optional
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Button
from textual.binding import Binding
from rich.text import Text


SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class AnimatedSpinner(Static):
    """Smooth terminal braille spinner widget."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._frame_idx = 0
        self._timer = None

    def on_mount(self) -> None:
        self.update_spinner()
        self._timer = self.set_interval(0.08, self.update_spinner)

    def update_spinner(self) -> None:
        frame = SPINNER_FRAMES[self._frame_idx % len(SPINNER_FRAMES)]
        self._frame_idx += 1
        self.update(Text(f" {frame} ", style="bold cyan"))


class VcfLoadingScreen(ModalScreen[Optional[int]]):
    """Centered modal popup dialog indicating VCF file reading and counting in progress."""

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Dismiss", show=False),
        Binding("enter", "dismiss_screen", "Dismiss", show=False),
        Binding("space", "dismiss_screen", "Dismiss", show=False),
    ]

    DEFAULT_CSS = """
    VcfLoadingScreen {
        align: center middle;
        background: rgba(11, 15, 23, 0.85);
    }

    #loading_dialog {
        width: 64;
        height: auto;
        border: solid #0284c7;
        background: #161e2e;
        padding: 1 2;
    }

    #loading_header {
        text-style: bold;
        color: #38bdf8;
        margin-bottom: 1;
        content-align: center middle;
        width: 100%;
    }

    #file_label {
        color: #f8fafc;
        text-style: bold;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }

    #spinner_container {
        height: 3;
        align: center middle;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }

    #progress_label {
        color: #38bdf8;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }

    #hint_label {
        color: #94a3b8;
        font-size: 80%;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }

    #btn_container {
        height: 3;
        align: center middle;
        width: 100%;
        margin-top: 1;
    }

    #btn_dismiss {
        min-width: 28;
    }
    """

    def __init__(self, filename: str, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.is_completed = False
        self._current_count: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="loading_dialog"):
            yield Static("Reading VCF File", id="loading_header")
            yield Static(f"File: {self.filename}", id="file_label")
            with Horizontal(id="spinner_container"):
                yield AnimatedSpinner(id="loading_spinner")
                yield Static(Text("Scanning index & parsing records...", style="italic bright_white"), id="status_text")
            yield Static("Preparing initial variant slice...", id="progress_label")
            yield Static("Please wait while records are indexed...", id="hint_label")
            with Horizontal(id="btn_container"):
                yield Button("Continue in Background (Esc)", id="btn_dismiss", variant="primary")

    def update_progress(self, count: int) -> None:
        """Called periodically as records are scanned in the background."""
        self._current_count = count
        try:
            lbl = self.query_one("#progress_label", Static)
            lbl.update(Text(f"Variants scanned: {count:,}", style="bold cyan"))
        except Exception:
            pass

    def mark_complete(self, total: int) -> None:
        """Called when reading and background counting finishes."""
        self.is_completed = True
        self._current_count = total
        try:
            lbl = self.query_one("#progress_label", Static)
            lbl.update(Text(f"Completed! Total variants: {total:,}", style="bold green"))
            status = self.query_one("#status_text", Static)
            status.update(Text("Index and records ready", style="bold green"))
        except Exception:
            pass
        # Auto-dismiss modal
        try:
            self.dismiss(total)
        except Exception:
            pass

    def action_dismiss_screen(self) -> None:
        try:
            self.dismiss(self._current_count)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_dismiss":
            self.action_dismiss_screen()
