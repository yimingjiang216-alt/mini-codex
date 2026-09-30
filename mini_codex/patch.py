# -*- coding: utf-8 -*-
"""apply_patch 的解析器。

严格对齐 openai/codex `codex-rs/apply-patch` 的补丁语法与容错规则。
语法（源自 codex-rs 的 parser.rs）：

    *** Begin Patch
    *** Add File: <path>
    +<内容行>
    *** Delete File: <path>
    *** Update File: <path>
    *** Move to: <新路径>          （可选，仅 Update File 之后）
    @@ <定位上下文>                （可选，用于缩小查找范围）
     <上下文行>                     （前导空格）
    -<被删除的行>
    +<新增的行>
    *** End Patch

容错规则（对齐 seek_sequence.rs，逐级放宽）：
    1. 精确匹配
    2. 忽略行尾空白
    3. 忽略首尾空白
    4. 归一化 Unicode 标点后匹配（全角破折号/引号/空格 → ASCII）

与 codex-rs 的差异（刻意保留，写进 README）：
    - 不实现 streaming parser，一次性解析
    - 不实现 PathUri / 符号链接策略，只做普通路径
    - 不实现 environment_id 前缀
"""
from __future__ import annotations

from dataclasses import dataclass, field

BEGIN_PATCH_MARKER = "*** Begin Patch"
END_PATCH_MARKER = "*** End Patch"
ADD_FILE_MARKER = "*** Add File: "
DELETE_FILE_MARKER = "*** Delete File: "
UPDATE_FILE_MARKER = "*** Update File: "
MOVE_TO_MARKER = "*** Move to: "
EOF_MARKER = "*** End of File"


class PatchParseError(ValueError):
    """补丁格式错误。"""


@dataclass
class AddFile:
    path: str
    contents: str


@dataclass
class DeleteFile:
    path: str


@dataclass
class UpdateFileChunk:
    change_context: str | None = None
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)
    is_end_of_file: bool = False


@dataclass
class UpdateFile:
    path: str
    move_path: str | None = None
    chunks: list[UpdateFileChunk] = field(default_factory=list)


@dataclass
class ApplyPatchArgs:
    hunks: list
    patch: str


# ---------------------------------------------------------------- 归一化

_PUNCT_MAP = {}
for _c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212":
    _PUNCT_MAP[ord(_c)] = "-"
for _c in "\u2018\u2019\u201a\u201b":
    _PUNCT_MAP[ord(_c)] = "'"
for _c in "\u201c\u201d\u201e\u201f":
    _PUNCT_MAP[ord(_c)] = '"'
for _c in "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000":
    _PUNCT_MAP[ord(_c)] = " "

_JUNK_SUFFIXES = ("\u200b", "\u200c", "\u200d", "\ufeff")


def normalise(s: str) -> str:
    """归一化：去首尾空白 + Unicode 标点转 ASCII + 去掉零宽字符。"""
    s = s.strip()
    for j in _JUNK_SUFFIXES:
        s = s.replace(j, "")
    return s.translate(_PUNCT_MAP)


# ---------------------------------------------------------------- 查找

def seek_sequence(lines: list[str], pattern: list[str], start: int = 0,
                  eof: bool = False) -> int | None:
    """在 lines 中从 start 起找 pattern，返回起始下标；找不到返回 None。

    逐级放宽：精确 → 忽略行尾空白 → 忽略首尾空白 → 归一化标点。
    """
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None

    search_start = start
    if eof and len(lines) >= len(pattern):
        search_start = max(len(lines) - len(pattern), start)

    last = len(lines) - len(pattern)

    # 1. 精确
    for i in range(search_start, last + 1):
        if lines[i:i + len(pattern)] == pattern:
            return i
    # 2. 忽略行尾空白
    for i in range(search_start, last + 1):
        if all(lines[i + k].rstrip() == p.rstrip() for k, p in enumerate(pattern)):
            return i
    # 3. 忽略首尾空白
    for i in range(search_start, last + 1):
        if all(lines[i + k].strip() == p.strip() for k, p in enumerate(pattern)):
            return i
    # 4. 归一化标点
    for i in range(search_start, last + 1):
        if all(normalise(lines[i + k]) == normalise(p) for k, p in enumerate(pattern)):
            return i
    return None


# ---------------------------------------------------------------- 解析

