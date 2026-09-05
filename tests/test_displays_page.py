"""multi-head-01's Control Room 'displays' page (P3 of
docs/planning/control-room-drop-in-integration-plan-2026-09-05.md).
Retires control-room-01's hardcoded DISPLAY panel and monitor-editor
modal. Hermetic: a stub Config, a fake VJApi, and all_detected_displays()
monkeypatched so no real SDL video query is needed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_MOD_PATH = Path(__file__).resolve().parents[1] / 'multihead.py'
_SPEC = importlib.util.spec_from_file_location('multihead_displays_page_under_test', _MOD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)
MultiHeadController = _MOD.MultiHeadController


class _Cfg:
    def __init__(self, **window):
        self._window = window

    def get(self, section, key, default=None):
        if section == 'window':
            return self._window.get(key, default)
        return default


class _FakeVJApi:
    def __init__(self) -> None:
        self.pages: dict[str, object] = {}
        self.store: dict[str, object] = {}
        self.mode = 'single'

    def register_operator_page(self, page) -> None:
        self.pages[page.name] = page

    def unregister_operator_page(self, name: str) -> bool:
        return self.pages.pop(name, None) is not None

    def set_runtime_state(self, key, value) -> bool:
        self.store[key] = value
        return True

    def set_display_mode(self, mode: str) -> str:
        self.mode = mode
        return mode


_DISPLAYS = [(0, 0, 0, 1920, 1080), (1, 1920, 0, 1920, 1080)]


def _mh(**window) -> 'MultiHeadController':
    mh = MultiHeadController(_Cfg(**window))
    mh.all_detected_displays = lambda: list(_DISPLAYS)
    return mh


def test_set_vj_api_registers_the_displays_page() -> None:
    mh = _mh()
    api = _FakeVJApi()
    mh.set_vj_api(api)
    page = api.pages['displays']
    assert page.title == 'Displays' and page.owner == 'multi-head-01'
    assert page.draw == mh._draw_displays_page
    assert page.on_action == mh._displays_page_action
    mh.shutdown()


def test_pending_excludes_seeded_from_active_excludes() -> None:
    mh = _mh(exclude_display_indices=[1])
    assert mh.pending_excluded_display_indices == {1}
    # Active excludes are untouched by staging -- this is the same set at
    # construction, but toggling pending must not mutate the active one.
    mh.toggle_pending_exclude(0)
    assert mh.excluded_display_indices == {1}
    assert mh.pending_excluded_display_indices == {0, 1}


def test_toggle_pending_exclude_flips_membership() -> None:
    mh = _mh()
    assert mh.toggle_pending_exclude(1) is True
    assert mh.pending_excluded_display_indices == {1}
    assert mh.toggle_pending_exclude(1) is False
    assert mh.pending_excluded_display_indices == set()


def test_reset_pending_excludes_reverts_to_config() -> None:
    mh = _mh(exclude_display_indices=[1])
    mh.toggle_pending_exclude(1)  # now empty (was {1}, toggled off)
    mh.toggle_pending_exclude(0)  # now {0}
    assert mh.pending_excluded_display_indices == {0}
    mh.reset_pending_excludes()
    assert mh.pending_excluded_display_indices == {1}


def test_save_pending_excludes_writes_the_runtime_excludes_key() -> None:
    mh = _mh()
    api = _FakeVJApi()
    mh.set_vj_api(api)
    mh.toggle_pending_exclude(1)
    result = mh.save_pending_excludes()
    assert result == [1]
    assert api.store['multihead.monitor_editor.exclude_display_indices'] == [1]
    mh.shutdown()


def test_save_pending_excludes_without_vj_api_does_not_raise() -> None:
    mh = _mh()
    mh.toggle_pending_exclude(0)
    assert mh.save_pending_excludes() == [0]


def test_pending_excludes_is_a_copy() -> None:
    mh = _mh()
    mh.pending_excluded_display_indices.add(9)
    assert mh.pending_excluded_display_indices == set()


class _FakeCanvas:
    def __init__(self, rect=(0, 0, 800, 500)) -> None:
        self.draw = _FakeDraw()
        self.rect = rect
        self.theme = SimpleNamespace(
            accent=(0, 160, 255), panel=(15, 25, 35), panel_alt=(10, 20, 30), line=(40, 50, 60),
            text=(255, 255, 255), text_dim=(150, 150, 150), warn=(255, 160, 0),
            danger=(255, 60, 60), success=(60, 200, 100),
        )
        font = _FakeFont()
        self.fonts = {'title': font, 'heading': font, 'body': font, 'small': font}
        self.hotspots: list[tuple[str, object, tuple]] = []

    def add_hotspot(self, action, payload, rect) -> None:
        self.hotspots.append((action, payload, rect))


class _FakeFont:
    pass


class _FakeDraw:
    def rounded_rectangle(self, *a, **kw) -> None:
        pass

    def rectangle(self, *a, **kw) -> None:
        pass

    def text(self, *a, **kw) -> None:
        pass

    def textbbox(self, xy, text, font=None):
        return (0, 0, len(str(text)) * 6, 12)


def test_draw_displays_page_emits_mode_and_select_hotspots() -> None:
    mh = _mh()
    canvas = _FakeCanvas()
    mh._draw_displays_page(canvas)
    actions = {h[0] for h in canvas.hotspots}
    assert 'mode' in actions
    assert 'select' in actions
    assert 'toggle_exclude' in actions
    assert 'reset_excludes' in actions
    assert 'save_excludes' in actions
    mode_payloads = {h[1] for h in canvas.hotspots if h[0] == 'mode'}
    assert mode_payloads == set(mh.supported_display_modes())


def test_draw_displays_page_handles_no_displays() -> None:
    mh = _mh()
    mh.all_detected_displays = lambda: []
    canvas = _FakeCanvas()
    mh._draw_displays_page(canvas)  # must not raise
    actions = {h[0] for h in canvas.hotspots}
    assert 'select' not in actions


def test_mode_action_routes_to_set_display_mode() -> None:
    mh = _mh()
    api = _FakeVJApi()
    mh.set_vj_api(api)
    msg = mh._displays_page_action('mode', 'span_included')
    assert api.mode == 'span_included'
    assert msg == 'Display mode: span_included'
    mh.shutdown()


def test_select_action_sets_selected_index() -> None:
    mh = _mh()
    assert mh._displays_page_action('select', 1) is None
    assert mh._page_selected_idx == 1


def test_toggle_exclude_action_uses_the_selected_display() -> None:
    mh = _mh()
    mh._page_selected_idx = 1
    msg = mh._displays_page_action('toggle_exclude', None)
    assert msg == 'Display 1: excluded'
    assert mh.pending_excluded_display_indices == {1}
    msg2 = mh._displays_page_action('toggle_exclude', None)
    assert msg2 == 'Display 1: included'


def test_toggle_exclude_action_with_no_displays() -> None:
    mh = _mh()
    mh.all_detected_displays = lambda: []
    assert mh._displays_page_action('toggle_exclude', None) == 'No displays detected'


def test_reset_and_save_actions_flash_text() -> None:
    mh = _mh()
    api = _FakeVJApi()
    mh.set_vj_api(api)
    assert mh._displays_page_action('reset_excludes', None) == 'Monitor excludes reset'
    assert mh._displays_page_action('save_excludes', None) == 'Monitor excludes saved (restart required)'
    mh.shutdown()


def test_unknown_action_returns_none() -> None:
    mh = _mh()
    assert mh._displays_page_action('nope', None) is None


def test_shutdown_unregisters_the_page() -> None:
    mh = _mh()
    api = _FakeVJApi()
    mh.set_vj_api(api)
    assert 'displays' in api.pages
    mh.shutdown()
    assert 'displays' not in api.pages
