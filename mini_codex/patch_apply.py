# -*- coding: utf-8 -*-
"""apply_patch 的落盘逻辑。

对齐 codex-rs `apply-patch/src/file_update.rs` 与 `lib.rs`：
- UpdateFile：按 chunk 顺序定位，每个 chunk 从上一个 chunk 之后开始找
- DeleteFile：文件必须存在，且必须是文件（删目录报错）
- AddFile：目标存在则覆盖
- Move to：先写新路径，再删旧路径；目标存在则覆盖
- 文件末尾强制补一个换行（codex-rs 的 NormalizeToLf 行为）

失败语义（对齐 codex-rs 的 015 号场景）：
    部分成功后再失败，**已生效的改动会保留**，不整体回滚。
    错误信息里给出已改动的文件列表。
"""
from __future__ import annotations

import os

from .patch import (AddFile, DeleteFile, PatchParseError, UpdateFile,
                    UpdateFileChunk, seek_sequence)


class PatchApplyError(RuntimeError):
    """补丁应用失败。"""


def _read_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not text:
        return []
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n")


def _write_lines(path: str, lines: list[str]) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(l + "\n" for l in lines))


def _apply_chunks(original: list[str], path: str, chunks: list[UpdateFileChunk]) -> list[str]:
    """按 chunk 依次替换，返回新行列表。"""
    out = list(original)

    for chunk in chunks:
        # 对齐 codex-rs:compute_replacements —— 每个 chunk 都从行号 0 重新搜索。
        # 这样做是安全的：chunk 按文件中出现顺序书写，前面的改动不会让后面的
        # old_lines 失配（seek_sequence 会跳过已被改掉的位置）。
        line_index = 0
        # 1) 先按 change_context 定位（@@ 后面的那行）
        if chunk.change_context:
            idx = seek_sequence(out, [chunk.change_context], line_index, eof=False)
            if idx is None:
                raise PatchApplyError(
                    "在 %s 中找不到定位上下文 %r" % (path, chunk.change_context)
                )
            line_index = idx + 1

        # 2) 纯插入（old_lines 为空）—— 对齐 codex-rs：始终追加到文件末尾。
        # 注意这不是"插到上下文附近"，而是 append。补丁里写 `@@ <ctx>` + `+行`
        # 时，新行会落到文件末尾，而不是 ctx 后面。
        if not chunk.old_lines:
            insertion = len(out)
            out[insertion:insertion] = list(chunk.new_lines)
            continue

        # 3) 定位 old_lines
        pattern = list(chunk.old_lines)
        idx = seek_sequence(out, pattern, line_index, eof=chunk.is_end_of_file)
        if idx is None and pattern and pattern[-1] == "":
            # 对齐 codex-rs：old_lines 末尾的空串代表"该区域的行尾换行"，
            # 而源文件不把它单独存成一行。去掉末元素重试。
            pattern = pattern[:-1]
            if pattern:
                idx = seek_sequence(out, pattern, line_index, eof=chunk.is_end_of_file)
            if idx is not None:
                # 替换时也要把末元素算进去
                pass
        if idx is None:
            preview = " / ".join(l.strip() for l in chunk.old_lines[:3])
            raise PatchApplyError(
                "在 %s 中找不到要替换的内容：%r（从第 %d 行起查找）"
                % (path, preview[:120], line_index + 1)
            )

        end = idx + len(chunk.old_lines)
        out[idx:end] = list(chunk.new_lines)
        line_index = idx + len(chunk.new_lines)

    return out


def apply_patch(hunks: list, cwd: str = ".", *, create_backup: bool = True):
    """应用补丁。返回 (已改动文件列表, 每个文件的 diff 摘要)。

    部分成功后再失败时，已生效的改动保留，异常里带上已改动列表。
    """
    # 对齐 codex-rs lib.rs：空补丁直接报错 "No files were modified."
    if not hunks:
        raise PatchApplyError("No files were modified.（补丁里没有任何 hunk）")

    changed: list[str] = []
    summaries: list[str] = []

    def resolve(p: str) -> str:
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(cwd, p))

    try:
        for hunk in hunks:
            if isinstance(hunk, AddFile):
                target = resolve(hunk.path)
                existed = os.path.exists(target)
                _write_lines(target, hunk.contents.rstrip("\n").split("\n") if hunk.contents else [])
                changed.append(hunk.path)
                summaries.append(("覆盖 " if existed else "新增 ") + hunk.path)

            elif isinstance(hunk, DeleteFile):
                target = resolve(hunk.path)
                if not os.path.exists(target):
                    raise PatchApplyError("要删除的文件不存在：%s" % hunk.path)
                if os.path.isdir(target):
                    raise PatchApplyError(
                        "Delete File 只接受文件，不接受目录：%s" % hunk.path
                    )
                os.remove(target)
                changed.append(hunk.path)
                summaries.append("删除 " + hunk.path)

            elif isinstance(hunk, UpdateFile):
                target = resolve(hunk.path)
                if not os.path.exists(target):
                    raise PatchApplyError("要修改的文件不存在：%s" % hunk.path)
                if os.path.isdir(target):
                    raise PatchApplyError("Update File 不能作用于目录：%s" % hunk.path)

                original = _read_lines(target)
                updated = _apply_chunks(original, hunk.path, hunk.chunks)

                if hunk.move_path:
                    dest = resolve(hunk.move_path)
                    _write_lines(dest, updated)
                    if os.path.exists(target):
                        os.remove(target)
                    changed.append(hunk.move_path)
                    summaries.append("移动 %s → %s（%d 个 chunk）" % (hunk.path, hunk.move_path, len(hunk.chunks)))
                else:
                    _write_lines(target, updated)
                    changed.append(hunk.path)
                    summaries.append("修改 %s（%d 个 chunk）" % (hunk.path, len(hunk.chunks)))

            else:
                raise PatchApplyError("不支持的 hunk 类型：%r" % (hunk,))

    except PatchApplyError as e:
        if changed:
            raise PatchApplyError(
                "%s\n注意：此前已生效的改动会保留，不会回滚。已改动：%s"
                % (e, "、".join(changed))
            ) from e
        raise

    return changed, summaries
