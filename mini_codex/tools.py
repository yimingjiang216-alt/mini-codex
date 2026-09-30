"""工具系统。

对应 Codex 的：
- `ToolDefinition`（name + description + input_schema JSON Schema）
- `ToolExecutor::handle`（执行，返回 ToolOutput）
- registry / router（按名字分发）

这里用最直白的方式：
- `ToolSpec`   = 工具元数据（暴露给模型的 JSON Schema + 参数说明）
- `ToolResult` = 执行结果（回填进消息历史的文本）
- `TOOLS`      = 名字 -> (spec, 执行函数)
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from .linting import lint_changed
from .patch import PatchParseError, parse_patch
from .patch_apply import PatchApplyError, apply_patch

MAX_OUTPUT = 8000  # 工具输出截断上限，避免撑爆上下文
MAX_TIMEOUT = 120   # 命令执行超时（秒）


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema 的 properties 部分


@dataclass
class ToolResult:
    content: str
    is_error: bool = False

    def to_message(self) -> str:
        prefix = "ERROR: " if self.is_error else ""
        return prefix + self.content


# ---------- 工具实现 ----------

def _run_command(cmd: str, cwd: str) -> ToolResult:
    from pathlib import Path
    work = Path(cwd).expanduser()
    if not work.exists():
        return ToolResult(f"目录不存在: {work}", is_error=True)
    try:
        # Windows 上用默认 shell；简单起见不设沙箱
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=MAX_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
        out = proc.stdout
        err = proc.stderr
        parts = []
        if out.strip():
            parts.append("STDOUT:\n" + out)
        if err.strip():
            parts.append("STDERR:\n" + err)
        if not parts:
            parts.append(f"(exit code {proc.returncode}, no output)")
        body = "\n\n".join(parts)
        return ToolResult(f"exit code: {proc.returncode}\n{body}", is_error=proc.returncode != 0)
    except subprocess.TimeoutExpired:
        return ToolResult(f"命令超时({MAX_TIMEOUT}s)已终止", is_error=True)
    except Exception as e:  # noqa: BLE001
        return ToolResult(f"执行失败: {e}", is_error=True)


def tool_exec(args: dict) -> ToolResult:
    return _run_command(args.get("command", ""), args.get("cwd", "."))


def tool_read(args: dict) -> ToolResult:
    try:
        p = args["path"]
        if not os.path.isfile(p):
            return ToolResult(f"文件不存在: {p}", is_error=True)
        with open(p, encoding="utf-8", errors="replace") as f:
            data = f.read()
        if len(data) > MAX_OUTPUT:
            data = data[:MAX_OUTPUT] + "\n...[truncated]"
        return ToolResult(data)
    except Exception as e:  # noqa: BLE001
        return ToolResult(str(e), is_error=True)


def tool_write(args: dict) -> ToolResult:
    try:
        p = args["path"]
        content = args["content"]
        os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(f"已写入 {p} ({len(content)} 字符)")
    except Exception as e:  # noqa: BLE001
        return ToolResult(str(e), is_error=True)


def tool_list_dir(args: dict) -> ToolResult:
    try:
        p = args.get("path", ".")
        entries = sorted(os.listdir(p))
        return ToolResult("\n".join(entries) or "(空目录)")
    except Exception as e:  # noqa: BLE001
        return ToolResult(str(e), is_error=True)


def tool_apply_patch(args: dict) -> ToolResult:
    """应用一个补丁。对齐 codex 的 apply_patch 工具。"""
    patch_text = args.get("patch", "")
    cwd = args.get("cwd", ".")
    if not patch_text.strip():
        return ToolResult("patch 参数为空", is_error=True)
    try:
        parsed = parse_patch(patch_text)
        changed, summaries = apply_patch(parsed.hunks, cwd=cwd)
    except PatchParseError as e:
        return ToolResult("补丁格式错误：%s" % e, is_error=True)
    except PatchApplyError as e:
        return ToolResult("补丁应用失败：%s" % e, is_error=True)

    body = "已应用：" + "；".join(summaries)
    # 编辑后自动语法检查（借鉴 SWE-agent 的 lint 回灌）
    warn = lint_changed(changed, cwd=cwd)
    if warn:
        body += "\n\n" + warn
    return ToolResult(body)


# ---------- 工具注册表 ----------

def _def(name: str, desc: str, params: dict) -> ToolSpec:
    return ToolSpec(name=name, description=desc, parameters=params)


TOOLS: dict[str, tuple[ToolSpec, object]] = {
    "exec": (_def(
        "exec",
        "在 cwd 目录下运行一条 shell 命令，返回 stdout/stderr 和退出码。用于编译、测试、检查文件等。",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "cwd": {"type": "string", "description": "工作目录，默认 '.'"},
            },
            "required": ["command"],
        },
    ), tool_exec),
    "read_file": (_def(
        "read_file",
        "读取一个文本文件的内容。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
            },
            "required": ["path"],
        },
    ), tool_read),
    "apply_patch": (_def(
        "apply_patch",
        "用一个补丁修改文件。支持三种操作：新增文件、删除文件、修改文件（可含多处改动，"
        "也可用 *** Move to: 移动/重命名）。比 write_file 更适合改大文件中的一小部分。\n"
        "补丁格式（第一行和最后一行必须是标记，换行符为 \\n，不会写就用空的 *** End Patch）：\n"
        "*** Begin Patch\n"
        "*** Add File: 路径\n"
        "+新增内容（每行前面加一个 +）\n"
        "*** Delete File: 路径\n"
        "*** Update File: 路径\n"
        "*** Move to: 新路径   （可选，仅 Update File 之后，紧邻）\n"
        "@@ 定位用的上下文行   （可选，用来缩小查找范围，不要带前导空格）\n"
        " 保持不变的行       （前导一个空格）\n"
        "-要删除的行\n"
        "+要新增的行\n"
        "*** End Patch\n"
        "规则：Update File 里每个 @@ 开头的块是一处改动；如果只写 @@ 后面不写上下文，"
        "则从文件开头找。要删除的行必须与文件里完全一致（允许首尾空白差异）。"
        "新增文件用 Add File，不要用 Update File 创建新文件。",
        {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "补丁全文，以 *** Begin Patch 开头、*** End Patch 结尾"},
                "cwd": {"type": "string", "description": "工作目录，默认 '.'"},
            },
            "required": ["patch"],
        },
    ), tool_apply_patch),
    "write_file": (_def(
        "write_file",
        "创建或覆盖一个文本文件。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "完整的新文件内容"},
            },
            "required": ["path", "content"],
        },
    ), tool_write),
    "list_dir": (_def(
        "list_dir",
        "列出目录下的条目（不递归）。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径，默认 '.'"},
            },
            "required": [],
        },
    ), tool_list_dir),
}


def tool_schemas() -> list[dict]:
    """生成传给模型的 function-calling 工具描述。"""
    out = []
    for spec, _ in TOOLS.values():
        out.append({
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        })
    return out


def execute_tool(name: str, args: dict) -> ToolResult:
    if name not in TOOLS:
        return ToolResult(f"未知工具: {name}", is_error=True)
    _, fn = TOOLS[name]
    try:
        res = fn(args)
    except Exception as e:  # noqa: BLE001
        return ToolResult(f"工具内部错误: {e}", is_error=True)
    # 统一截断
    if len(res.content) > MAX_OUTPUT:
        res.content = res.content[:MAX_OUTPUT] + "\n...[truncated]"
    return res
