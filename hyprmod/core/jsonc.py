"""Comment preserving reader and editor for waybar's JSONC config.

Waybar configuration files are JSON with ``//`` comments and trailing commas.
HyprMod edits them in place so a user's comments and layout survive a save,
which a round trip through :mod:`json` would destroy.
"""

from __future__ import annotations

import json

_WHITESPACE = " \t\r\n"
_DELIMITERS = ",}]"


class JsoncError(ValueError):
    """Raised when the text is not valid JSONC."""


def _skip(text: str, index: int) -> int:
    """Return the index of the next character that is not whitespace or a comment."""
    length = len(text)
    while index < length:
        char = text[index]
        if char in _WHITESPACE:
            index += 1
        elif text.startswith("//", index):
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
        elif text.startswith("/*", index):
            closing = text.find("*/", index + 2)
            index = length if closing < 0 else closing + 2
        else:
            break
    return index


def _line_indent(text: str, index: int) -> str:
    """Return the leading whitespace of the line holding ``index``, if any."""
    start = text.rfind("\n", 0, index) + 1
    prefix = text[start:index]
    return prefix if prefix.strip() == "" else ""


def _scan_string(text: str, index: int) -> int:
    """Return the index just past the string literal starting at ``index``."""
    index += 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
        elif char == '"':
            return index + 1
        else:
            index += 1
    raise JsoncError("unterminated string")


class Node:
    """A parsed JSONC value, remembering where it sits in the source text."""

    __slots__ = ("kind", "start", "end", "members", "items")

    def __init__(self, kind: str, start: int, end: int) -> None:
        self.kind = kind
        self.start = start
        self.end = end
        self.members: list[tuple[str, int, Node]] = []
        self.items: list[Node] = []

    def member(self, key: str) -> tuple[str, int, Node] | None:
        for entry in self.members:
            if entry[0] == key:
                return entry
        return None


def _parse_value(text: str, index: int) -> tuple[Node, int]:
    index = _skip(text, index)
    if index >= len(text):
        raise JsoncError("unexpected end of input")
    char = text[index]
    if char == "{":
        return _parse_object(text, index)
    if char == "[":
        return _parse_array(text, index)
    if char == '"':
        end = _scan_string(text, index)
        return Node("scalar", index, end), end
    end = index
    while end < len(text) and text[end] not in _WHITESPACE and text[end] not in _DELIMITERS:
        end += 1
    if end == index:
        raise JsoncError(f"unexpected character {char!r}")
    return Node("scalar", index, end), end


def _parse_object(text: str, start: int) -> tuple[Node, int]:
    node = Node("object", start, start)
    index = _skip(text, start + 1)
    if index < len(text) and text[index] == "}":
        node.end = index + 1
        return node, node.end
    while True:
        index = _skip(text, index)
        if index >= len(text) or text[index] != '"':
            raise JsoncError("expected an object key")
        key_start = index
        key_end = _scan_string(text, index)
        key = json.loads(text[key_start:key_end])
        index = _skip(text, key_end)
        if index >= len(text) or text[index] != ":":
            raise JsoncError("expected ':' after an object key")
        value, index = _parse_value(text, index + 1)
        node.members.append((key, key_start, value))
        index = _skip(text, index)
        if index < len(text) and text[index] == ",":
            index = _skip(text, index + 1)
            if index < len(text) and text[index] == "}":
                break
            continue
        break
    index = _skip(text, index)
    if index >= len(text) or text[index] != "}":
        raise JsoncError("expected '}'")
    node.end = index + 1
    return node, node.end


def _parse_array(text: str, start: int) -> tuple[Node, int]:
    node = Node("array", start, start)
    index = _skip(text, start + 1)
    if index < len(text) and text[index] == "]":
        node.end = index + 1
        return node, node.end
    while True:
        value, index = _parse_value(text, index)
        node.items.append(value)
        index = _skip(text, index)
        if index < len(text) and text[index] == ",":
            index = _skip(text, index + 1)
            if index < len(text) and text[index] == "]":
                break
            continue
        break
    index = _skip(text, index)
    if index >= len(text) or text[index] != "]":
        raise JsoncError("expected ']'")
    node.end = index + 1
    return node, node.end


