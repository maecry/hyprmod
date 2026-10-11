import json
import re
from typing import Any

import pytest

from hyprmod.core import jsonc, waybar

SAMPLE = """{
    // top bar
    "layer": "top",
    "height": 30,
    "modules-left": [
        "hyprland/workspaces",
        "custom/media", // scratch
    ],
    "modules-center": ["hyprland/window"],
    "modules-right": [
        "clock",
        "custom/power",
    ],
    "clock": {
        "format": "{:%H:%M}",
        "tooltip": true,
    },
    "custom/power": {
        "format": "\u23fb ",
    },
}
"""

LISTED = """[
    {
        "name": "main",
        "height": 40,
        "modules-right": ["clock"]
    }
]
"""


def plain(text: str) -> Any:
    stripped = re.sub(r"(?m)//.*$", "", text)
    stripped = re.sub(r",(\s*[\]}])", r"\1", stripped)
    return json.loads(stripped)


def test_bar_path_for_an_object_and_a_list():
    assert waybar.bar_path(SAMPLE) == ()
    assert waybar.bar_path(LISTED) == (0,)


def test_reads_modules_per_section():
    assert waybar.modules(SAMPLE, "modules-left") == ["hyprland/workspaces", "custom/media"]
    assert waybar.modules(SAMPLE, "modules-center") == ["hyprland/window"]
    assert waybar.modules(SAMPLE, "modules-right") == ["clock", "custom/power"]
    assert waybar.modules(SAMPLE, "modules-nope") == []


def test_reads_modules_from_a_list_config():
    assert waybar.modules(LISTED, "modules-right") == ["clock"]


def test_all_modules_keeps_configuration_order():
    assert waybar.all_modules(SAMPLE) == [
        "hyprland/workspaces",
        "custom/media",
        "hyprland/window",
        "clock",
        "custom/power",
    ]


def test_reads_module_options():
    assert waybar.module_options(SAMPLE, "clock") == {"format": "{:%H:%M}", "tooltip": True}
    assert waybar.module_options(SAMPLE, "ghost") == {}


def test_reads_bar_options_without_the_module_lists():
    options = waybar.bar_options(SAMPLE)
    assert options == {"layer": "top", "height": 30}


def test_set_option_keeps_comments_and_other_members():
    text = waybar.set_option(SAMPLE, "clock", "tooltip", False)
    assert "// top bar" in text
    assert "// scratch" in text
    assert plain(text)["clock"] == {"format": "{:%H:%M}", "tooltip": False}


def test_set_option_adds_a_new_key():
    text = waybar.set_option(SAMPLE, "clock", "interval", 60)
    assert plain(text)["clock"]["interval"] == 60
    assert plain(text)["clock"]["tooltip"] is True


def test_set_option_creates_the_module_entry():
    text = waybar.set_option(SAMPLE, "tray", "icon-size", 18)
    assert plain(text)["tray"] == {"icon-size": 18}
    assert "// top bar" in text


def test_set_option_reports_a_broken_config():
    with pytest.raises(jsonc.JsoncError):
        waybar.set_option('"not an object"', "clock", "format", "x")


def test_remove_option_leaves_the_rest_alone():
    text = waybar.remove_option(SAMPLE, "clock", "tooltip")
    assert plain(text)["clock"] == {"format": "{:%H:%M}"}
    assert waybar.remove_option(text, "clock", "format") == waybar.remove_option(
        text, "clock", "format"
    )


def test_add_and_remove_module():
    added = waybar.add_module(SAMPLE, "modules-right", "tray")
    assert waybar.modules(added, "modules-right") == ["clock", "custom/power", "tray"]
    assert "// scratch" in added
    removed = waybar.remove_module(added, "modules-right", "clock")
    assert waybar.modules(removed, "modules-right") == ["custom/power", "tray"]


def test_add_module_is_idempotent():
    assert waybar.add_module(SAMPLE, "modules-center", "hyprland/window") == SAMPLE


def test_remove_module_ignores_unknown_names():
    assert waybar.remove_module(SAMPLE, "modules-center", "ghost") == SAMPLE


def test_add_module_reports_a_missing_section():
    with pytest.raises(jsonc.JsoncError):
        waybar.add_module('{"height": 30}', "modules-right", "clock")


def test_option_specs_covers_namespaced_and_custom_modules():
    workspaces = waybar.option_specs("hyprland/workspaces")
    assert "format" in workspaces
    assert waybar.option_specs("custom/power")["format"][0] == "string"
    assert waybar.option_specs("ghost") == {}


def test_widget_kind_maps_man_page_types():
    assert waybar.widget_kind("bool") == "bool"
    assert waybar.widget_kind("integer") == "number"
    assert waybar.widget_kind("integer or float") == "number"
    assert waybar.widget_kind("string") == "string"
    assert waybar.widget_kind("array") == "json"
    assert waybar.widget_kind("") == "string"


def test_module_names_use_slashes_for_namespaces():
    names = waybar.module_names()
    assert "hyprland/workspaces" in names
    assert "hyprland-workspaces" not in names
    assert "power-profiles-daemon" in names
    assert "idle-inhibitor" in names


def test_decode_parses_json_values():
    assert waybar.decode('["a", "b"]') == ["a", "b"]
    with pytest.raises(json.JSONDecodeError):
        waybar.decode("not json")


def test_config_path_prefers_the_user_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(waybar, "SYSTEM_DIR", tmp_path / "etc")
    assert waybar.config_path() == tmp_path / "waybar" / "config.jsonc"
    assert waybar.user_config_path() == tmp_path / "waybar" / "config.jsonc"
    directory = tmp_path / "waybar"
    directory.mkdir()
    (directory / "config.jsonc").write_text(SAMPLE)
    assert waybar.config_path() == directory / "config.jsonc"
    assert waybar.user_config_path() == directory / "config.jsonc"


def test_config_path_falls_back_to_the_system_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(waybar, "SYSTEM_DIR", tmp_path / "etc")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "config.jsonc").write_text(SAMPLE)
    assert waybar.config_path() == tmp_path / "etc" / "config.jsonc"
    assert waybar.user_config_path() == tmp_path / "waybar" / "config.jsonc"
    assert waybar.default_document() == SAMPLE


def test_minimal_config_parses():
    assert plain(waybar.MINIMAL_CONFIG)["modules-right"] == ["clock", "custom/power"]


def test_module_reference_parses_for_every_module():
    for name in waybar.module_names():
        specs = waybar.option_specs(name)
        assert specs, name
        for kind, _, description in specs.values():
            assert waybar.widget_kind(kind) in ("bool", "number", "string", "json")
            assert isinstance(description, str)
