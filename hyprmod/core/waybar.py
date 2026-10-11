"""Waybar configuration support.

Waybar keeps a JSONC config under ``$XDG_CONFIG_HOME/waybar``. This module
reads and edits that file in place, so the user's comments survive, and pairs
each module with the option reference in :mod:`hyprmod.data.waybar_modules`.
"""

import json
import os
import shutil
from pathlib import Path

from hyprmod.core import jsonc
from hyprmod.data.waybar_modules import MODULES

BINARY = "waybar"
PACKAGE = "waybar"
ICON = "view-grid-symbolic"

FILE_NAMES = ("config.jsonc", "config.json", "config")
SYSTEM_DIR = Path("/etc/xdg/waybar")
SECTIONS = ("modules-left", "modules-center", "modules-right")

#: Namespaced modules are documented as ``waybar-hyprland-workspaces`` and used
#: as ``hyprland/workspaces``. Only these heads carry a namespace.
_NAMESPACES = ("hyprland", "sway", "niri", "dwl", "river", "ext", "wlr", "systemd")

#: Bar level options, which the module man pages do not cover.
BAR_OPTIONS: dict[str, tuple[str, str, str]] = {
    "height": ("integer", "30", "Height of the bar in pixels."),
    "spacing": ("integer", "4", "Gaps between the modules."),
    "margin-top": ("integer", "0", "Margin around the bar."),
    "margin-bottom": ("integer", "0", "Margin around the bar."),
    "margin-left": ("integer", "0", "Margin around the bar."),
    "margin-right": ("integer", "0", "Margin around the bar."),
    "position": ("string", "top", "Where the bar sits: top, bottom, left or right."),
    "layer": ("string", "top", "Layer shell layer: bottom, top or overlay."),
    "output": ("string", "", "Name of the output to use, or a list of outputs."),
    "reload_style_on_change": ("bool", "false", "Reload style.css when it changes."),
    "include": ("string", "", "Path to another config file to merge in."),
}

MINIMAL_CONFIG = """{
    "layer": "top",
    "position": "top",
    "height": 30,
    "spacing": 4,
    "modules-left": [],
    "modules-center": [],
    "modules-right": ["clock", "custom/power"],
    "clock": {
        "format": "{:%H:%M}"
    }
}
"""


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "waybar"


def config_path() -> Path:
    """The config waybar would load: the user's, else the system default."""
    directory = config_dir()
    for name in FILE_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    for name in FILE_NAMES:
        candidate = SYSTEM_DIR / name
        if candidate.is_file():
            return candidate
    return directory / FILE_NAMES[0]


def user_config_path() -> Path:
    """Where HyprMod writes, whether or not the user has a config yet."""
    for name in FILE_NAMES:
        candidate = config_dir() / name
        if candidate.is_file():
            return candidate
    return config_dir() / FILE_NAMES[0]


def default_document() -> str:
    """Config text for a user who has none: the system default if there is one."""
    for name in FILE_NAMES:
        candidate = SYSTEM_DIR / name
        if candidate.is_file():
            return candidate.read_text()
    return MINIMAL_CONFIG


def is_installed() -> bool:
    return shutil.which(BINARY) is not None


def read() -> str:
    try:
        return user_config_path().read_text()
    except (OSError, UnicodeDecodeError):
        return ""


# -- reading ----------------------------------------------------------------


def bar_path(text: str) -> tuple[str | int, ...]:
    """Waybar accepts a single bar object or a list of them."""
    root = jsonc.Document(text).root
    return (0,) if root.kind == "array" else ()


def modules(text: str, section: str) -> list[str]:
    document = jsonc.Document(text)
    value = document.get((*bar_path(text), section), [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def all_modules(text: str) -> list[str]:
    seen: list[str] = []
    for section in SECTIONS:
        for module in modules(text, section):
            if module not in seen:
                seen.append(module)
    return seen


def module_options(text: str, module: str) -> dict[str, object]:
    value = jsonc.Document(text).get((*bar_path(text), module), {})
    return value if isinstance(value, dict) else {}


def bar_options(text: str) -> dict[str, object]:
    value = jsonc.Document(text).get(bar_path(text), {})
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if key not in SECTIONS and not isinstance(item, (dict, list))
    }


# -- writing ----------------------------------------------------------------


def set_option(text: str, module: str, key: str, value: object) -> str:
    document = jsonc.Document(text)
    base = bar_path(text)
    node = document.lookup(base)
    if node is None or node.kind != "object":
        raise jsonc.JsoncError("the waybar config has no bar object")
    if node.member(module) is None:
        return document.put(base, module, {key: value}).text
    return document.put((*base, module), key, value).text


def set_bar_option(text: str, key: str, value: object) -> str:
    """Set a bar level option, which lives next to the module entries."""
    return jsonc.Document(text).put(bar_path(text), key, value).text


def remove_option(text: str, module: str, key: str) -> str:
    document = jsonc.Document(text)
    return document.drop((*bar_path(text), module), key).text


def add_module(text: str, section: str, module: str) -> str:
    path = (*bar_path(text), section)
    document = jsonc.Document(text)
    if document.lookup(path) is None:
        raise jsonc.JsoncError(f"the bar has no {section!r} list")
    if module in modules(text, section):
        return text
    return document.append(path, module).text


def remove_module(text: str, section: str, module: str) -> str:
    path = (*bar_path(text), section)
    current = modules(text, section)
    if module not in current:
        return text
    return jsonc.Document(text).remove_at(path, current.index(module)).text


def decode(raw: str) -> object:
    """Turn text typed into a JSON valued row into a Python value."""
    return json.loads(raw)


# -- option reference -------------------------------------------------------


def option_specs(module: str) -> dict[str, tuple[str, str, str]]:
    """Option name to ``(type, default, description)`` for *module*."""
    rows = MODULES.get(module)
    if rows is None:
        rows = MODULES.get(module.replace("/", "-"))
    if rows is None:
        rows = MODULES.get(module.split("/", 1)[0], ())
    return {option: (kind, default, description) for option, kind, default, description in rows}


def widget_kind(type_name: str) -> str:
    """Map a man page type onto the widget kind used by the editor."""
    name = type_name.strip().lower()
    if name == "bool":
        return "bool"
    if any(word in name for word in ("int", "float", "double", "number")):
        return "number"
    if name in ("array", "object", "json", "list"):
        return "json"
    return "string"


def module_names() -> list[str]:
    """Every module id we know about, ready to drop into a config."""
    names: list[str] = []
    for name in sorted(MODULES):
        head, _, tail = name.partition("-")
        names.append(f"{head}/{tail}" if tail and head in _NAMESPACES else name)
    return names
