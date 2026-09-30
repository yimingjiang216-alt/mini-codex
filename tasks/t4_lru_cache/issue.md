# LRU 缓存淘汰的不是最久未使用的项

命中过的键没有被标记为"最近使用"，导致淘汰顺序错误：

```python
>>> from lru import LRUCache
>>> c = LRUCache(2)
>>> c.put("a", 1); c.put("b", 2)
>>> c.get("a")        # a 刚被访问过
1
>>> c.put("c", 3)     # 期望淘汰 b
>>> c.keys()
['b', 'c']            # 期望 ['a', 'c']
```

另外 `LRUCache(0)` 目前不会报错，但容量为 0 的缓存没有意义。

## 需要的行为

1. `get` 命中的键要被标记为最近使用。
2. `put` 更新已存在的键时，该键也要变为最近使用。
3. 超出容量时淘汰最久未使用的键。
4. `hits` / `misses` 计数正确。
5. `capacity < 1` 时构造 `LRUCache` 抛 `ValueError`。

## 验收

`repo/tests/test_issue.py` 覆盖上述行为，修复后应全部通过，
且 `test_existing.py` 不能被破坏。
