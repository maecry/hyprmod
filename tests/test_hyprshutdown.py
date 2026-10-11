import json
import re
from typing import Any

from hyprmod.core import hyprshutdown


def test_bare_command():
    assert hyprshutdown.command() == "hyprshutdown"


def test_virtual_terminal_is_omitted_at_zero():
    assert hyprshutdown.command(vt=0) == "hyprshutdown"
    assert hyprshutdown.command(vt=2) == "hyprshutdown --vt 2"


def test_top_label_is_quoted():
    assert hyprshutdown.command(top_label="Shutting down...") == (
        "hyprshutdown --top-label 'Shutting down...'"
    )


def test_post_command_is_quoted_as_one_argument():
    assert hyprshutdown.command(post_cmd="shutdown -P 0") == (
        "hyprshutdown --post-cmd 'shutdown -P 0'"
    )


def test_blank_values_are_dropped():
    assert hyprshutdown.command(top_label="   ", post_cmd="\t") == "hyprshutdown"


def test_quotes_in_values_are_escaped():
    assert hyprshutdown.command(top_label="it's") == "hyprshutdown --top-label 'it'\\''s'"


def test_every_flag_together():
    assert hyprshutdown.command(2, "Restarting...", "reboot") == (
        "hyprshutdown --vt 2 --top-label 'Restarting...' --post-cmd 'reboot'"
    )


def test_is_installed_is_a_bool():
    assert isinstance(hyprshutdown.is_installed(), bool)


SAMPLE = """{
    // keep me
    "height": 30,
    "modules-right": ["clock"]
}
"""


def plain(text: str) -> Any:
    return json.loads(re.sub(r"(?m)//.*$", "", text))


def test_set_bar_option_updates_in_place():
    from hyprmod.core import waybar

    text = waybar.set_bar_option(SAMPLE, "height", 44)
    assert plain(text)["height"] == 44
    assert plain(text)["modules-right"] == ["clock"]
    assert "// keep me" in text


def test_set_bar_option_adds_a_missing_key():
    from hyprmod.core import waybar

    text = waybar.set_bar_option(SAMPLE, "spacing", 8)
    assert plain(text)["spacing"] == 8
    assert "// keep me" in text
