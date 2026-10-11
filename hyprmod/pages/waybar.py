"""Waybar configuration page.

Waybar's config is JSONC, so the edits go through :mod:`hyprmod.core.jsonc`
and the user's comments survive. Options are typed from the reference in
:mod:`hyprmod.data.waybar_modules`, which is generated from waybar's own man
pages. Nothing is live-applied: waybar only picks the file up when it starts
or when it is asked to reload.
"""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gi.repository import Adw, Gtk
from hyprland_config import atomic_write

from hyprmod.core import ecosystem, waybar
from hyprmod.ui import clear_children, make_inline_hint, make_page_layout, try_with_toast

if TYPE_CHECKING:
    from hyprmod.window import HyprModWindow

_FALLBACK_MIN = -1_000_000.0
_FALLBACK_MAX = 1_000_000.0

HINT = (
    "Editing config.jsonc. Waybar reads it at startup, so changes show after a restart or a reload."
)


def _kind_of(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"


def _spec_default(spec: tuple[str, str, str]) -> Any:
    """The value a fresh option starts at, shaped for its widget."""
    type_name, default, _description = spec
    kind = waybar.widget_kind(type_name)
    if kind == "bool":
        return default.strip().lower() in ("true", "1", "yes", "on")
    if kind == "number":
        try:
            return int(default)
        except ValueError:
            try:
                return float(default)
            except ValueError:
                return 0
    if kind == "json":
        try:
            return waybar.decode(default) if default else []
        except ValueError:
            return []
    return default


def _as_number(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return 0.0


def _compact(value: object) -> str:
    return json.dumps(value)


class WaybarPage:
    """Editor for the waybar config: the bar, its layout, and each module."""

    def __init__(self, window: "HyprModWindow") -> None:
        self._window = window
        self._content: Gtk.Box | None = None
        self._text = ""

    # -- shell --

    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        header.set_title_widget(Adw.WindowTitle(title="Waybar", subtitle="config.jsonc"))
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
        if self._content is None:
            return
        self._text = waybar.read()
        clear_children(self._content)
        if not waybar.is_installed():
            self._content.append(self._missing_tool_hint())
            return
        if not self._text.strip():
            self._content.append(self._missing_config_hint())
            return
        self._content.append(make_inline_hint(HINT, icon_name="view-grid-symbolic"))
        self._content.append(self._bar_group())
        self._content.append(self._layout_group())
        for module in waybar.all_modules(self._text):
            self._content.append(self._module_group(module))

    def _missing_tool_hint(self) -> Gtk.Widget:
        command = ecosystem.package_install_command(waybar.PACKAGE)
        if command is None:
            return make_inline_hint(
                "Waybar is not installed and pacman was not found. Install the "
                f"{waybar.PACKAGE} package, then reload this page.",
                icon_name="dialog-warning-symbolic",
            )
        return make_inline_hint(
            f"Waybar is not installed. Running `{' '.join(command)}` installs it.",
            icon_name="dialog-warning-symbolic",
            button_label="Install",
            button_callback=lambda _button: self._install(command),
        )

    def _install(self, command: list[str]) -> None:
        if ecosystem.launch_in_terminal(command):
            self._window.show_toast(f"Installing {waybar.PACKAGE} in a terminal", timeout=8)
            return
        self._window.show_toast(
            f"No terminal emulator found. Run `{' '.join(command)}` yourself.", timeout=8
        )

    def _missing_config_hint(self) -> Gtk.Widget:
        return make_inline_hint(
            "No waybar config of your own yet.",
            icon_name="view-grid-symbolic",
            button_label="Create config",
            button_callback=lambda _button: self._create(),
        )

    def _create(self) -> None:
        path = waybar.user_config_path()

        def action() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, waybar.default_document())

        if try_with_toast(self._window.show_bug_toast, "Could not create the config", action):
            self.refresh()

    # -- saving --

    def _edit(self, mutate: Callable[[str], str]) -> None:
        path = waybar.user_config_path()

        def action() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, mutate(self._text))

        if try_with_toast(self._window.show_bug_toast, "Could not save the waybar config", action):
            self.refresh()

    # -- bar level options --

    def _bar_group(self) -> Adw.PreferencesGroup:
        current = waybar.bar_options(self._text)
        group = Adw.PreferencesGroup(
            title="Bar",
            description="Bar level settings. Which modules show up is edited under Layout.",
        )
        for key, value in current.items():
            spec = waybar.BAR_OPTIONS.get(key)
            group.add(self._option_row(key, value, spec, self._bar_setter(key)))
        for key in sorted(set(waybar.BAR_OPTIONS) - set(current)):
            group.add(
                self._option_row(
                    key,
                    _spec_default(waybar.BAR_OPTIONS[key]),
                    waybar.BAR_OPTIONS[key],
                    self._bar_setter(key),
                )
            )
        return group

    def _bar_setter(self, key: str) -> Callable[[object], None]:
        return lambda value: self._edit(lambda text: waybar.set_bar_option(text, key, value))

    # -- layout --

    def _layout_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Layout",
            description="Which modules sit in which part of the bar.",
        )
        for section in waybar.SECTIONS:
            group.add(self._section_row(section))
        return group

    def _section_row(self, section: str) -> Adw.ExpanderRow:
        modules = waybar.modules(self._text, section)
        row = Adw.ExpanderRow(title=section.removeprefix("modules-").capitalize())
        row.set_subtitle(", ".join(modules) if modules else "empty")
        for module in modules:
            item = Adw.ActionRow(title=module)
            remove = Gtk.Button(icon_name="user-trash-symbolic")
            remove.set_valign(Gtk.Align.CENTER)
            remove.add_css_class("flat")
            remove.set_tooltip_text(f"Remove {module} from {section}")
            remove.connect(
                "clicked", lambda _button, name=module: self._remove_module(section, name)
            )
            item.add_suffix(remove)
            row.add_row(item)

        available = [name for name in waybar.module_names() if name not in modules]
        if available:
            row.add_row(
                self._picker_row(
                    "Add module", available, f"Add to {section}", self._module_adder(section)
                )
            )
        return row

    def _module_adder(self, section: str) -> Callable[[str], None]:
        return lambda name: self._edit(lambda text: waybar.add_module(text, section, name))

    def _remove_module(self, section: str, module: str) -> None:
        self._edit(lambda text: waybar.remove_module(text, section, module))

    # -- modules --

    def _module_group(self, module: str) -> Adw.PreferencesGroup:
        current = waybar.module_options(self._text, module)
        specs = waybar.option_specs(module)
        group = Adw.PreferencesGroup(title=module)
        for key, value in current.items():
            spec = specs.get(key)
            group.add(self._option_row(key, value, spec, self._module_setter(module, key)))
        missing = sorted(set(specs) - set(current))
        if missing:
            group.add(
                self._picker_row(
                    "Add option", missing, f"Add to {module}", self._option_adder(module)
                )
            )
        return group

    def _module_setter(self, module: str, key: str) -> Callable[[object], None]:
        return lambda value: self._edit(lambda text: waybar.set_option(text, module, key, value))

    def _option_adder(self, module: str) -> Callable[[str], None]:
        def add(key: str) -> None:
            spec = waybar.option_specs(module)[key]
            value = _spec_default(spec)
            self._edit(lambda text: waybar.set_option(text, module, key, value))

        return add

    # -- rows --

    def _option_row(
        self,
        key: str,
        value: object,
        spec: tuple[str, str, str] | None,
        setter: Callable[[object], None],
    ) -> Gtk.Widget:
        type_name, _default, description = spec if spec else ("", "", "")
        kind = waybar.widget_kind(type_name) if spec else _kind_of(value)
        if kind == "bool":
            row: Adw.PreferencesRow = Adw.SwitchRow(title=key)
            row.set_active(bool(value))
            row.connect("notify::active", lambda widget, _param: setter(widget.get_active()))
        elif kind == "number":
            is_float = (
                "float" in type_name.lower()
                or "double" in type_name.lower()
                or (spec is None and isinstance(value, float))
            )
            row = Adw.SpinRow.new_with_range(_FALLBACK_MIN, _FALLBACK_MAX, 1.0)
            row.set_title(key)
            if is_float:
                row.set_digits(2)
            row.set_value(_as_number(value))
            row.connect(
                "notify::value",
                lambda widget, _param: setter(
                    widget.get_value() if is_float else int(widget.get_value())
                ),
            )
        else:
            row = Adw.EntryRow(title=key)
            row.set_text(value if isinstance(value, str) else _compact(value))
            row.set_show_apply_button(True)
            row.connect("apply", lambda widget: self._apply_entry(widget, kind, setter))
        if description:
            row.set_tooltip_text(description)
        return row

    def _apply_entry(self, row: Adw.EntryRow, kind: str, setter: Callable[[object], None]) -> None:
        text = row.get_text()
        if kind == "json":
            try:
                value = waybar.decode(text)
            except ValueError as error:
                self._window.show_toast(f"Not valid JSON: {error}", timeout=8)
                return
        else:
            value = text
        setter(value)

    def _picker_row(
        self, title: str, keys: list[str], tooltip: str, handler: Callable[[str], None]
    ) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        dropdown = Gtk.DropDown.new_from_strings(keys)
        dropdown.set_valign(Gtk.Align.CENTER)
        row.add_suffix(dropdown)
        button = Gtk.Button(icon_name="list-add-symbolic")
        button.set_valign(Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda _button, widget=dropdown: self._pick(widget, handler))
        row.add_suffix(button)
        return row

    def _pick(self, dropdown: Gtk.DropDown, handler: Callable[[str], None]) -> None:
        item = dropdown.get_selected_item()
        if isinstance(item, Gtk.StringObject):
            handler(item.get_string())
