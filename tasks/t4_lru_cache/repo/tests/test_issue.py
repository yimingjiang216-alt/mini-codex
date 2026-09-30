import pytest

from lru import LRUCache


def test_get_refreshes_recency():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")          # a 变为最近使用
    c.put("c", 3)       # 应淘汰 b，而不是 a
    assert c.keys() == ["a", "c"]
    assert c.get("b") is None
    assert c.get("a") == 1


def test_put_existing_refreshes_recency():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 10)      # 更新 a，a 变为最近使用
    c.put("c", 3)       # 应淘汰 b
    assert c.keys() == ["a", "c"]
    assert c.get("a") == 10


def test_missing_key_counts_as_miss():
    c = LRUCache(2)
    c.get("nope")
    assert c.misses == 1
    assert c.hits == 0


def test_hit_and_miss_counters():
    c = LRUCache(2)
    c.put("a", 1)
    c.get("a")
    c.get("b")
    assert c.hits == 1
    assert c.misses == 1


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        LRUCache(0)


def test_get_does_not_change_len():
    c = LRUCache(2)
    c.put("a", 1)
    c.get("a")
    assert len(c) == 1
