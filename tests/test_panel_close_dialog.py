"""The panel's close button opens a dialog that is actually inside the window.

Panel.qml's root is a plain Item that is never shown; only the FloatingWindow
(id: win) is mapped. Anything visual placed directly under the root Item is
invisible, which is how the close dialog ended up never appearing.
QML isn't executed here, so this walks the object tree in the source.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Panel.qml"

NON_VISUAL = {"FileView", "Timer", "FloatingWindow", "Process", "Connections", "IpcHandler"}


def _strip(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            out.append('""')
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tree(text: str):
    """Return nodes as dicts {type, id, parent, children} for QML objects."""
    src = _strip(text)
    root = {"type": "<file>", "id": None, "parent": None, "children": []}
    stack = [root]
    pattern = r"(component\s+\w+\s*:\s*)?([A-Za-z_][\w.]*)\s*\{|\{|\}|\bid:\s*(\w+)"
    for m in re.finditer(pattern, src):
        tok = m.group(0)
        if m.group(3):
            stack[-1]["id"] = stack[-1]["id"] or m.group(3)
        elif tok == "}":
            stack.pop()
        elif m.group(2) and m.group(2)[0].isupper():
            # "component Chip: Rectangle {" declares a type, not an instance.
            kind = "<component>" if m.group(1) else m.group(2)
            node = {"type": kind, "id": None, "parent": stack[-1], "children": []}
            stack[-1]["children"].append(node)
            stack.append(node)
        else:
            node = {"type": "<block>", "id": None, "parent": stack[-1], "children": []}
            stack[-1]["children"].append(node)
            stack.append(node)
    assert len(stack) == 1, "unbalanced braces in Panel.qml"
    return root


def _find(node, ident):
    if node.get("id") == ident:
        return node
    for c in node["children"]:
        hit = _find(c, ident)
        if hit:
            return hit
    return None


def _ancestors(node):
    out = []
    while node["parent"] is not None:
        node = node["parent"]
        out.append(node)
    return out


def test_close_dialog_is_inside_the_window():
    tree = _tree(PANEL.read_text(encoding="utf-8"))
    dialog = _find(tree, "closeDialogOverlay")
    assert dialog is not None
    assert any(a.get("id") == "win" and a["type"] == "FloatingWindow" for a in _ancestors(dialog))


def test_no_visual_items_hang_off_the_hidden_root():
    tree = _tree(PANEL.read_text(encoding="utf-8"))
    root_item = next(c for c in tree["children"] if c["type"] == "Item")
    stray = [c["type"] + (f"#{c['id']}" if c["id"] else "") for c in root_item["children"]
             if c["type"] not in NON_VISUAL and not c["type"].startswith("<")]
    assert stray == [], f"visual items outside the window: {stray}"


def test_close_button_opens_dialog_and_confirm_closes():
    text = PANEL.read_text(encoding="utf-8")
    assert re.search(r'label:\s*"✕"[\s\S]{0,120}onClicked:\s*root\.close\(\)', text)
    close_fn = text[text.index("function close()"):text.index("function cancelClose()")]
    assert "closeDialogVisible = true" in close_fn
    confirm = text[text.index("function confirmClose()"):text.index("function toggle(")]
    assert "opened = false" in confirm
    assert "/api/desk/quiet_standing" in confirm
