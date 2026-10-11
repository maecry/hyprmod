import json
import re
from typing import Any

import pytest

from hyprmod.core import jsonc

SAMPLE = """{
    // the bar itself
    "height": 30,
    "modules-right": [
        "clock",
        "custom/power", // the power button
    ],
    "empty": {},
    "custom/power": {
        "format": "\u23fb ",
        "tooltip": false,
        "menu-actions": {
            "logout": "hyprshutdown",
        },
    },
}
"""


def plain(text: str) -> Any:
    """Parse ``text`` as strict JSON, ignoring the comments waybar allows."""
    stripped = re.sub(r"(?m)//.*$", "", text)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
    stripped = re.sub(r",(\s*[\]}])", r"\1", stripped)
    return json.loads(stripped)


def test_reads_nested_values():
    document = jsonc.Document(SAMPLE)
    assert document.get(("height",)) == 30
    assert document.get(("modules-right", 1)) == "custom/power"
    assert document.get(("custom/power", "menu-actions", "logout")) == "hyprshutdown"
    assert document.get(("custom/power", "format")) == "\u23fb "
    assert document.get(("missing",)) is None
    assert document.get(("height", "deeper")) is None


def test_replaces_value_and_keeps_comments():
    text = jsonc.Document(SAMPLE).replace(("height",), 40).text
    assert "// the bar itself" in text
    assert "// the power button" in text
    assert plain(text)["height"] == 40


def test_replaces_nested_value():
    text = jsonc.Document(SAMPLE).replace(("custom/power", "tooltip"), True).text
    assert plain(text)["custom/power"]["tooltip"] is True
    assert "// the power button" in text


def test_put_adds_member_to_populated_object():
    text = jsonc.Document(SAMPLE).put(("custom/power",), "on-click", "hyprshutdown").text
    parsed = plain(text)
    assert parsed["custom/power"]["on-click"] == "hyprshutdown"
    assert parsed["custom/power"]["tooltip"] is False
    assert "// the power button" in text


def test_put_adds_member_to_empty_object():
    text = jsonc.Document(SAMPLE).put(("empty",), "interval", 5).text
    assert plain(text)["empty"] == {"interval": 5}
    assert '"empty": {\n        "interval": 5\n    }' in text


def test_put_overwrites_existing_member():
    text = jsonc.Document(SAMPLE).put(("custom/power",), "format", "X").text
    assert plain(text)["custom/power"]["format"] == "X"


def test_put_handles_trailing_comma():
    text = jsonc.Document(SAMPLE).put(("custom/power", "menu-actions"), "lock", "hyprlock").text
    actions = plain(text)["custom/power"]["menu-actions"]
    assert actions == {"logout": "hyprshutdown", "lock": "hyprlock"}


def test_drop_middle_member():
    text = jsonc.Document(SAMPLE).drop(("custom/power",), "tooltip").text
    assert "tooltip" not in plain(text)["custom/power"]
    assert plain(text)["custom/power"]["format"] == "\u23fb "


def test_drop_last_member_leaves_no_trailing_comma():
    text = jsonc.Document(SAMPLE).drop(("custom/power", "menu-actions"), "logout").text
    assert plain(text)["custom/power"]["menu-actions"] == {}
    assert "logout" not in text


def test_drop_only_member():
    text = jsonc.Document('{\n    "a": 1\n}\n').drop((), "a").text
    assert plain(text) == {}


def test_append_adds_array_item():
    text = jsonc.Document(SAMPLE).append(("modules-right",), "tray").text
    assert plain(text)["modules-right"] == ["clock", "custom/power", "tray"]


def test_append_to_empty_array():
    document = jsonc.Document('{\n    "modules-right": []\n}\n')
    assert plain(document.append(("modules-right",), "clock").text)["modules-right"] == ["clock"]


def test_remove_at_drops_item():
    text = jsonc.Document(SAMPLE).remove_at(("modules-right",), 0).text
    assert plain(text)["modules-right"] == ["custom/power"]


def test_remove_at_last_item():
    text = jsonc.Document('{"a": ["x", "y"]}').remove_at(("a",), 1).text
    assert plain(text)["a"] == ["x"]


def test_round_trip_is_byte_identical():
    document = jsonc.Document(SAMPLE)
    assert document.text == SAMPLE


def test_rejects_broken_input():
    with pytest.raises(jsonc.JsoncError):
        jsonc.Document('{"a": }')


def test_rejects_missing_path():
    with pytest.raises(jsonc.JsoncError):
        jsonc.Document(SAMPLE).replace(("nope",), 1)
    with pytest.raises(jsonc.JsoncError):
        jsonc.Document(SAMPLE).put(("height",), "a", 1)
    with pytest.raises(jsonc.JsoncError):
        jsonc.Document(SAMPLE).drop((), "nope")
    with pytest.raises(jsonc.JsoncError):
        jsonc.Document(SAMPLE).remove_at(("modules-right",), 9)


def test_preserves_indentation_of_nested_blocks():
    text = jsonc.Document(SAMPLE).put(("custom/power", "menu-actions"), "reboot", "reboot").text
    assert '            "logout": "hyprshutdown",\n            "reboot": "reboot"' in text
