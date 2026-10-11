"""Sharded write-path tests.

When the user runs a modular Lua config (``hyprland.lua`` requiring
``modules/*.lua``) hyprmod must not keep a second config that silently
overrides the user's own modules. Instead of appending an include for its
canonical managed file, it splices each feature's generated Lua into the
module that owns it, wrapped in sentinel comments so the next save can
replace or drop the block.

These tests cover the write path (routing, replacement, stale removal) and
the ownership bookkeeping that lets the rest of hyprmod tell hyprmod's own
lines apart from the user's.
"""

import pytest
from hyprland_config import load_any

from hyprmod.core import config, setup
from hyprmod.core.config import ConfigSections
from hyprmod.core.external import load_external_keyword_entries

SHARD_MODULES = (
    "env",
    "cursor",
    "input",
    "decorations",
    "layouts",
    "misc",
    "monitor",
    "binds",
    "rules",
    "autostart",
)


@pytest.fixture
def sharded(tmp_path, monkeypatch):
    """A modular Lua-mode setup: hyprland.lua + a populated modules/ dir."""
    hypr_dir = tmp_path / "hypr"
    modules = hypr_dir / "modules"
    modules.mkdir(parents=True)
    (hypr_dir / "hyprland.lua").write_text(
        "\n".join(f'require "modules.{name}"' for name in SHARD_MODULES) + "\n"
    )
    for name in SHARD_MODULES:
        (modules / f"{name}.lua").write_text(f"-- user {name} module\n")

    monkeypatch.setattr("hyprland_config.default_config_dir", lambda: hypr_dir)
    config.set_managed_path(hypr_dir / "hyprland-gui")
    yield hypr_dir / "hyprland.lua", modules
    config.set_managed_path(None)


def _block(module_text: str) -> str:
    """Return the body inside hyprmod's sentinel comments, or ""."""
    begin = module_text.find("-- >>> hyprmod:begin")
    if begin == -1:
        return ""
    end = module_text.find("-- <<< hyprmod:end", begin)
    return module_text[begin:end]


class TestActiveShards:
    def test_detected_for_modular_lua_config(self, sharded) -> None:
        shards = config.active_shards()
        assert shards is not None
        assert shards["env"].name == "env.lua"
        assert shards["input"].parent.name == "modules"

    def test_none_without_modules_dir(self, tmp_path, monkeypatch) -> None:
        hypr_dir = tmp_path / "hypr"
        hypr_dir.mkdir()
        (hypr_dir / "hyprland.lua").touch()
        monkeypatch.setattr("hyprland_config.default_config_dir", lambda: hypr_dir)
        config.set_managed_path(hypr_dir / "hyprland-gui")
        try:
            assert config.active_shards() is None
        finally:
            config.set_managed_path(None)


class TestWriteRouting:
    def test_each_feature_lands_in_its_module(self, sharded) -> None:
        entrypoint, modules = sharded
        config.write_all(
            {"input:sensitivity": "-0.5", "general:gaps_in": "5", "misc:focus_on_activate": "true"},
            ConfigSections(
                binds=["bind = SUPER, Q, exec, kitty"],
                monitors=["monitor = DP-1, highrr, auto, auto"],
                env=["env = GTK_THEME, Adwaita:dark", "env = XCURSOR_SIZE, 24"],
                exec_=["exec-once = waybar"],
                window_rules=["windowrule = float, class:^(x)$"],
            ),
        )
        assert "input = {" in _block((modules / "input.lua").read_text())
        assert "general = {" in _block((modules / "decorations.lua").read_text())
        assert "misc = {" in _block((modules / "misc.lua").read_text())
        assert "hl.bind" in _block((modules / "binds.lua").read_text())
        assert "hl.monitor" in _block((modules / "monitor.lua").read_text())
        assert "hl.window_rule" in _block((modules / "rules.lua").read_text())
        # exec-once is emitted as a hyprland.start handler.
        assert "waybar" in _block((modules / "autostart.lua").read_text())
        # env vars split: cursor-related ones go to the cursor module.
        assert "GTK_THEME" in _block((modules / "env.lua").read_text())
        assert "XCURSOR_SIZE" in _block((modules / "cursor.lua").read_text())

    def test_user_lines_are_preserved(self, sharded) -> None:
        _entrypoint, modules = sharded
        config.write_all({"input:sensitivity": "-0.5"}, ConfigSections())
        text = (modules / "input.lua").read_text()
        assert "-- user input module" in text
        assert text.count("-- >>> hyprmod:begin") == 1

    def test_second_write_replaces_and_drops_stale_blocks(self, sharded) -> None:
        _entrypoint, modules = sharded
        config.write_all(
            {"input:sensitivity": "-0.5", "general:gaps_in": "5"},
            ConfigSections(env=["env = GTK_THEME, Adwaita:dark"]),
        )
        config.write_all({"input:sensitivity": "-1.0"}, ConfigSections())

        input_block = _block((modules / "input.lua").read_text())
        assert "-1.0" in input_block and "-0.5" not in input_block
        # Features absent from the second save lose their block entirely.
        assert _block((modules / "decorations.lua").read_text()) == ""
        assert _block((modules / "env.lua").read_text()) == ""
        assert (modules / "input.lua").read_text().count("-- >>> hyprmod:begin") == 1

    def test_tree_parses_after_splice(self, sharded) -> None:
        entrypoint, _modules = sharded
        config.write_all({"input:sensitivity": "-0.5"}, ConfigSections())
        doc = load_any(entrypoint, follow_sources=True, lenient=True)
        keys = [getattr(line, "full_key", "") for _doc, line in doc.iter_lines(recursive=True)]
        assert "input:sensitivity" in keys


class TestOwnershipBookkeeping:
    def test_managed_counts_exclude_external(self, sharded) -> None:
        entrypoint, modules = sharded
        (modules / "binds.lua").write_text('hl.bind("SUPER+W", hl.dsp.exec_cmd("useronly"))\n')
        config.write_all(
            {},
            ConfigSections(binds=["bind = SUPER, Q, exec, guionly"]),
        )
        owned = config.managed_keyword_counts()
        assert owned[("bind", "SUPER, Q, exec, guionly")] == 1

        external = load_external_keyword_entries(entrypoint, config.managed_path(), ("bind",))
        values = [entry.value for entry in external]
        assert "SUPER, Q, exec, guionly" not in values  # hyprmod's own line
        assert "SUPER, W, exec, useronly" in values  # the user's line survives


class TestSetupSkipped:
    def test_needs_setup_false_when_shards_active(self, sharded) -> None:
        assert setup.needs_setup() is False
