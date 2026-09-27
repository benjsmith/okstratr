"""Observer panels must track focusDeskId on every desk select.

After Desk Prompt UX (6249fb7), Blackboard / Desk Prompt headers could stay
stuck on the previously focused desk (e.g. desk-543 - work) while the sidebar
and sticky focus already pointed at another standing desk. Contracts lock the
bindFocusPanels wiring without weakening sticky focus (14be8ad).
"""

from __future__ import annotations

import pytest

from okstratr.lifecycle import observer_asset_dir


@pytest.fixture(scope="module")
def observer_js() -> str:
    return (observer_asset_dir() / "observer.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def observer_html() -> str:
    return (observer_asset_dir() / "index.html").read_text(encoding="utf-8")


def test_focus_bind_helpers_present(observer_js: str) -> None:
    js = observer_js
    assert "function bindFocusPanels" in js
    assert "function focusedDeskMetaLabel" in js
    assert "function focusDesk" in js
    assert "function setFocusDesk" in js
    assert "focusSticky" in js


def test_focus_desk_binds_panels_before_refresh(observer_js: str) -> None:
    js = observer_js
    # focusDesk must rebind dependent panels immediately (not only after refresh).
    idx = js.index("function focusDesk")
    chunk = js[idx : idx + 900]
    assert "bindFocusPanels()" in chunk
    assert "renderDeskSwitcher()" in chunk
    assert "renderBlackboard" in chunk
    assert 'api("/api/desk/focus"' in chunk
    # Sticky focus still applied.
    assert "setFocusDesk(deskId, { sticky: true })" in chunk


def test_refresh_discards_stale_scoped_payloads(observer_js: str) -> None:
    js = observer_js
    assert "focusStill" in js
    assert "Discard scoped payloads" in js or "no longer focused" in js
    # Sticky adopt gate remains.
    assert "if (!state.focusDeskId && !state.focusSticky)" in js


def test_refresh_calls_bind_focus_panels(observer_js: str) -> None:
    js = observer_js
    idx = js.index("renderDeskSwitcher();")
    # Nearby refresh render path should bind panels.
    chunk = js[idx : idx + 600]
    assert "bindFocusPanels()" in chunk


def test_panel_header_ids_present(observer_html: str) -> None:
    html = observer_html
    assert 'id="bb-desk-label"' in html
    assert 'id="desk-prompt-meta"' in html
    assert 'id="desk-switcher"' in html
    assert 'id="conversation-meta"' in html


def test_meta_label_uses_id_kind_dash(observer_js: str) -> None:
    """Headers should read like 'desk-543e03be - work' for the focused desk."""
    js = observer_js
    assert 'short + " - " + kind' in js
