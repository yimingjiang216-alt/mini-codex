# 不同单位相加时没有做换算

```python
>>> from unitcalc import eval_expr
>>> eval_expr("3 km + 500 m")
503.0 km          # 期望 3.5 km

>>> eval_expr("1 h + 30 min")
31.0 h            # 期望 1.5 h
```

`Quantity.__add__` 把两个数值直接相加了，没有把右操作数换算到左操作数的单位。
注意减法是对的，说明问题只在加法这一处。

## 需要的行为

1. `3 km + 500 m` 得到 `3.5 km`（结果沿用左操作数的单位）。
2. 反向也要对：`500 m + 1 km` 得到 `1500 m`。
3. 连续不同单位相加要正确：`1 h + 30 min + 1800 s` 得到 `2 h`。
4. 量纲不一致（如 `1 km + 1 kg`）仍然要抛 `UnitError`。
5. 同单位相加、减法、乘除、单位换算等现有行为不能退化。

## 验收

`repo/tests/test_issue.py` 覆盖上述行为，修复后应全部通过，
且 `repo/test_existing.py` 不能被破坏。
