"""Typed access to the config files of the hypr* companion tools.

Hypridle, hyprlock, hyprlauncher and hyprsunset each keep their own
Hyprlang file next to ``hyprland.conf``. HyprMod edits those files in
place: the tool's file stays the single source of truth, so hand-written
options, comments and any block HyprMod does not know about survive
untouched.

Values come from the parsed ``Assignment`` nodes, which carry real line
numbers for Hyprlang files. Block boundaries come from
:func:`_section_spans`, because the node type that marks a ``name { }``
block is not part of the ``hyprland_config`` public surface.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hyprland_config import Assignment, ParseError, atomic_write, default_config_dir, parse_string

# ---------------------------------------------------------------------------
# Option specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Field:
    """One typed option. ``default`` is text so it renders into the file as is."""

    key: str
    label: str
    kind: str
    default: str
    hint: str = ""
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True, slots=True)
class Group:
    """A block of related options.

    ``key`` is the section path (``""`` for top-level options, ``"auth:pam"``
    for a nested one). ``repeatable`` marks blocks a config may hold several
    times, like hypridle's ``listener`` or hyprlock's ``background``.
    """

    key: str
    label: str
    description: str
    fields: tuple[Field, ...]
    repeatable: bool = False

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self.key.split(":")) if self.key else ()

    def full_key(self, field: Field) -> str:
        return f"{self.key}:{field.key}" if self.key else field.key


@dataclass(frozen=True, slots=True)
class Tool:
    """A companion tool: where its binary, package and config file live."""

    slug: str
    label: str
    binary: str
    package: str
    config_name: str
    summary: str
    icon: str
    groups: tuple[Group, ...]
    restart_hint: str

    def config_path(self) -> Path:
        return default_config_dir() / self.config_name

    def is_installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def option(self, full_key: str) -> Field | None:
        for group in self.groups:
            for field in group.fields:
                if group.full_key(field) == full_key:
                    return field
        return None


def _bool(key: str, label: str, default: bool, hint: str = "") -> Field:
    return Field(key, label, "bool", "true" if default else "false", hint)


def _int(
    key: str,
    label: str,
    default: int,
    hint: str = "",
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Field:
    return Field(key, label, "int", str(default), hint, minimum, maximum)


def _float(
    key: str,
    label: str,
    default: float,
    hint: str = "",
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Field:
    return Field(key, label, "float", str(default), hint, minimum, maximum)


def _str(key: str, label: str, default: str = "", hint: str = "") -> Field:
    return Field(key, label, "str", default, hint)


HYPRIDLE = Tool(
    slug="hypridle",
    label="Hypridle",
    binary="hypridle",
    package="hypridle",
    config_name="hypridle.conf",
    summary=(
        "Runs commands after a period of inactivity, for example locking the "
        "screen. Hypridle only starts when this config exists."
    ),
    icon="alarm-symbolic",
    restart_hint="Run `hyprctl dispatch exec hypridle` after a big change.",
    groups=(
        Group(
            key="general",
            label="General",
            description="Commands run around locking and sleeping.",
            fields=(
                _str("lock_cmd", "Lock command", hint="Usually `pidof hyprlock || hyprlock`."),
                _str("unlock_cmd", "Unlock command"),
                _str("on_lock_cmd", "On lock", hint="Runs after the session was locked."),
                _str("on_unlock_cmd", "On unlock"),
                _str("before_sleep_cmd", "Before sleep", hint="Runs before the system suspends."),
                _str("after_sleep_cmd", "After sleep"),
                _bool(
                    "ignore_dbus_inhibit",
                    "Ignore D-Bus idle inhibitor",
                    False,
                    "Without this, video players keep the session awake through all listeners.",
                ),
                _bool("ignore_systemd_inhibit", "Ignore systemd idle inhibitor", False),
                _bool("ignore_wayland_inhibit", "Ignore Wayland idle inhibitor", False),
                _int(
                    "inhibit_sleep",
                    "Inhibit sleep",
                    2,
                    "0 keeps the system awake, 1 allows suspend, 2 decides automatically, "
                    "3 only when the lock notification arrives.",
                    minimum=0,
                    maximum=3,
                ),
            ),
        ),
        Group(
            key="listener",
            label="Listener",
            description="One inactivity timer and the command it fires.",
            repeatable=True,
            fields=(
                _int("timeout", "Timeout", 300, "Seconds of inactivity.", minimum=1),
                _str("on-timeout", "On timeout"),
                _str(
                    "on-resume", "On resume", hint="Runs when activity returns before the timeout."
                ),
                _str(
                    "condition_cmd",
                    "Condition",
                    hint="Checked through /bin/sh -c. Exit code 0 fires the timeout, "
                    "anything else defers it.",
                ),
                _int(
                    "condition_retry", "Condition retry", 0, "Seconds between re-checks.", minimum=0
                ),
                _bool(
                    "ignore_inhibit",
                    "Ignore inhibitors",
                    False,
                    "Lets this timer fire even while a video player holds an idle inhibitor.",
                ),
            ),
        ),
    ),
)

HYPRLOCK = Tool(
    slug="hyprlock",
    label="Hyprlock",
    binary="hyprlock",
    package="hyprlock",
    config_name="hyprlock.conf",
    summary=(
        "The screen locker. Hyprlock exits with an error when no config file is "
        "found, so create one before binding it to a key."
    ),
    icon="changes-prevent-symbolic",
    restart_hint="Changes apply the next time hyprlock starts.",
    groups=(
        Group(
            key="general",
            label="General",
            description="Session-wide behaviour.",
            fields=(
                _bool("hide_cursor", "Hide cursor", False),
                _bool("ignore_empty_input", "Ignore empty input", False),
                _bool("immediate_render", "Immediate render", False, "Skips the fade in."),
                _bool("text_trim", "Trim text", True),
                _int(
                    "fractional_scaling",
                    "Fractional scaling",
                    2,
                    "0 disables, 1 uses the output scale.",
                    minimum=0,
                    maximum=1,
                ),
                _int(
                    "screencopy_mode",
                    "Screencopy mode",
                    0,
                    "0 is CPU copy, 1 is DMABUF with permissions, 2 is DMABUF with a fallback.",
                    minimum=0,
                    maximum=2,
                ),
                _int(
                    "fail_timeout",
                    "Fail timeout",
                    2000,
                    "Milliseconds of shake after a bad password.",
                    minimum=0,
                ),
            ),
        ),
        Group(
            key="auth",
            label="Authentication",
            description="PAM and fingerprint settings.",
            fields=(
                _bool("pam:enabled", "Use PAM", True),
                _str("pam:module", "PAM module", "hyprlock"),
                _bool("fingerprint:enabled", "Use fingerprint", False),
                _str(
                    "fingerprint:ready_message",
                    "Fingerprint prompt",
                    "(Scan fingerprint to unlock)",
                ),
                _str(
                    "fingerprint:present_message",
                    "Fingerprint scan message",
                    "Scanning fingerprint",
                ),
                _int(
                    "fingerprint:retry_delay",
                    "Fingerprint retry delay",
                    250,
                    "Milliseconds.",
                    minimum=0,
                ),
            ),
        ),
        Group(
            key="animations",
            label="Animations",
            description="Fade transitions, driven by the global animation speed.",
            fields=(_bool("enabled", "Enable animations", True),),
        ),
        Group(
            key="background",
            label="Background",
            description="Draws a wallpaper or a flat colour behind the widgets.",
            repeatable=True,
            fields=(
                _str("monitor", "Monitor", hint="Empty means every monitor."),
                _str(
                    "path",
                    "Image path",
                    hint="`screenshot` uses the current desktop, empty uses the colour.",
                ),
                _str("color", "Fallback colour", "rgba(17, 17, 17, 1.0)"),
                _int("blur_passes", "Blur passes", 0, "0 disables blurring.", minimum=0),
                _int("blur_size", "Blur size", 7, minimum=0),
                _float("noise", "Noise", 0.0117),
                _float("contrast", "Contrast", 0.8916),
                _float("brightness", "Brightness", 0.8172),
                _int("zindex", "Z-index", -1),
            ),
        ),
        Group(
            key="input-field",
            label="Input field",
            description="The password prompt.",
            repeatable=True,
            fields=(
                _str("monitor", "Monitor", hint="Empty means every monitor."),
                _str("size", "Size", "400, 90"),
                _int("outline_thickness", "Outline thickness", 4, minimum=0),
                _float("dots_size", "Dot size", 0.25, minimum=0.001, maximum=0.8),
                _bool("dots_center", "Center dots", True),
                _int("rounding", "Rounding", -1, "-1 rounds completely."),
                _str("font_family", "Font family", "Noto Sans"),
                _str(
                    "placeholder_text",
                    "Placeholder",
                    "<i>Input Password...</i>",
                    "Supports Pango markup.",
                ),
                _bool("fade_on_empty", "Fade when empty", True),
                _int("fade_timeout", "Fade timeout", 2000, "Milliseconds.", minimum=0),
                _bool(
                    "hide_input", "Hide input", False, "Shows a shifting indicator instead of dots."
                ),
                _str("check_text", "Checking text", hint="Shown while the password is verified."),
            ),
        ),
        Group(
            key="label",
            label="Label",
            description="Text drawn over the lock screen, for example a clock.",
            repeatable=True,
            fields=(
                _str("monitor", "Monitor", hint="Empty means every monitor."),
                _str(
                    "text",
                    "Text",
                    hint="Supports Pango markup and the $TIME, $USER and $ATTEMPTS variables.",
                ),
                _str("color", "Colour", "rgba(200, 200, 200, 1.0)"),
                _int("font_size", "Font size", 16, minimum=1),
                _str("font_family", "Font family", "Noto Sans"),
                _str("position", "Position", hint="Offsets such as `0, 80`."),
                _str("halign", "Horizontal align", hint="left, center or right."),
                _str("valign", "Vertical align", hint="top, center or bottom."),
                _str("onclick", "On click", hint="Command to run when the label is clicked."),
                _int("zindex", "Z-index", 0),
            ),
        ),
    ),
)

HYPRLAUNCHER = Tool(
    slug="hyprlauncher",
    label="Hyprlauncher",
    binary="hyprlauncher",
    package="hyprlauncher",
    config_name="hyprlauncher.conf",
    summary=(
        "The application launcher. It always runs as a daemon, so this config "
        "controls how the window looks and which finders it offers."
    ),
    icon="system-search-symbolic",
    restart_hint="Run `hyprctl dispatch exec hyprlauncher -d` to apply changes.",
    groups=(
        Group(
            key="general",
            label="General",
            description="Window behaviour.",
            fields=(_bool("grab_focus", "Grab focus", True),),
        ),
        Group(
            key="cache",
            label="Cache",
            description="Usage history, stored in ~/.local/share/hyprlauncher.",
            fields=(_bool("enabled", "Remember usage", True),),
        ),
        Group(
            key="finders",
            label="Finders",
            description="Which result source is searched, and the prefixes that pick one directly.",
            fields=(
                _str("default_finder", "Default finder", "desktop"),
                _str("desktop_prefix", "Desktop prefix", hint="One character."),
                _str("unicode_prefix", "Unicode prefix", "."),
                _str("math_prefix", "Math prefix", "="),
                _str("font_prefix", "Font prefix", "'"),
                _str(
                    "desktop_launch_prefix",
                    "Desktop launch prefix",
                    hint="Prepended to launched apps, for example `uwsm app --`.",
                ),
                _bool("desktop_icons", "Desktop icons", True),
            ),
        ),
        Group(
            key="ui",
            label="Interface",
            description="Window geometry. Colours come from the hyprtoolkit theme.",
            fields=(_str("window_size", "Window size", "400 260"),),
        ),
    ),
)

HYPRSUNSET = Tool(
    slug="hyprsunset",
    label="Hyprsunset",
    binary="hyprsunset",
    package="hyprsunset",
    config_name="hyprsunset.conf",
    summary=(
        "Shifts the colour temperature of the screen. Profiles switch by time "
        "of day; without a config the tool starts at 6000K and never changes."
    ),
    icon="night-light-symbolic",
    restart_hint="Profiles apply on startup. `hyprctl hyprsunset profile` re-reads them.",
    groups=(
        Group(
            key="",
            label="Global",
            description="Applies to every profile.",
            fields=(
                _int(
                    "max-gamma",
                    "Max gamma",
                    100,
                    "Upper bound the gamma value is clamped to.",
                    minimum=0,
                    maximum=200,
                ),
            ),
        ),
        Group(
            key="profile",
            label="Profile",
            description="One colour temperature for a time of day.",
            repeatable=True,
            fields=(
                _str("time", "Time", "00:00", "24 hour HH:MM."),
                _int("temperature", "Temperature", 6000, "Kelvin.", minimum=1000, maximum=20000),
                _float("gamma", "Gamma", 1.0, minimum=0.0, maximum=2.0),
                _bool("identity", "Identity", False, "Shows the unmodified screen at this time."),
            ),
        ),
    ),
)

TOOLS: tuple[Tool, ...] = (HYPRIDLE, HYPRLOCK, HYPRLAUNCHER, HYPRSUNSET)

TOOLS_BY_SLUG: dict[str, Tool] = {tool.slug: tool for tool in TOOLS}

# ---------------------------------------------------------------------------
# Installing a missing tool
# ---------------------------------------------------------------------------

# First entry that exists wins. ``-e`` is how every one of these takes a
# command to run instead of an interactive shell.
_TERMINALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kitty", ("-e",)),
    ("foot", ("-e",)),
    ("alacritty", ("-e",)),
    ("wezterm", ("start", "--")),
    ("ghostty", ("-e",)),
    ("xterm", ("-e",)),
)


def terminal_command(argv: Sequence[str]) -> list[str] | None:
    """Wrap *argv* so it runs in a terminal window, or ``None`` if none is around."""
    candidates: list[tuple[str, tuple[str, ...]]] = []
    preferred = _preferred_terminal()
    if preferred is not None:
        candidates.append(preferred)
    candidates.extend(_TERMINALS)
    for name, prefix in candidates:
        if shutil.which(name):
            return [name, *prefix, *argv]
    return None


def _preferred_terminal() -> tuple[str, tuple[str, ...]] | None:
    """The user's ``$TERMINAL``, if it is set and installed."""
    name = os.environ.get("TERMINAL", "").strip()
    if not name or shutil.which(name) is None:
        return None
    return name, ("-e",)


