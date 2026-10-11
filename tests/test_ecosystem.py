"""Tests for the companion-tool config editor in ``hyprmod.core.ecosystem``."""

from pathlib import Path

import pytest

from hyprmod.core import ecosystem

HYPRIDLE_SAMPLE = """\
# my own config
general {
    lock_cmd = hyprlock   # keep this comment
    ignore_dbus_inhibit = false
}

listener {
    timeout = 300
    on-timeout = hyprlock
}

listener {
    timeout = 600
}

auth {
    pam {
        enabled = true
    }
}
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "hypridle.conf"
    path.write_text(HYPRIDLE_SAMPLE)
    return path


@pytest.fixture
def editor(config_file: Path) -> ecosystem.ToolConfig:
    return ecosystem.ToolConfig(config_file)


class TestToolSpecs:
    def test_slugs_and_filenames_are_unique(self):
        slugs = [tool.slug for tool in ecosystem.TOOLS]
        names = [tool.config_name for tool in ecosystem.TOOLS]
        assert len(set(slugs)) == len(slugs)
        assert len(set(names)) == len(names)
        assert all(name.endswith(".conf") for name in names)

    def test_directory_matches_slug_lookup(self):
        assert set(ecosystem.TOOLS_BY_SLUG) == {tool.slug for tool in ecosystem.TOOLS}

    def test_option_keys_are_unique_within_a_tool(self):
        for tool in ecosystem.TOOLS:
            keys = [group.full_key(field) for group in tool.groups for field in group.fields]
            assert len(set(keys)) == len(keys), tool.slug

    def test_repeatable_groups_are_flat_blocks(self):
        # The writer targets a repeatable block by (path, index) and matches
        # option keys directly, which only holds for single-segment paths.
        for tool in ecosystem.TOOLS:
            for group in tool.groups:
                if group.repeatable:
                    assert len(group.path) == 1, (tool.slug, group.key)

    def test_every_field_kind_has_a_renderer(self):
        kinds = {
            field.kind
            for tool in ecosystem.TOOLS
            for group in tool.groups
            for field in group.fields
        }
        assert kinds == {"bool", "int", "float", "str"}

    def test_option_lookup_by_full_key(self):
        assert ecosystem.HYPRIDLE.option("general:lock_cmd") is not None
        assert ecosystem.HYPRIDLE.option("general:nope") is None


class TestSnapshot:
    def test_scalars_use_the_last_assignment(self, editor):
        values = editor.snapshot().values
        assert values["general:lock_cmd"] == "hyprlock"
        assert values["listener:timeout"] == "600"

    def test_inline_comment_is_not_part_of_the_value(self, editor):
        assert editor.snapshot().values["general:ignore_dbus_inhibit"] == "false"

    def test_repeated_blocks_stay_separate(self, editor):
        blocks = editor.snapshot().blocks[("listener",)]
        assert blocks == [{"timeout": "300", "on-timeout": "hyprlock"}, {"timeout": "600"}]

    def test_nested_block_is_not_reported_as_its_parent(self, editor):
        blocks = editor.snapshot().blocks
        assert blocks[("auth", "pam")] == [{"enabled": "true"}]
        assert ("auth",) not in blocks

    def test_missing_file_reads_empty(self, tmp_path):
        snapshot = ecosystem.ToolConfig(tmp_path / "nope.conf").snapshot()
        assert snapshot.values == {}
        assert snapshot.blocks == {}


class TestSectionSpans:
    def test_commented_block_is_ignored(self):
        assert ecosystem._section_spans(["# general {", "gaps_in = 5"]) == []

    def test_stray_close_brace_is_ignored(self):
        assert ecosystem._section_spans(["}", "gaps_in = 5"]) == []

    def test_nested_paths_are_reported(self):
        spans = ecosystem._section_spans(["auth {", "    pam {", "    }", "}"])
        assert [span[0] for span in spans] == [("auth", "pam"), ("auth",)]


class TestSetValues:
    def test_replaces_in_place_and_keeps_the_comment(self, editor, config_file):
        editor.set_values({"general:lock_cmd": "pidof hyprlock || hyprlock"})
        text = config_file.read_text()
        assert "    lock_cmd = pidof hyprlock || hyprlock # keep this comment\n" in text
        assert "hyprlock   # keep this comment" not in text

    def test_inserts_a_new_key_into_the_existing_block(self, editor, config_file):
        editor.set_values({"general:on_unlock_cmd": "notify-send hi"})
        text = config_file.read_text()
        assert "    ignore_dbus_inhibit = false\n    on_unlock_cmd = notify-send hi\n}" in text

    def test_creates_a_missing_block(self, editor, config_file):
        editor.set_values({"auth:fingerprint:enabled": "true"})
        assert (
            "auth {\n    fingerprint {\n        enabled = true\n    }\n}" in config_file.read_text()
        )

    def test_appends_a_top_level_key(self, editor, config_file):
        editor.set_values({"max-gamma": "80"})
        assert config_file.read_text().endswith("max-gamma = 80\n")

    def test_writes_into_an_empty_file(self, tmp_path):
        editor = ecosystem.ToolConfig(tmp_path / "hyprsunset.conf")
        editor.set_values({"max-gamma": "90"})
        assert editor.read_text() == "max-gamma = 90\n"

    def test_unrelated_lines_survive(self, editor, config_file):
        editor.set_values({"general:lock_cmd": "hyprlock"})
        assert config_file.read_text().startswith("# my own config\ngeneral {\n")

    def test_result_still_parses(self, editor, config_file):
        editor.set_values({"general:new_key": "1", "auth:fingerprint:enabled": "true"})
        assert editor.snapshot().values["general:new_key"] == "1"
        assert editor.snapshot().values["auth:fingerprint:enabled"] == "true"


class TestBlocks:
    def test_add_block_appends(self, editor):
        editor.add_block(("listener",), {"timeout": "900", "on-timeout": "systemctl suspend"})
        snapshot = editor.snapshot()
        assert snapshot.blocks[("listener",)][-1] == {
            "timeout": "900",
            "on-timeout": "systemctl suspend",
        }

    def test_add_block_creates_nested_blocks(self, editor):
        editor.add_block(("profile",), {"time": "20:00"})
        assert ("profile",) in editor.snapshot().blocks

    def test_remove_block_drops_only_that_index(self, editor):
        editor.remove_block(("listener",), 0)
        assert editor.snapshot().blocks[("listener",)] == [{"timeout": "600"}]

    def test_remove_block_out_of_range_is_a_no_op(self, editor, config_file):
        before = config_file.read_text()
        editor.remove_block(("listener",), 9)
        assert config_file.read_text() == before

    def test_set_block_value_targets_the_right_block(self, editor):
        editor.set_block_value(("listener",), 0, "timeout", "120")
        assert editor.snapshot().blocks[("listener",)][0]["timeout"] == "120"
        assert editor.snapshot().blocks[("listener",)][1]["timeout"] == "600"

    def test_set_block_value_adds_a_missing_key(self, editor):
        editor.set_block_value(("listener",), 1, "on-timeout", "hyprlock")
        assert editor.snapshot().blocks[("listener",)][1]["on-timeout"] == "hyprlock"

    def test_set_block_value_keeps_the_comment(self, editor, config_file):
        editor.set_block_value(("general",), 0, "lock_cmd", "hyprlock")
        assert "# keep this comment" in config_file.read_text()


class TestDefaultDocument:
    @pytest.mark.parametrize("tool", ecosystem.TOOLS, ids=lambda tool: tool.slug)
    def test_parses_and_carries_the_defaults(self, tool, tmp_path):
        path = tmp_path / tool.config_name
        path.write_text(ecosystem.default_document(tool))
        values = ecosystem.ToolConfig(path).snapshot().values
        groups = [group for group in tool.groups if not group.repeatable]
        assert groups
        for group in groups:
            for field in group.fields:
                assert values[group.full_key(field)] == field.default, (tool.slug, field.key)

    def test_repeatable_blocks_are_left_out(self, tmp_path):
        path = tmp_path / "hypridle.conf"
        path.write_text(ecosystem.default_document(ecosystem.HYPRIDLE))
        assert ecosystem.ToolConfig(path).snapshot().blocks.get(("listener",), []) == []


class TestCommands:
    def test_install_command_needs_pacman(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _name: None)
        assert ecosystem.package_install_command(ecosystem.HYPRIDLE) is None

    def test_install_command_uses_pacman(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        command = ecosystem.package_install_command(ecosystem.HYPRLOCK)
        assert command == ["sudo", "pacman", "-S", "--needed", "hyprlock"]

    def test_terminal_command_prefers_the_configured_terminal(self, monkeypatch):
        monkeypatch.setenv("TERMINAL", "alacritty")
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        command = ecosystem.terminal_command(["sudo", "true"])
        assert command is not None
        assert command[:2] == ["alacritty", "-e"]

    def test_terminal_command_falls_back_to_a_known_terminal(self, monkeypatch):
        monkeypatch.delenv("TERMINAL", raising=False)
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/kitty" if name == "kitty" else None
        )
        command = ecosystem.terminal_command(["sudo", "true"])
        assert command is not None
        assert command[:2] == ["kitty", "-e"]

    def test_terminal_command_none_when_nothing_is_installed(self, monkeypatch):
        monkeypatch.delenv("TERMINAL", raising=False)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        assert ecosystem.terminal_command(["sudo", "true"]) is None
