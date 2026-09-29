"""Standing (kind: placeholder) desk rows must focus without pressing Start.

Idle quiet desks already call focusDesk on row click. Standing section rows are
often never-started kind: placeholders — the click handler used to only flip
selectedKind + re-render, so Blackboard / Desk Prompt / Agent Space stayed on
the prior idle desk. Contracts lock ensure→focus for placeholders and keep
button data-act handlers separate.
"""

from __future__ import annotations

import pytest

from okstratr.lifecycle import observer_asset_dir


@pytest.fixture(scope="module")
def observer_js() -> str:
    return (observer_asset_dir() / "observer.js").read_text(encoding="utf-8")


def test_select_desk_row_helper_present(observer_js: str) -> None:
    js = observer_js
    assert "function selectDeskRow" in js
    assert "function ensureAndFocusKind" in js
    assert "function deskIdFromStartPayload" in js
    assert "function focusDesk" in js


def test_desks_click_uses_select_desk_row(observer_js: str) -> None:
    js = observer_js
    idx = js.index('el("desks").addEventListener("click"')
    # Include button branch + row select (handler is ~40 lines).
    chunk = js[idx : idx + 2200]
    assert "selectDeskRow(kind, id)" in chunk
    assert "ensureAndFocusKind" in js
    # Old reject-only path must be gone from the row-click branch.
    assert "if (id && id.indexOf(\"kind:\") !== 0) focusDesk(id);" not in chunk
    assert "else renderDesks();" not in chunk


def test_ensure_and_focus_starts_quiet_without_herdr(observer_js: str) -> None:
    js = observer_js
    idx = js.index("function ensureAndFocusKind")
    chunk = js[idx : idx + 900]
    assert 'api("/api/desk/start"' in chunk
    assert "drive_herdr: false" in chunk
    assert "focusDesk(newId)" in chunk
    # Must not require a pre-filled standing objective / Start button.
    assert 'objective: ""' in chunk


def test_button_actions_still_stop_propagation(observer_js: str) -> None:
    js = observer_js
    idx = js.index('el("desks").addEventListener("click"')
    chunk = js[idx : idx + 900]
    assert 't.closest("button[data-act]")' in chunk
    assert "ev.stopPropagation()" in chunk
    assert 'act === "start"' in chunk
    assert 'act === "stop"' in chunk
    assert 'act === "dismiss"' in chunk
