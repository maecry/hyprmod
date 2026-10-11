"""Hyprshutdown support.

Hyprshutdown has no config file: everything it understands is a command line
flag. This module builds that command line, so HyprMod can offer it as a
keybind instead of pretending there is a file to edit.
"""

import shutil

BINARY = "hyprshutdown"
PACKAGE = "hyprshutdown"
LABEL = "Hyprshutdown"
ICON = "system-shutdown-symbolic"
SUMMARY = "A shutdown dialog for Hyprland, with logout, reboot and poweroff."

#: ``--vt`` takes the virtual terminal to switch to after Hyprland exits.
VT_MAX = 12


def _quote(value: str) -> str:
    """Single-quote a value: Hyprland runs bind arguments through a shell."""
    return "'" + value.replace("'", "'\\''") + "'"


def command(vt: int = 0, top_label: str = "", post_cmd: str = "") -> str:
    """The hyprshutdown command line built from the page's fields."""
    parts = [BINARY]
    if vt:
        parts += ["--vt", str(vt)]
    if top_label.strip():
        parts += ["--top-label", _quote(top_label.strip())]
    if post_cmd.strip():
        parts += ["--post-cmd", _quote(post_cmd.strip())]
    return " ".join(parts)


def is_installed() -> bool:
    return shutil.which(BINARY) is not None
