"""Hyprshutdown page.

Hyprshutdown has no config file, so this page is not a settings editor: it
explains what the tool is, offers to install it, and builds a keybind from
the flags the user picks. The keybind is added through the normal binds
page, so it lands in the user's own binds module like any other bind.
"""

from typing import TYPE_CHECKING

from gi.repository import Adw, Gdk, Gtk
from hyprland_config import BindData

from hyprmod.core import ecosystem, hyprshutdown
from hyprmod.ui import clear_children, make_inline_hint, make_page_layout

if TYPE_CHECKING:
    from hyprmod.window import HyprModWindow

#: The combination the helper installs. The binds page reports a clash.
KEYBIND_MODS = ["SUPER", "SHIFT"]
KEYBIND_KEY = "P"
KEYBIND_DESCRIPTION = "Log out"


class HyprshutdownPage:
    """Install helper and keybind builder for hyprshutdown."""

    def __init__(self, window: "HyprModWindow") -> None:
        self._window = window
        self._content: Gtk.Box | None = None
        self._command_row: Adw.ActionRow | None = None
        self._vt = 0
        self._top_label = ""
        self._post_cmd = ""

    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        header.set_title_widget(
            Adw.WindowTitle(title=hyprshutdown.LABEL, subtitle="flags, no config file")
        )
        reload_button = Gtk.Button(icon_name="view-refresh-symbolic")
        reload_button.set_tooltip_text("Reload")
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
        clear_children(self._content)
        self._content.append(self._status_hint())
        self._content.append(self._options_group())
        self._content.append(self._keybind_group())
        self._update_command()

    # -- Hints --

    def _status_hint(self) -> Gtk.Widget:
        if hyprshutdown.is_installed():
            return make_inline_hint(
                f"{hyprshutdown.SUMMARY} It reads no config file: every option is a flag, "
                "so this page builds a command line instead.",
                icon_name=hyprshutdown.ICON,
            )
        command = ecosystem.package_install_command(hyprshutdown.PACKAGE)
        if command is None:
            return make_inline_hint(
                f"{hyprshutdown.LABEL} is not installed and pacman was not found. "
                f"Install the {hyprshutdown.PACKAGE} package, then reload this page.",
                icon_name="dialog-warning-symbolic",
            )
        return make_inline_hint(
            f"{hyprshutdown.LABEL} is not installed. Running `{' '.join(command)}` installs it.",
            icon_name="dialog-warning-symbolic",
            button_label="Install",
            button_callback=lambda _button: self._install(command),
        )

    def _install(self, command: list[str]) -> None:
        if ecosystem.launch_in_terminal(command):
            self._window.show_toast(f"Installing {hyprshutdown.PACKAGE} in a terminal", timeout=8)
            return
        self._window.show_toast(
            f"No terminal emulator found. Run `{' '.join(command)}` yourself.", timeout=8
        )

    # -- Groups --

    def _options_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Options",
            description="Baked into the command line below. They change nothing until you "
            "add the keybind.",
        )

        vt_row = Adw.SpinRow.new_with_range(0, hyprshutdown.VT_MAX, 1)
        vt_row.set_title("Virtual terminal")
        vt_row.set_subtitle("Switch to this VT after Hyprland exits. 0 keeps the current one.")
        vt_row.set_value(self._vt)
        vt_row.connect("notify::value", self._on_vt_changed)
        group.add(vt_row)

        label_row = Adw.EntryRow(title="Top label")
        label_row.set_text(self._top_label)
        label_row.connect("notify::text", self._on_top_label_changed)
        group.add(label_row)

        post_row = Adw.EntryRow(title="Post command")
        post_row.set_text(self._post_cmd)
        post_row.connect("notify::text", self._on_post_cmd_changed)
        group.add(post_row)

        return group

    def _keybind_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Keybind",
            description="Super + Shift + P runs this command once the keybind is added.",
        )
        self._command_row = Adw.ActionRow(title="Command")
        self._command_row.set_subtitle_selectable(True)
        group.add(self._command_row)

        add_row = Adw.ActionRow(
            title=f"Add {KEYBIND_DESCRIPTION.lower()} keybind",
            subtitle="Super + Shift + P",
        )
        add_button = Gtk.Button(label="Add")
        add_button.set_valign(Gtk.Align.CENTER)
        add_button.add_css_class("suggested-action")
        add_button.connect("clicked", lambda _button: self._add_keybind())
        add_row.add_suffix(add_button)
        group.add(add_row)

        copy_row = Adw.ActionRow(title="Copy command")
        copy_button = Gtk.Button(label="Copy")
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.connect("clicked", lambda _button: self._copy_command())
        copy_row.add_suffix(copy_button)
        group.add(copy_row)

        return group

    # -- State --

    def _command(self) -> str:
        return hyprshutdown.command(self._vt, self._top_label, self._post_cmd)

    def _update_command(self) -> None:
        if self._command_row is not None:
            self._command_row.set_subtitle(self._command())

    def _on_vt_changed(self, row: Adw.SpinRow, _param) -> None:
        self._vt = int(row.get_value())
        self._update_command()

    def _on_top_label_changed(self, row: Adw.EntryRow, _param) -> None:
        self._top_label = row.get_text()
        self._update_command()

    def _on_post_cmd_changed(self, row: Adw.EntryRow, _param) -> None:
        self._post_cmd = row.get_text()
        self._update_command()

    def _copy_command(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(self._command())
        self._window.show_toast("Command copied")

    def _add_keybind(self) -> None:
        binds_page = getattr(self._window, "_binds_page", None)
        if binds_page is None:
            self._window.show_toast("The keybinds page is not available", timeout=8)
            return
        bind = BindData(
            mods=list(KEYBIND_MODS),
            key=KEYBIND_KEY,
            dispatcher="exec",
            arg=self._command(),
            description=KEYBIND_DESCRIPTION,
        )
        if binds_page.find_conflicts(bind):
            self._window.show_toast(
                f"{bind.format_shortcut()} is already bound. Change it on the Keybinds page.",
                timeout=8,
            )
            return
        if not binds_page.add_bind(bind):
            self._window.show_toast("HyprMod cannot represent that keybind", timeout=8)
            return
        self._window.show_toast(f"Added {bind.format_shortcut()} → {KEYBIND_DESCRIPTION}")