def _strip_heredoc(lines: list[str]) -> list[str]:
    """容忍模型把补丁包在 heredoc 里（对齐 codex-rs 的 Lenient 模式）。"""
    if len(lines) >= 4 and lines[0] in ("<<EOF", "<<'EOF'", '<<"EOF"') and lines[-1].rstrip().endswith("EOF"):
        return lines[1:-1]
    return lines


def _check_boundaries(lines: list[str]) -> list[str]:
    if not lines:
        raise PatchParseError("补丁为空：第一行必须是 '*** Begin Patch'")
    first = lines[0].strip()
    last = lines[-1].strip()
    if first != BEGIN_PATCH_MARKER:
        raise PatchParseError("补丁第一行必须是 '*** Begin Patch'")
    if last != END_PATCH_MARKER:
        raise PatchParseError("补丁最后一行必须是 '*** End Patch'")
    # 部分模型会在 "*** End Patch" 后面留字，容忍多余后缀
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith(END_PATCH_MARKER):
            return lines[:i + 1]
    return lines


def parse_patch(patch: str) -> ApplyPatchArgs:
    raw = _strip_heredoc(patch.strip("\n").split("\n"))
    lines = _check_boundaries(raw)
    body = lines[1:-1]

    hunks: list = []
    i = 0
    while i < len(body):
        line = body[i]
        stripped = line.strip()

        # 跳过空行
        if not stripped:
            i += 1
            continue

        if stripped.startswith(ADD_FILE_MARKER):
            path = stripped[len(ADD_FILE_MARKER):].strip()
            if not path:
                raise PatchParseError("Add File 缺少路径")
            i += 1
            contents: list[str] = []
            while i < len(body):
                nxt = body[i]
                if nxt.startswith("+") and not nxt.strip().startswith("*** "):
                    contents.append(nxt[1:])
                    i += 1
                else:
                    break
            text = "".join(c + "\n" for c in contents)
            hunks.append(AddFile(path=path, contents=text))
            continue

        if stripped.startswith(DELETE_FILE_MARKER):
            path = stripped[len(DELETE_FILE_MARKER):].strip()
            if not path:
                raise PatchParseError("Delete File 缺少路径")
            hunks.append(DeleteFile(path=path))
            i += 1
            continue

        if stripped.startswith(UPDATE_FILE_MARKER):
            path = stripped[len(UPDATE_FILE_MARKER):].strip()
            if not path:
                raise PatchParseError("Update File 缺少路径")
            i += 1
            move_path = None
            if i < len(body) and body[i].strip().startswith(MOVE_TO_MARKER):
                move_path = body[i].strip()[len(MOVE_TO_MARKER):].strip()
                i += 1

            chunks: list[UpdateFileChunk] = []
            cur: UpdateFileChunk | None = None
            while i < len(body):
                nxt = body[i]
                s = nxt.strip()
                if s.startswith("*** ") and not s.startswith("@@") and not s.startswith(EOF_MARKER):
                    break
                if s.startswith("@@"):
                    if cur is not None:
                        chunks.append(cur)
                    ctx = s[2:].strip()
                    cur = UpdateFileChunk(change_context=ctx or None)
                    i += 1
                    continue
                if cur is None:
                    # 没有 @@ 头的裸改动：自动开一个 chunk
                    cur = UpdateFileChunk()
                if s == EOF_MARKER:
                    cur.is_end_of_file = True
                    i += 1
                    continue
                if not nxt:
                    # 补丁里的空行 = 空上下文行
                    cur.old_lines.append("")
                    cur.new_lines.append("")
                    i += 1
                    continue
                marker, rest = nxt[0], nxt[1:]
                if marker == " ":
                    cur.old_lines.append(rest)
                    cur.new_lines.append(rest)
                elif marker == "-":
                    cur.old_lines.append(rest)
                elif marker == "+":
                    cur.new_lines.append(rest)
                else:
                    raise PatchParseError(
                        "Update File 里的每一行必须以空格、'-' 或 '+' 开头，"
                        "实际是：%r" % nxt[:60]
                    )
                i += 1
            if cur is not None:
                chunks.append(cur)
            if not chunks:
                raise PatchParseError("Update File 的 hunk 为空：%s" % path)
            hunks.append(UpdateFile(path=path, move_path=move_path, chunks=chunks))
            continue

        raise PatchParseError(
            "无法识别的 hunk 头：%r（只支持 Add File / Delete File / Update File）" % stripped[:60]
        )

    return ApplyPatchArgs(hunks=hunks, patch=patch)
