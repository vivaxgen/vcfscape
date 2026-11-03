"""
Cohort Manager Modal Screen for Malaria VCF TUI.
Allows users to create, define, clone, invert selections, and delete sample cohorts.
"""

from typing import Optional, Set, List, Tuple
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    Select,
    SelectionList,
)
from textual.widgets.selection_list import Selection

from vcfscape.core.cohorts import CohortManager, COHORT_COLORS


class CohortManagerScreen(ModalScreen[bool]):
    """Modal screen for interactive cohort creation, definition, cloning, and deletion."""

    DEFAULT_CSS = """
    CohortManagerScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }

    #cohort_dialog {
        width: 94%;
        max-width: 110;
        height: 92%;
        background: $surface;
        border: solid $primary;
        padding: 0 1;
        layout: vertical;
    }

    #dialog_header {
        height: 1;
        margin: 0;
        dock: top;
        content-align: center middle;
        text-style: bold;
        color: $primary-lighten-2;
    }

    .section_row {
        height: 3;
        margin: 0;
        align-vertical: middle;
    }

    .form_label_sm {
        width: 8;
        text-style: bold;
        padding-top: 1;
    }

    #cohort_selector {
        width: 32;
        margin-right: 1;
    }

    #name_input {
        width: 1fr;
        margin-right: 1;
    }

    #desc_input {
        width: 1.4fr;
    }

    #toolbar_row {
        height: 3;
        margin: 0;
        align-vertical: middle;
    }

    #search_input {
        width: 1fr;
        margin-right: 1;
    }

    .tool_btn {
        margin-right: 1;
        min-width: 10;
    }

    #selection_summary {
        height: 1;
        margin: 0;
        text-style: bold;
        color: $accent;
    }

    #sample_list_container {
        height: 1fr;
        border: solid $primary;
        background: $panel;
        padding: 0;
        margin: 0;
    }

    #sample_checklist {
        height: 100%;
        padding: 0;
    }

    #footer_actions {
        height: 3;
        dock: bottom;
        margin: 0;
        align-vertical: middle;
    }

    #status_message {
        width: 1fr;
        height: 1;
        color: $warning;
        text-style: italic;
    }

    .action_btn {
        margin-left: 1;
        min-width: 14;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel / Close", show=True),
        Binding("ctrl+s", "save_cohort", "Save Cohort", show=True),
        Binding("ctrl+i", "invert_selection", "Invert Selection", show=True),
        Binding("ctrl+a", "select_all", "Select All", show=True),
        Binding("ctrl+d", "deselect_all", "Deselect All", show=True),
    ]

    def __init__(self, cohort_manager: CohortManager, initial_cohort: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.cohort_manager = cohort_manager
        
        # Available cohorts
        cohort_keys = list(self.cohort_manager.cohorts.keys())
        self.active_cohort_name = initial_cohort if initial_cohort in cohort_keys else (cohort_keys[0] if cohort_keys else "All Samples")
        
        # State tracking for current working cohort
        self.is_new_mode: bool = False
        self.working_name: str = self.active_cohort_name
        self.working_desc: str = ""
        self.working_color: str = "#3b82f6"
        self.selected_samples: Set[str] = set()
        self.search_filter: str = ""

        self._load_cohort_into_working_state(self.active_cohort_name)

    def _load_cohort_into_working_state(self, cohort_name: str):
        if cohort_name in self.cohort_manager.cohorts:
            c = self.cohort_manager.cohorts[cohort_name]
            self.is_new_mode = False
            self.working_name = c.name
            self.working_desc = c.description
            self.working_color = c.color
            self.selected_samples = set(c.sample_ids)
        else:
            self.is_new_mode = True
            self.working_name = "New Cohort"
            self.working_desc = ""
            self.working_color = COHORT_COLORS[len(self.cohort_manager.cohorts) % len(COHORT_COLORS)]
            self.selected_samples = set()

    def _get_selector_options(self) -> List[Tuple[str, str]]:
        options = [
            (f"{c_name} (n={len(c.sample_ids)})", c_name)
            for c_name, c in self.cohort_manager.cohorts.items()
        ]
        options.append(("[+ Define New Cohort...]", "__NEW__"))
        return options

    def compose(self) -> ComposeResult:
        with Container(id="cohort_dialog"):
            yield Static("🧬  COHORT MANAGER: DEFINE, CLONE, INVERT & DELETE", id="dialog_header")

            # Row 1: Switch / Choose Cohort + Quick Management Actions
            with Horizontal(classes="section_row"):
                yield Label("Cohort:", classes="form_label_sm")
                yield Select(
                    options=self._get_selector_options(),
                    value=self.active_cohort_name,
                    id="cohort_selector",
                    allow_blank=False,
                )
                yield Button("+ New", variant="success", id="btn_new", classes="tool_btn")
                yield Button("Clone", variant="default", id="btn_clone", classes="tool_btn")
                yield Button("Delete", variant="error", id="btn_delete", classes="tool_btn")

            # Row 2: Cohort Name & Description (combined horizontally to save vertical space)
            with Horizontal(classes="section_row"):
                yield Label("Name:", classes="form_label_sm")
                yield Input(value=self.working_name, placeholder="e.g. Asymptomatic Responders", id="name_input")
                yield Label("Desc:", classes="form_label_sm")
                yield Input(value=self.working_desc, placeholder="Optional details or criteria", id="desc_input")

            # Row 3: Search filter & Selection helpers
            with Horizontal(id="toolbar_row"):
                yield Label("Filter:", classes="form_label_sm")
                yield Input(placeholder="Search sample IDs (e.g. KL_, AS_01)...", id="search_input")
                yield Button("Select All", id="btn_select_all", classes="tool_btn")
                yield Button("Clear All", id="btn_deselect_all", classes="tool_btn")
                yield Button("Invert (Ctrl+I)", variant="warning", id="btn_invert", classes="tool_btn")

            # Selection Count Summary (compact 1-line bar)
            yield Static(self._build_summary_text(), id="selection_summary")

            # Row 4: Sample Checklist Container (maximized height, 0 inner padding)
            with VerticalScroll(id="sample_list_container"):
                yield SelectionList[str](*self._build_selection_items(), id="sample_checklist")

            # Row 5: Action buttons (Save & Close) with status message on left
            with Horizontal(id="footer_actions"):
                yield Static("", id="status_message")
                yield Button("Cancel (Esc)", id="btn_cancel", classes="action_btn")
                yield Button("Save & Apply (Ctrl+S)", variant="primary", id="btn_save", classes="action_btn")

    def _build_selection_items(self) -> List[Selection[str]]:
        items: List[Selection[str]] = []
        term = self.search_filter.strip().lower()
        for sample_id in self.cohort_manager.all_samples:
            if term and term not in sample_id.lower():
                continue
            is_checked = sample_id in self.selected_samples
            items.append(Selection(sample_id, sample_id, is_checked))
        return items

    def _build_summary_text(self) -> str:
        total = len(self.cohort_manager.all_samples)
        selected = len(self.selected_samples)
        pct = (selected / total * 100) if total > 0 else 0
        term_note = f" (Filtering by '{self.search_filter}')" if self.search_filter else ""
        return f"Selected Samples: {selected} / {total} ({pct:.1f}% of dataset){term_note}"

    def _refresh_sample_list(self):
        checklist = self.query_one("#sample_checklist", SelectionList)
        checklist.clear_options()
        checklist.add_options(self._build_selection_items())
        
        summary = self.query_one("#selection_summary", Static)
        summary.update(self._build_summary_text())

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "cohort_selector":
            val = str(event.value)
            status = self.query_one("#status_message", Static)
            if val == "__NEW__":
                self.is_new_mode = True
                self.working_name = f"Cohort {len(self.cohort_manager.cohorts) + 1}"
                self.working_desc = ""
                self.working_color = COHORT_COLORS[len(self.cohort_manager.cohorts) % len(COHORT_COLORS)]
                self.selected_samples = set()
                status.update("Defining a new cohort. Choose samples and click 'Save & Apply'.")
            else:
                self.active_cohort_name = val
                self._load_cohort_into_working_state(val)
                status.update(f"Loaded existing cohort '{val}'.")

            # Update inputs
            self.query_one("#name_input", Input).value = self.working_name
            self.query_one("#desc_input", Input).value = self.working_desc

            # Update delete button enable/disable
            btn_delete = self.query_one("#btn_delete", Button)
            btn_delete.disabled = (self.working_name == "All Samples" and not self.is_new_mode)

            self._refresh_sample_list()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search_input":
            self.search_filter = event.value
            self._refresh_sample_list()
        elif event.input.id == "name_input":
            self.working_name = event.value.strip()
        elif event.input.id == "desc_input":
            self.working_desc = event.value.strip()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        """Keep selected_samples set in sync when checkboxes are toggled."""
        visible_options = {item.prompt for item in self.query_one("#sample_checklist", SelectionList)._options}
        checked_set = set(event.selection_list.selected)

        # Update membership for visible items
        for s in visible_options:
            if s in checked_set:
                self.selected_samples.add(s)
            else:
                self.selected_samples.discard(s)

        summary = self.query_one("#selection_summary", Static)
        summary.update(self._build_summary_text())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_new":
            self.action_new_cohort()
        elif btn_id == "btn_clone":
            self.action_clone_cohort()
        elif btn_id == "btn_delete":
            self.action_delete_cohort()
        elif btn_id == "btn_select_all":
            self.action_select_all()
        elif btn_id == "btn_deselect_all":
            self.action_deselect_all()
        elif btn_id == "btn_invert":
            self.action_invert_selection()
        elif btn_id == "btn_save":
            self.action_save_cohort()
        elif btn_id == "btn_cancel":
            self.action_dismiss_modal()

    def action_new_cohort(self):
        selector = self.query_one("#cohort_selector", Select)
        selector.value = "__NEW__"

    def action_clone_cohort(self):
        status = self.query_one("#status_message", Static)
        if self.is_new_mode:
            status.update("Cannot duplicate an unsaved new cohort.")
            return

        source_name = self.active_cohort_name
        try:
            cloned = self.cohort_manager.clone_cohort(source_name)
            self.active_cohort_name = cloned.name
            self._load_cohort_into_working_state(cloned.name)

            # Update selector
            selector = self.query_one("#cohort_selector", Select)
            selector.set_options(self._get_selector_options())
            selector.value = cloned.name

            self.query_one("#name_input", Input).value = self.working_name
            self.query_one("#desc_input", Input).value = self.working_desc
            self._refresh_sample_list()
            status.update(f"Duplicated '{source_name}' to '{cloned.name}'.")
        except Exception as e:
            status.update(f"Error cloning cohort: {e}")

    def action_delete_cohort(self):
        status = self.query_one("#status_message", Static)
        if self.is_new_mode:
            status.update("Nothing to delete (in new cohort mode).")
            return
        if self.active_cohort_name == "All Samples":
            status.update("Cannot delete the default 'All Samples' cohort.")
            return

        target = self.active_cohort_name
        success = self.cohort_manager.delete_cohort(target)
        if success:
            remaining = list(self.cohort_manager.cohorts.keys())
            new_target = remaining[0] if remaining else "All Samples"
            self.active_cohort_name = new_target
            self._load_cohort_into_working_state(new_target)

            selector = self.query_one("#cohort_selector", Select)
            selector.set_options(self._get_selector_options())
            selector.value = new_target

            self.query_one("#name_input", Input).value = self.working_name
            self.query_one("#desc_input", Input).value = self.working_desc
            self._refresh_sample_list()
            status.update(f"Deleted cohort '{target}'. Switched to '{new_target}'.")
        else:
            status.update(f"Could not delete cohort '{target}'.")

    def action_select_all(self):
        """Select all visible or all samples."""
        term = self.search_filter.strip().lower()
        for s in self.cohort_manager.all_samples:
            if not term or term in s.lower():
                self.selected_samples.add(s)
        self._refresh_sample_list()
        self.query_one("#status_message", Static).update("Selected all matching samples.")

    def action_deselect_all(self):
        term = self.search_filter.strip().lower()
        if term:
            for s in self.cohort_manager.all_samples:
                if term in s.lower():
                    self.selected_samples.discard(s)
        else:
            self.selected_samples.clear()
        self._refresh_sample_list()
        self.query_one("#status_message", Static).update("Cleared sample selections.")

    def action_invert_selection(self):
        """Invert selection: flips current selection across entire sample list."""
        self.selected_samples = set(
            self.cohort_manager.invert_selection(list(self.selected_samples))
        )
        self._refresh_sample_list()
        self.query_one("#status_message", Static).update(
            f"Inverted sample selection: now {len(self.selected_samples)} selected."
        )

    def action_save_cohort(self):
        status = self.query_one("#status_message", Static)
        name = self.working_name.strip()
        if not name:
            status.update("Error: Cohort name cannot be empty.")
            return

        sample_list = sorted(list(self.selected_samples))

        try:
            if self.is_new_mode:
                if name in self.cohort_manager.cohorts:
                    status.update(f"Error: A cohort named '{name}' already exists.")
                    return
                self.cohort_manager.add_cohort(
                    name=name,
                    sample_ids=sample_list,
                    description=self.working_desc,
                    color=self.working_color,
                    active=True,
                )
            else:
                self.cohort_manager.update_cohort(
                    old_name=self.active_cohort_name,
                    new_name=name,
                    sample_ids=sample_list,
                    description=self.working_desc,
                    color=self.working_color,
                )

            # Close modal returning True to indicate changes
            self.dismiss(True)
        except Exception as e:
            status.update(f"Error saving cohort: {e}")

    def action_dismiss_modal(self):
        self.dismiss(False)
