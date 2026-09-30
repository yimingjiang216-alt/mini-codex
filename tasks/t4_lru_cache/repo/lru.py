"""基于 OrderedDict 的 LRU 缓存。"""

from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._data: OrderedDict = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if key not in self._data:
            self.misses += 1
            return None
        self.hits += 1
        return self._data[key]

    def put(self, key, value):
        self._data[key] = value
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def __len__(self):
        return len(self._data)

    def keys(self):
        return list(self._data.keys())
