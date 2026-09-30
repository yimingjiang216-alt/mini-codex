# -*- coding: utf-8 -*-
"""编辑后的自动检查（借鉴 SWE-agent 的 windowed_edit_linting）。

SWE-agent 的 str_replace_editor 每次编辑后都会跑 flake8 并把结果回灌给模型
（源码里出现 20 次 flake8、18 次 lint）。Codex 的 apply_patch 不这么做 ——
它假设模型会自己验证。

这里选 SWE-agent 的做法，理由是：模型改出语法错误时往往不自知，
而"改完立刻看到语法报错"是最便宜的纠错信号（不需要跑完整测试）。

刻意做得比 SWE-agent 轻：
- 只对 .py 文件跑 py_compile（标准库，零依赖，毫秒级）
- 不跑 flake8（需要额外依赖，且大部分是风格问题，噪音大）
- 只报语法错误，不报风格问题
"""
from __future__ import annotations

import ast
import os


def check_syntax(path: str) -> str | None:
    """检查 Python 文件语法。返回错误描述；没问题返回 None。

    只对 .py 生效，其他扩展名直接跳过。
    """
    if not path.endswith(".py"):
        return None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError as e:
        return "无法读取文件：%s" % e

    try:
        ast.parse(src, filename=path)
    except SyntaxError as e:
        line = e.lineno if e.lineno is not None else "?"
        col = e.offset if e.offset is not None else "?"
        return "语法错误 第 %s 行 第 %s 列: %s" % (line, col, e.msg)
    return None


def lint_changed(paths: list[str], cwd: str = ".") -> str:
    """对刚改动的文件做语法检查，返回回灌给模型的文本。

    没有问题时返回空串 —— 这样调用方可以只在出错时追加内容。
    """
    problems = []
    for rel in paths:
        full = rel if os.path.isabs(rel) else os.path.join(cwd, rel)
        msg = check_syntax(full)
        if msg:
            problems.append("%s: %s" % (rel, msg))
    if not problems:
        return ""
    return "自动语法检查发现问题（请先修掉再继续）：\n" + "\n".join("- " + p for p in problems)
