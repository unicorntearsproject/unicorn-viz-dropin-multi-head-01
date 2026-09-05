"""multi-head-01: the monitor editor's persisted excludes must actually
apply (2026-09-05 audit finding #1 -- the key was written by control-room-01
and read by nobody). Hermetic: a stub Config, no SDL, no GL."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / 'multihead.py'
_SPEC = importlib.util.spec_from_file_location('multihead_under_test', _MOD_PATH)
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


def test_config_excludes_apply_when_no_runtime_override() -> None:
    mh = MultiHeadController(_Cfg(exclude_display_indices=[3, 4]))
    assert mh.excluded_display_indices == {3, 4}
    assert mh.excludes_source == 'config'


def test_runtime_excludes_replace_config() -> None:
    mh = MultiHeadController(_Cfg(exclude_display_indices=[3, 4]), runtime_excludes=[1])
    assert mh.excluded_display_indices == {1}
    assert mh.excludes_source == 'runtime'


def test_runtime_empty_list_means_no_excludes_even_if_config_has_some() -> None:
    """Saving an empty selection in the editor must clear config's list, not
    fall back to it -- otherwise there is no way to un-exclude from the UI."""
    mh = MultiHeadController(_Cfg(exclude_display_indices=[3]), runtime_excludes=[])
    assert mh.excluded_display_indices == set()
    assert mh.excludes_source == 'runtime'


def test_non_list_runtime_value_is_ignored() -> None:
    mh = MultiHeadController(_Cfg(exclude_display_indices=[2]), runtime_excludes=None)
    assert mh.excluded_display_indices == {2}
    assert mh.excludes_source == 'config'


def test_excluded_display_indices_is_a_copy() -> None:
    mh = MultiHeadController(_Cfg(exclude_display_indices=[2]))
    mh.excluded_display_indices.add(9)
    assert mh.excluded_display_indices == {2}
