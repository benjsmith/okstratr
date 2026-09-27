"""Observer desk focus must stick across poll ticks (selection/poll race).

Switchbay soft remounts re-inject observer.js. A zombie interval that re-queries
#conversation by id can write the new DOM with a stale focusDeskId, flipping
selection between two idle desks every POLL_MS. Contracts below lock the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr.lifecycle import observer_asset_dir


@pytest.fixture(scope="module")
def observer_js() -> str:
    return (observer_asset_dir() / "observer.js").read_text(encoding="utf-8")


def test_observer_js_sticky_focus_contracts(observer_js: str) -> None:
    js = observer_js
    assert "focusSticky" in js
    assert "mountAlive" in js
    assert "function mountIsLive" in js
    assert "function setFocusDesk" in js
    assert "function clearFocusDesk" in js
    assert "function detectPreferredDesk" in js
    assert "OKSTRATR_FOCUS_DESK" in js
    assert "okstratr.observer.focusDeskId" in js
    # Zombie ticks must capture roots — not re-query into a remount's DOM.
    assert "const convRoot = el(\"conversation\")" in js
    assert "const desksRoot = el(\"desks\")" in js
    assert "if (!mountIsLive(convRoot) || !mountIsLive(desksRoot)) return" in js
    # Teardown must kill in-flight callbacks, not only clearInterval.
    assert "mountAlive = false" in js
    # Refresh must not auto-promote another desk once sticky.
    assert "if (!state.focusDeskId && !state.focusSticky)" in js
    assert "Never auto-promote another" in js or "never auto-promote another" in js.lower() or (
        "Auto-promote" not in js and "setFocusDesk(fid, { sticky: true })" in js
    )


def test_observer_js_preferred_desk_once(observer_js: str) -> None:
    js = observer_js
    assert "preferredDeskApplied" in js
    assert "detectPreferredDesk()" in js
    assert "readStoredFocus()" in js
