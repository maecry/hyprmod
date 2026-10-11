"""Typed editors for the hypr* companion tools.

One page per tool (hypridle, hyprlock, hyprlauncher, hyprsunset). Each
page writes straight back into that tool's own Hyprlang file, so the
tool keeps a single source of truth and anything written by hand (extra
options, comments, blocks HyprMod does not know about) survives.

Nothing here is live-applied. Hypridle, hyprlock and hyprlauncher read
their config only at startup and expose no reload IPC, so a change takes
effect the next time the tool runs. The page says so in its header hint
instead of pretending otherwise.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from hyprmod.core import ecosystem
from hyprmod.ui import clear_children, make_inline_hint, make_page_layout, try_with_toast

if TYPE_CHECKING:
    from hyprmod.window import HyprModWindow

# Spin rows work in doubles; these stand in for "no bound documented".
_FALLBACK_MIN = -1_000_000.0
_FALLBACK_MAX = 1_000_000.0


class EcosystemPage:
    """Typed editor for one companion tool's config file."""

    def __init__(self, window: "HyprModWindow", tool: ecosystem.Tool) -> None:
        self._window = window
        self.tool = tool
        self._config = ecosystem.ToolConfig(tool.config_path())
        self._content: Gtk.Box | None = None

    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        title = Adw.WindowTitle(title=self.tool.label, subtitle=self.tool.config_name)
        header.set_title_widget(title)
        reload_button = Gtk.Button(icon_name="view-refresh-symbolic")
        reload_button.set_tooltip_text("Reload from disk")
        reload_button.add_css_class("flat")
        reload_button.connect("clicked", lambda _button: self.refresh())
        header.pack_start(reload_button)

        toolbar_view, _, content_box, _ = make_page_layout(header=header)
        self._content = content_box
        self.refresh()
        return toolbar_view

    def refresh(self) -> None:
        """Rebuild every row from what is on disk right now."""
        if self._content is None:
            return
        clear_children(self._content)
        if not self.tool.is_installed():
            self._content.append(self._missing_tool_hint())
            return
        if not self._config.exists():
            self._content.append(self._missing_config_hint())
            return
        self._content.append(
            make_inline_hint(
                f"Editing {self.tool.config_name}. {self.tool.restart_hint}",
                icon_name=self.tool.icon,
            )
        )
        snapshot = self._config.snapshot()
        for group in self.tool.groups:
            self._content.append(self._build_group(group, snapshot))

    # -- Hints shown when the tool or its config is missing --

    def _missing_tool_hint(self) -> Gtk.Widget:
        command = ecosystem.package_install_command(self.tool.package)
        if command is None:
            return make_inline_hint(
                f"{self.tool.label} is not installed and pacman was not found. "
                f"Install the {self.tool.package} package, then reload this page.",
                icon_name="dialog-warning-symbolic",
            )
        return make_inline_hint(
            f"{self.tool.label} is not installed. Running `{' '.join(command)}` installs it.",
            icon_name="dialog-warning-symbolic",
            button_label="Install",
            button_callback=lambda _button: self._install(command),
        )

    def _missing_config_hint(self) -> Gtk.Widget:
        return make_inline_hint(
            f"{self.tool.summary} There is no {self.tool.config_name} yet.",
            icon_name=self.tool.icon,
            button_label="Create config",
            button_callback=lambda _button: self._create(),
        )

    def _install(self, command: list[str]) -> None:
        if ecosystem.launch_in_terminal(command):
            self._window.show_toast(f"Installing {self.tool.package} in a terminal", timeout=8)
            return
        self._window.show_toast(
            f"No terminal emulator found. Run `{' '.join(command)}` yourself.",
            timeout=8,
        )

    def _create(self) -> None:
        def action() -> None:
            self._config.write(ecosystem.default_document(self.tool))

        if try_with_toast(self._window.show_bug_toast, "Could not create the config", action):
            self.refresh()

    # -- Rows --

    def _build_group(
        self, group: ecosystem.Group, snapshot: ecosystem.Snapshot
    ) -> Adw.PreferencesGroup:
        widget = Adw.PreferencesGroup(title=group.label, description=group.description)
        if group.repeatable:
            add_button = Gtk.Button(icon_name="list-add-symbolic")
            add_button.set_tooltip_text(f"Add {group.label.lower()}")
            add_button.add_css_class("flat")
            add_button.connect("clicked", lambda _button: self._add_block(group))
            widget.set_header_suffix(add_button)
            for index, entry in enumerate(snapshot.blocks.get(group.path, [])):
                widget.add(self._build_block(group, index, entry))
            return widget

        for field in group.fields:
            full_key = group.full_key(field)
            value = snapshot.values.get(full_key, field.default)
            widget.add(self._build_row(field, value, self._setter(full_key)))
        return widget

    def _build_block(
        self,
        group: ecosystem.Group,
        index: int,
        entry: dict[str, str],
    ) -> Adw.ExpanderRow:
        expander = Adw.ExpanderRow(title=f"{group.label} {index + 1}")
        remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        remove_button.set_tooltip_text(f"Remove this {group.label.lower()}")
        remove_button.add_css_class("flat")
        remove_button.set_valign(Gtk.Align.CENTER)
        remove_button.connect("clicked", lambda _button: self._remove_block(group, index))
        expander.add_suffix(remove_button)
        for field in group.fields:
            setter = self._block_setter(group, index, field)
            expander.add_row(self._build_row(field, entry.get(field.key, field.default), setter))
        return expander

    def _build_row(
        self,
        field: ecosystem.Field,
        value: str,
        on_change: Callable[[str], None],
    ) -> Adw.PreferencesRow:
        if field.kind == "bool":
            row = Adw.SwitchRow(title=field.label)
            row.set_active(_as_bool(value))
            if field.hint:
                row.set_subtitle(field.hint)
            row.connect(
                "notify::active",
                lambda widget, _pspec: on_change("true" if widget.get_active() else "false"),
            )
            return row
        if field.kind in ("int", "float"):
            return self._build_spin_row(field, value, on_change)
        entry = Adw.EntryRow(title=field.label)
        entry.set_text(value)
        entry.set_show_apply_button(True)
        if field.hint:
            entry.set_tooltip_text(field.hint)
        entry.connect("apply", lambda widget: on_change(widget.get_text()))
        return entry

    def _build_spin_row(
        self,
        field: ecosystem.Field,
        value: str,
        on_change: Callable[[str], None],
    ) -> Adw.SpinRow:
        minimum = _FALLBACK_MIN if field.minimum is None else float(field.minimum)
        maximum = _FALLBACK_MAX if field.maximum is None else float(field.maximum)
        step = 1.0 if field.kind == "int" else 0.05
        row = Adw.SpinRow.new_with_range(minimum, maximum, step)
        row.set_title(field.label)
        row.set_digits(0 if field.kind == "int" else 2)
        row.set_value(_as_number(value, field.default))
        if field.hint:
            row.set_tooltip_text(field.hint)
        # The handler is connected after the initial set_value, so building
        # the row is not reported as an edit. It ignores a notify that
        # carries the same value, which is what a rebuild produces.
        cell = [_as_number(value, field.default)]

        def changed(widget: Adw.SpinRow, _pspec: object) -> None:
            current = widget.get_value()
            if current == cell[0]:
                return
            cell[0] = current
            on_change(_format_number(current, field.kind))

        row.connect("notify::value", changed)
        return row

    # -- Writes --

    def _setter(self, full_key: str) -> Callable[[str], None]:
        def apply(value: str) -> None:
            self._save(
                f"Could not save {full_key}",
                lambda: self._config.set_values({full_key: value}),
            )

        return apply

    def _block_setter(
        self,
        group: ecosystem.Group,
        index: int,
        field: ecosystem.Field,
    ) -> Callable[[str], None]:
        def apply(value: str) -> None:
            self._save(
                f"Could not save {field.label}",
                lambda: self._config.set_block_value(group.path, index, field.key, value),
            )

        return apply

    def _add_block(self, group: ecosystem.Group) -> None:
        entries = {field.key: field.default for field in group.fields}
        if self._save(
            f"Could not add a {group.label.lower()}",
            lambda: self._config.add_block(group.path, entries),
        ):
            self.refresh()

    def _remove_block(self, group: ecosystem.Group, index: int) -> None:
        if self._save(
            f"Could not remove the {group.label.lower()}",
            lambda: self._config.remove_block(group.path, index),
        ):
            self.refresh()

    def _save(self, error_prefix: str, action: Callable[[], object]) -> bool:
        return try_with_toast(self._window.show_bug_toast, error_prefix, action)


def _format_number(value: float, kind: str) -> str:
    return str(int(round(value))) if kind == "int" else f"{value:g}"


def _as_number(value: str, fallback: str) -> float:
    try:
        return float(value)
    except ValueError:
        return float(fallback)


def _as_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")
