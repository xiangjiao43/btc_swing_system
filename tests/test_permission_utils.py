"""
tests/test_permission_utils.py — src.utils.permission 测试。
"""

from __future__ import annotations

import pytest

from src.utils.permission import (
    get_permission_order,
    is_permission_strict_enough,
    merge_permissions,
)


class TestGetOrder:
    def test_returns_list(self):
        order = get_permission_order()
        assert isinstance(order, list)
        assert len(order) >= 5

    def test_expected_values(self):
        order = get_permission_order()
        for v in ("can_open", "cautious_open", "ambush_only",
                  "no_chase", "hold_only", "watch", "protective"):
            assert v in order

    def test_ordering_wide_to_strict(self):
        """can_open 在最前(最宽),protective 在最后(最严)。"""
        order = get_permission_order()
        assert order[0] == "can_open"
        assert order[-1] == "protective"


class TestMergePermissions:
    def test_two_perms_stricter_wins(self):
        # protective 最严
        assert merge_permissions("can_open", "protective") == "protective"
        assert merge_permissions("watch", "can_open") == "watch"

    def test_identical_returns_same(self):
        assert merge_permissions("cautious_open", "cautious_open") == "cautious_open"

    def test_three_perms(self):
        assert merge_permissions("can_open", "cautious_open", "hold_only") == "hold_only"

    def test_empty_returns_watch(self):
        assert merge_permissions() == "watch"

    def test_unknown_permission_preserved_as_fallback(self):
        """全部未识别 → 返回第一个(防止静默变 watch)。"""
        assert merge_permissions("made_up_perm") == "made_up_perm"

    def test_mixed_known_and_unknown(self):
        """已知 + 未知 → 只看已知里最严的。"""
        assert merge_permissions("can_open", "invalid_perm", "watch") == "watch"

    def test_ambush_vs_no_chase(self):
        """no_chase 比 ambush_only 严(索引更大)。"""
        assert merge_permissions("ambush_only", "no_chase") == "no_chase"

    def test_hold_only_vs_watch(self):
        """watch 比 hold_only 严。"""
        assert merge_permissions("hold_only", "watch") == "watch"


class TestIsStrictEnough:
    def test_strict_enough(self):
        assert is_permission_strict_enough("watch", "hold_only") is True
        assert is_permission_strict_enough("protective", "watch") is True

    def test_not_strict_enough(self):
        assert is_permission_strict_enough("can_open", "cautious_open") is False
        assert is_permission_strict_enough("hold_only", "protective") is False

    def test_equal_counts_as_strict_enough(self):
        assert is_permission_strict_enough("watch", "watch") is True

    def test_unknown_returns_false(self):
        assert is_permission_strict_enough("fake", "watch") is False