class Document:
    """An editable JSONC document. Every edit returns a new document."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.root, _ = _parse_value(text, 0)

    def value(self, node: Node) -> object:
        """The Python value of ``node``, so comments inside it are ignored."""
        if node.kind == "object":
            return {key: self.value(child) for key, _, child in node.members}
        if node.kind == "array":
            return [self.value(item) for item in node.items]
        return json.loads(self.text[node.start : node.end])

    def lookup(self, path: tuple[str | int, ...] = ()) -> Node | None:
        node = self.root
        for step in path:
            if isinstance(step, int):
                if node.kind != "array" or not 0 <= step < len(node.items):
                    return None
                node = node.items[step]
            else:
                if node.kind != "object":
                    return None
                entry = node.member(step)
                if entry is None:
                    return None
                node = entry[2]
        return node

    def get(self, path: tuple[str | int, ...] = (), default: object = None) -> object:
        node = self.lookup(path)
        if node is None:
            return default
        return self.value(node)

    def replace(self, path: tuple[str | int, ...], value: object) -> "Document":
        node = self.lookup(path)
        if node is None:
            raise JsoncError(f"no value at {path!r}")
        return self._splice(node.start, node.end, json.dumps(value))

    def put(self, path: tuple[str | int, ...], key: str, value: object) -> "Document":
        """Add or overwrite the ``key`` member of the object at ``path``."""
        node = self.lookup(path)
        if node is None or node.kind != "object":
            raise JsoncError(f"no object at {path!r}")
        entry = node.member(key)
        rendered = json.dumps(value)
        if entry is not None:
            return self._splice(entry[2].start, entry[2].end, rendered)
        return self._insert_member(node, key, rendered, self._own_indent(path))

    def drop(self, path: tuple[str | int, ...], key: str) -> "Document":
        node = self.lookup(path)
        if node is None or node.kind != "object":
            raise JsoncError(f"no object at {path!r}")
        entry = node.member(key)
        if entry is None:
            raise JsoncError(f"no member {key!r} at {path!r}")
        return self._remove(entry[2], entry[1])

    def append(self, path: tuple[str | int, ...], value: object) -> "Document":
        node = self.lookup(path)
        if node is None or node.kind != "array":
            raise JsoncError(f"no array at {path!r}")
        rendered = json.dumps(value)
        if node.items:
            indent = _line_indent(self.text, node.items[-1].start)
            return self._insert_after(node.items[-1], rendered, indent)
        return self._insert_first(node, rendered)

    def remove_at(self, path: tuple[str | int, ...], index: int) -> "Document":
        node = self.lookup(path)
        if node is None or node.kind != "array" or not 0 <= index < len(node.items):
            raise JsoncError(f"no item {index} at {path!r}")
        item = node.items[index]
        return self._remove(item, item.start)

    # -- internals ---------------------------------------------------------

    def _splice(self, start: int, end: int, replacement: str) -> "Document":
        return Document(self.text[:start] + replacement + self.text[end:])

    def _line_start(self, index: int) -> int:
        return self.text.rfind("\n", 0, index) + 1

    def _insert_after(self, previous: Node, rendered: str, indent: str) -> "Document":
        """Insert a new member or item after ``previous``, comma handled."""
        index = _skip(self.text, previous.end)
        if index < len(self.text) and self.text[index] == ",":
            insert_at = index + 1
            prefix = ""
        else:
            insert_at = previous.end
            prefix = ","
        chunk = f"{prefix}\n{indent}{rendered}"
        return self._splice(insert_at, insert_at, chunk)

    def _own_indent(self, path: tuple[str | int, ...]) -> str:
        """Return the indentation of the line that holds ``path``'s key."""
        if not path or not isinstance(path[-1], str):
            return ""
        parent = self.lookup(path[:-1])
        if parent is None or parent.kind != "object":
            return ""
        entry = parent.member(path[-1])
        return "" if entry is None else _line_indent(self.text, entry[1])

    def _insert_member(self, node: Node, key: str, rendered: str, base: str) -> "Document":
        entry = f"{json.dumps(key)}: {rendered}"
        if node.members:
            indent = _line_indent(self.text, node.members[-1][1])
            return self._insert_after(node.members[-1][2], entry, indent)
        child = base + "    "
        inner = self.text[node.start + 1 : node.end - 1]
        if inner.strip():
            closing = node.end - 1
            return self._splice(closing, closing, f"{child}{entry}\n{base}")
        return self._splice(node.start + 1, node.end - 1, f"\n{child}{entry}\n{base}")

    def _insert_first(self, node: Node, rendered: str) -> "Document":
        base = _line_indent(self.text, node.start)
        inner = self.text[node.start + 1 : node.end - 1]
        if inner.strip():
            closing = node.end - 1
            return self._splice(closing, closing, f"{base}    {rendered}\n{base}")
        return self._splice(node.start + 1, node.end - 1, f"\n{base}    {rendered}\n{base}")

    def _remove(self, node: Node, key_start: int) -> "Document":
        """Remove a member or item plus one comma, leaving the rest untouched."""
        back = key_start - 1
        while back >= 0 and self.text[back] in " \t":
            back -= 1
        if back >= 0 and self.text[back] == ",":
            start = back
        else:
            line = self.text.rfind("\n", 0, key_start) + 1
            start = line if self.text[line:key_start].strip() == "" else key_start
        after = _skip(self.text, node.end)
        if after < len(self.text) and self.text[after] == ",":
            end = after + 1
            while end < len(self.text) and self.text[end] in " \t":
                end += 1
            if end < len(self.text) and self.text[end] == "\n":
                end += 1
        else:
            end = node.end
        return Document(self.text[:start] + self.text[end:])
