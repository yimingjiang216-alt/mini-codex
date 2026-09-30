# 分页函数第一页数据不对，且总页数少算一页

两个问题：

```python
>>> from pagination import page, total_pages
>>> page(["a", "b", "c"], 1, 2)
[]                    # 期望 ['a', 'b']
>>> total_pages(25, 10)
2                     # 期望 3
```

翻到第一页拿到的是空列表，最后一页（不满一页的部分）也会被丢掉；
`total_pages` 没有向上取整。

## 需要的行为

1. `page_no` 从 1 开始计数，第 1 页应返回最前面的 `per_page` 个元素。
2. 最后一页不足 `per_page` 时返回剩余元素，不能丢。
3. 请求超出总页数时返回空列表，不报错。
4. `total_pages` 向上取整；元素数为 0 时返回 0。
5. `page_no < 1` 或 `per_page < 1` 抛 `ValueError`。

## 验收

`repo/tests/test_issue.py` 覆盖上述行为，修复后应全部通过，
且 `test_existing.py` 不能被破坏。
