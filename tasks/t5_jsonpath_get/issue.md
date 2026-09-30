# 路径里带数组下标时取值失败

`get()` 只支持字典逐层下钻，路径中一旦出现数组下标就出错：

```python
>>> from jsonpath_lite import get
>>> get({"a": [10, 20, 30]}, "a.1")
TypeError: list indices must be integers or slices, not str
```

## 需要的行为

1. 路径片段为纯数字时，按列表下标解释：`a.0`、`a.1`。
2. 支持数组里放字典：`items.1.name`。
3. 路径不存在时：给了 `default` 就返回 `default`；没给就抛 `PathNotFound`。
4. 下标越界、负数下标、对列表用非数字片段，都属于路径不存在。
5. 空路径返回原始数据本身。

## 验收

`repo/tests/test_issue.py` 覆盖上述行为，修复后应全部通过，
且 `test_existing.py` 不能被破坏。
