"""
Modal screen for jumping to a specific genomic region, chromosome:position, or drug-resistance marker gene.
"""

from typing import Optional, Tuple
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, Input, Button


GENE_PRESETS = {
    "crt": ("Pf3D7_07_v3", 403000, "Chloroquine (pfcrt)"),
    "k13": ("Pf3D7_13_v3", 1725000, "Artemisinin (kelch13)"),
    "dhfr": ("Pf3D7_04_v3", 748000, "Pyrimethamine (dhfr)"),
    "mdr1": ("Pf3D7_05_v3", 958000, "MDR / Mefloquine (pfmdr1)"),
    "dhps": ("Pf3D7_08_v3", 549000, "Sulfadoxine (dhps)"),
}


class JumpRegionScreen(ModalScreen[Optional[Tuple[str, int]]]):
    """Modal dialog prompting user for genomic coordinates or gene to jump to."""

    DEFAULT_CSS = """
    JumpRegionScreen {
        align: center middle;
        background: rgba(11, 15, 23, 0.85);
    }

    #jump_dialog {
        width: 60;
        height: auto;
        border: solid #0284c7;
        background: #161e2e;
        padding: 1 2;
    }

    #jump_title {
        text-style: bold;
        color: #38bdf8;
        margin-bottom: 1;
    }

    #jump_hint {
        color: #94a3b8;
        text-style: italic;
        margin-bottom: 1;
    }

    .preset_row {
        height: 3;
        margin-top: 1;
        margin-bottom: 1;
    }

    .preset_btn {
        min-width: 10;
        margin-right: 1;
    }

    #action_row {
        height: 3;
        margin-top: 1;
        align-horizontal: right;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="jump_dialog"):
            yield Static("Genomic Coordinate / Gene Jumper", id="jump_title")
            yield Static(
                "Jump directly into big VCF files by chromosome:position or marker gene.",
                id="jump_hint",
            )
            yield Input(
                placeholder="e.g. Pf3D7_07_v3:403000 or 'crt'",
                id="locus_input",
            )
            with Horizontal(classes="preset_row"):
                yield Button("crt (Chr 7)", id="btn_crt", classes="preset_btn")
                yield Button("k13 (Chr 13)", id="btn_k13", classes="preset_btn")
                yield Button("mdr1 (Chr 5)", id="btn_mdr1", classes="preset_btn")
                yield Button("dhfr (Chr 4)", id="btn_dhfr", classes="preset_btn")
            with Horizontal(id="action_row"):
                yield Button("Cancel", id="btn_cancel", variant="default")
                yield Button("Jump", id="btn_jump", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn_cancel":
            self.dismiss(None)
            return

        if bid == "btn_crt":
            self.dismiss(("Pf3D7_07_v3", 403000))
            return
        if bid == "btn_k13":
            self.dismiss(("Pf3D7_13_v3", 1725000))
            return
        if bid == "btn_mdr1":
            self.dismiss(("Pf3D7_05_v3", 958000))
            return
        if bid == "btn_dhfr":
            self.dismiss(("Pf3D7_04_v3", 748000))
            return

        if bid == "btn_jump":
            self._handle_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._handle_input()

    def _handle_input(self) -> None:
        val = self.query_one("#locus_input", Input).value.strip().lower()
        if not val:
            self.dismiss(None)
            return

        # Check presets
        if val in GENE_PRESETS:
            chrom, pos, _ = GENE_PRESETS[val]
            self.dismiss((chrom, pos))
            return

        # Parse chr:pos format
        if ":" in val:
            parts = val.split(":", 1)
            chrom = parts[0].strip()
            # Restore casing for Pf3D7 contigs
            if chrom.startswith("pf3d7"):
                chrom = "Pf3D7" + chrom[5:]
            try:
                pos = int(parts[1].replace(",", "").strip())
                self.dismiss((chrom, pos))
                return
            except ValueError:
                pass

        self.dismiss(None)