def package_install_command(tool: Tool) -> list[str] | None:
    """The command that installs *tool*, or ``None`` when pacman is missing."""
    if shutil.which("pacman") is None:
        return None
    return ["sudo", "pacman", "-S", "--needed", tool.package]


def launch_in_terminal(argv: Sequence[str]) -> bool:
    """Open a terminal running *argv*. Returns False when no terminal was found."""
    wrapped = terminal_command(argv)
    if wrapped is None:
        return False
    subprocess.Popen(wrapped, start_new_session=True)
    return True


# ---------------------------------------------------------------------------
# Reading and writing one tool's config file
# ---------------------------------------------------------------------------

_OPEN_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<name>[A-Za-z0-9_.:-]+)[ \t]*\{$")
_CLOSE_RE = re.compile(r"^[ \t]*\}$")

Span = tuple[tuple[str, ...], int, int]


@dataclass(slots=True)
class Snapshot:
    """A read-only view of one config file.

    ``values`` holds every assignment by full key (last one wins, which
    matches how Hyprlang resolves duplicates). ``blocks`` holds the entries
    of each leaf block, so repeated blocks stay separate.
    """

    values: dict[str, str]
    blocks: dict[tuple[str, ...], list[dict[str, str]]]


def _section_spans(lines: Sequence[str]) -> list[Span]:
    """Return ``(path, open_index, close_index)`` for every ``name { }`` block."""
    spans: list[Span] = []
    stack: list[tuple[str, int]] = []
    for index, raw in enumerate(lines):
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        match = _OPEN_RE.match(line)
        if match is not None:
            stack.append((match.group("name"), index))
            continue
        if _CLOSE_RE.match(line) and stack:
            name, open_index = stack.pop()
            spans.append((tuple(entry[0] for entry in stack) + (name,), open_index, index))
    return spans


def _is_leaf(spans: Sequence[Span], path: tuple[str, ...]) -> bool:
    """True when no other block sits inside *path*, so its lines are all entries."""
    return not any(len(span[0]) > len(path) and span[0][: len(path)] == path for span in spans)


def _last_span(spans: Sequence[Span], path: tuple[str, ...]) -> Span | None:
    for span in reversed(spans):
        if span[0] == path:
            return span
    return None


class ToolConfig:
    """Line editor for one companion tool's Hyprlang file.

    Every write re-reads the file, so a change made in an editor outside
    HyprMod is never clobbered by a stale in-memory copy.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def read_text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def snapshot(self) -> Snapshot:
        """Parse the file into scalar values and per-block entries."""
        text = self.read_text()
        lines = text.splitlines()
        spans = _section_spans(lines)
        by_lineno: dict[int, Assignment] = {}
        for node in _assignments(text):
            if node.lineno:
                by_lineno[node.lineno] = node
        values = {node.full_key: node.value for node in by_lineno.values()}
        blocks: dict[tuple[str, ...], list[dict[str, str]]] = {}
        for path, open_index, close_index in spans:
            if not _is_leaf(spans, path):
                continue
            entry: dict[str, str] = {}
            for lineno in range(open_index + 2, close_index + 1):
                node = by_lineno.get(lineno)
                if node is not None:
                    entry[node.key] = node.value
            blocks.setdefault(path, []).append(entry)
        return Snapshot(values, blocks)

    def set_values(self, updates: Mapping[str, str]) -> None:
        """Set scalar options, creating blocks and keys that do not exist yet."""
        text = _normalized(self.read_text())
        lines = text.splitlines(keepends=True)
        existing = {node.full_key: node for node in _assignments(text) if node.lineno}
        spans = _section_spans(text.splitlines())
        additions: dict[int, list[str]] = {}
        for full_key, value in updates.items():
            node = existing.get(full_key)
            if node is not None:
                lines[node.lineno - 1] = _render(
                    lines[node.lineno - 1], full_key, value, node.inline_comment
                )
                continue
            path = tuple(full_key.split(":"))[:-1]
            key = full_key.rpartition(":")[2]
            span = _last_span(spans, path)
            if not path or span is None:
                additions.setdefault(len(lines), []).extend(self._block_lines(path, {key: value}))
                continue
            indent = _indent(lines[span[1]]) + "    "
            additions.setdefault(span[2], []).append(f"{indent}{key} = {value}\n")
        self._splice(lines, additions)

    def set_block_value(self, path: tuple[str, ...], index: int, key: str, value: str) -> None:
        """Set one option inside the *index*-th ``path { }`` block.

        shortcut: a nested block inside *path* would share key names with its
        parent, so this only targets flat blocks. Every repeatable group in
        :data:`TOOLS` is flat; revisit if one gains a sub-block.
        """
        text = _normalized(self.read_text())
        lines = text.splitlines(keepends=True)
        matches = [span for span in _section_spans(text.splitlines()) if span[0] == path]
        if index >= len(matches):
            return
        _, open_index, close_index = matches[index]
        nodes = {node.lineno: node for node in _assignments(text)}
        for lineno in range(open_index + 2, close_index + 1):
            node = nodes.get(lineno)
            if node is not None and node.key == key:
                lines[lineno - 1] = _render(lines[lineno - 1], key, value, node.inline_comment)
                self.write("".join(lines))
                return
        indent = _indent(lines[open_index]) + "    "
        lines.insert(close_index, f"{indent}{key} = {value}\n")
        self.write("".join(lines))

    def add_block(self, path: tuple[str, ...], entries: Mapping[str, str]) -> None:
        """Append a new ``path { entries }`` block to the file."""
        text = _normalized(self.read_text())
        lines = text.splitlines(keepends=True)
        self._splice(lines, {len(lines): ["\n", *self._block_lines(path, entries)]})

    def remove_block(self, path: tuple[str, ...], index: int) -> None:
        """Delete the *index*-th ``path { }`` block."""
        text = _normalized(self.read_text())
        lines = text.splitlines(keepends=True)
        matches = [span for span in _section_spans(text.splitlines()) if span[0] == path]
        if index >= len(matches):
            return
        _, open_index, close_index = matches[index]
        stop = close_index + 1
        if stop < len(lines) and not lines[stop].strip():
            stop += 1
        del lines[open_index:stop]
        self.write("".join(lines))

    def _block_lines(self, path: Sequence[str], entries: Mapping[str, str]) -> list[str]:
        lines = [f"{'    ' * depth}{name} {{\n" for depth, name in enumerate(path)]
        indent = "    " * len(path)
        lines.extend(f"{indent}{key} = {value}\n" for key, value in entries.items())
        lines.extend(f"{'    ' * depth}}}\n" for depth in range(len(path) - 1, -1, -1))
        return lines

    def _splice(self, lines: list[str], additions: Mapping[int, Sequence[str]]) -> None:
        for index in sorted(additions, reverse=True):
            lines[index:index] = list(additions[index])
        self.write("".join(lines))

    def write(self, text: str) -> None:
        """Replace the file's contents, creating the directory when needed."""
        atomic_write(self.path, text)


def _assignments(text: str) -> list[Assignment]:
    """Every assignment in *text*, or none when it cannot be parsed at all."""
    try:
        document = parse_string(text, lenient=True)
    except ParseError:
        return []
    return [node for node in document.lines if isinstance(node, Assignment)]


def _normalized(text: str) -> str:
    return text if text.endswith("\n") or not text else text + "\n"


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _render(old: str, full_key: str, value: str, inline_comment: str) -> str:
    """Rewrite one option line, keeping its indentation and trailing comment."""
    key = full_key.rpartition(":")[2]
    comment = f" {inline_comment}" if inline_comment else ""
    return f"{_indent(old)}{key} = {value}{comment}\n"


def default_document(tool: Tool) -> str:
    """Render *tool*'s non-repeatable options at their documented defaults.

    Repeated blocks are left out on purpose: a listener or a widget needs a
    meaningful command or position, which the user picks on the page.
    """
    lines = [f"# {tool.config_name} managed by HyprMod\n"]
    for group in tool.groups:
        if group.repeatable:
            continue
        if not group.key:
            lines.extend(f"{field.key} = {field.default}\n" for field in group.fields)
            lines.append("\n")
            continue
        lines.append(f"{group.key} {{\n")
        lines.extend(f"    {field.key} = {field.default}\n" for field in group.fields)
        lines.append("}\n\n")
    return "".join(lines)
