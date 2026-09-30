"""对照实验：write_file（legacy） vs apply_patch（patch）。

每个任务是一个自带 bug 的迷你仓库：

    tasks/<id>/repo/              待修复代码 + test_existing.py（原有测试，必须保持绿）
    tasks/<id>/repo/tests/test_issue.py   隐藏验收测试（修复前必须红）
    tasks/<id>/issue.md           给 agent 看的 issue 描述

一次运行 = 把 repo 拷到临时目录 -> 自检（issue 红 / existing 绿）
-> 让 agent 在受控工具集下修 -> 再跑两个测试集。

两种工具模式的区别只在「编辑接口」：

    legacy : exec / read_file / write_file / list_dir
    patch  : exec / read_file / apply_patch / list_dir

resolved 的判据同时要求 fail_to_pass 全绿 **且** pass_to_pass 不退化。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mini_codex import agent as agent_mod  # noqa: E402
from mini_codex import tools as tools_mod  # noqa: E402
from mini_codex.agent import Agent  # noqa: E402
from mini_codex.model import ModelError, make_backend  # noqa: E402

TASKS_DIR = os.path.join(ROOT, "tasks")

MODE_TOOLS = {
    "legacy": ["exec", "read_file", "write_file", "list_dir"],
    "patch": ["exec", "read_file", "apply_patch", "list_dir"],
    "all": ["exec", "read_file", "write_file", "apply_patch", "list_dir"],
}

# 每个模式真正的「编辑接口」。exec 只用来跑测试和只读查看，
# 否则 agent 可以用 sed / Set-Content 之类绕过被测的编辑工具，
# 对照实验就失去意义了。
EDIT_TOOL = {
    "legacy": "write_file",
    "patch": "apply_patch",
    "all": None,
}

TEST_ISSUE = os.path.join("tests", "test_issue.py")
TEST_EXISTING = "test_existing.py"

_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors)")


def run_pytest(repo: str, target: str) -> dict:
    """跑一个测试目标，返回 {passed, failed, error, ok, tail}。"""
    cmd = [sys.executable, "-m", "pytest", target, "-q", "--no-header",
           "-p", "no:cacheprovider"]
    try:
        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": 0, "error": 1, "ok": False,
                "tail": "pytest 超时"}

    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    counts = {"passed": 0, "failed": 0, "error": 0}
    for num, kind in _COUNT_RE.findall(blob):
        key = "error" if kind.startswith("error") else kind
        counts[key] += int(num)

    lines = [ln for ln in blob.strip().splitlines() if ln.strip()]
    tail = lines[-1][:200] if lines else "(无输出)"
    ok = (proc.returncode == 0 and counts["failed"] == 0 and counts["error"] == 0)
    return {**counts, "ok": ok, "tail": tail}


def _snapshot(repo: str) -> dict:
    """记录仓库里每个文件的内容哈希，用于判断哪些文件被动过。"""
    import hashlib
    out = {}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        for f in files:
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, repo)] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                pass
    return out


def _diff_snapshot(before: dict, after: dict) -> set:
    """返回内容发生变化/新增/删除的文件集合。"""
    changed = set()
    for k, v in after.items():
        if before.get(k) != v:
            changed.add(k)
    for k in before:
        if k not in after:
            changed.add(k)
    return changed


def load_tasks(only=None) -> list[dict]:
    out = []
    for name in sorted(os.listdir(TASKS_DIR)):
        d = os.path.join(TASKS_DIR, name)
        if not os.path.isdir(d) or only and name != only:
            continue
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        with open(os.path.join(d, "issue.md"), encoding="utf-8") as f:
            issue = f.read()
        out.append({"id": name, "dir": d, "meta": meta, "issue": issue})
    return out


def build_task_prompt(issue: str, allowed_tools: list[str]) -> str:
    listing = ", ".join(allowed_tools)
    return (
        f"{issue}\n\n"
        "----\n"
        f"你只能使用这些工具：{listing}。\n"
        "代码在 'repo/' 目录下（你的 cwd 就是这个目录的父目录，"
        "路径请按 repo/xxx.py 书写）。\n"
        "验收命令（改完后请自己跑一遍确认）：\n"
        f"  python -m pytest {TEST_ISSUE} -q\n"
        f"  python -m pytest {TEST_EXISTING} -q\n"
        "要求：只改 repo/ 下的实现代码，不要改任何测试文件；"
        f"{TEST_EXISTING} 必须保持通过。全部完成后用一句话说明你改了哪个文件、改了什么。\n"
    )


# exec 只允许跑测试和只读查看；任何写文件的 shell 命令都会被拒绝，
# 这样 agent 不能绕过被测的编辑工具（write_file / apply_patch）。
READONLY_EXEC_DENY = [
    "sed -i", "tee ", "truncate", "dd if=", "dd of=",
    "set-content", "add-content", "out-file", "new-item",
    "remove-item", "move-item", "copy-item", "del ", "erase ",
    "rmdir", "mkdir", "md ", "ren ", "rm -", "vi ", "vim ", "nano ",
    "python -c", "python3 -c", "perl -i", "awk -i", "patch ",
    "git checkout", "git apply", ">>", " > ",
]


def install_readonly_exec():
    """把 exec 换成只读版本，返回还原函数。"""
    original = tools_mod.TOOLS.get("exec")
    if original is None:
        return lambda: None
    spec, _fn = original

    def guard(args: dict):
        cmd = (args.get("command") or "").strip()
        low = cmd.lower()
        for bad in READONLY_EXEC_DENY:
            if bad in low:
                return tools_mod.ToolResult(
                    "拒绝执行：本次评测中 exec 只能用于运行测试和只读查看，"
                    "不能用它修改文件（命中禁用模式 {!r}）。"
                    "请改用 {} 修改源代码。".format(bad, _EDIT_HINT[0]),
                    is_error=True,
                )
        return _fn(args)

    tools_mod.TOOLS["exec"] = (spec, guard)

    def restore():
        tools_mod.TOOLS["exec"] = original
    return restore


_EDIT_HINT = ["apply_patch"]


def restrict_tools(allowed: list[str]):
    """把全局工具注册表裁剪成白名单，返回还原函数。"""
    saved = dict(tools_mod.TOOLS)
    for name in list(tools_mod.TOOLS):
        if name not in allowed:
            del tools_mod.TOOLS[name]
    return lambda: tools_mod.TOOLS.update(saved)


def run_task(task: dict, tools_mode: str, max_steps: int, verbose: bool,
             model: str | None) -> dict:
    result = {
        "id": task["id"],
        "title": task["meta"].get("title", task["id"]),
        "tools": tools_mode,
        "resolved": False,
        "reason": "",
        "steps": 0,
        "seconds": 0.0,
        "tools_used": {},
    }

    allowed = MODE_TOOLS[tools_mode]
    tmp = tempfile.mkdtemp(prefix="minicodex_eval_")
    work = os.path.join(tmp, "repo")
    try:
        # 先清掉任务仓库里可能残留的缓存与上次跑留下的改动痕迹
        src_repo = os.path.join(task["dir"], "repo")
        for root, dirs, _files in os.walk(src_repo):
            for d in list(dirs):
                if d in ("__pycache__", ".pytest_cache"):
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    dirs.remove(d)
        shutil.copytree(src_repo, work)

        # ---- 自检：任务必须一开始是「issue 红 + existing 绿」 ----
        pre_issue = run_pytest(work, TEST_ISSUE)
        pre_existing = run_pytest(work, TEST_EXISTING)
        if pre_issue["ok"]:
            result["reason"] = "任务无效：隐藏测试初始就是绿的"
            return result
        if not pre_existing["ok"]:
            result["reason"] = "任务无效：原有测试初始不是绿的"
            return result
        result["baseline"] = {"issue": pre_issue["tail"], "existing": pre_existing["tail"]}

        if model:
            os.environ["OPENAI_MODEL"] = model
            os.environ["OLLAMA_MODEL"] = model

        backend = make_backend()
        session = agent_mod.Session(workdir=work)
        agent = Agent(backend, workdir=work, max_steps=max_steps, session=session)

        restore = restrict_tools(allowed)
        edit_tool = EDIT_TOOL[tools_mode]
        if edit_tool:
            _EDIT_HINT[0] = edit_tool
        restore_exec = install_readonly_exec()
        before = _snapshot(work)
        t0 = time.time()
        try:
            prompt = build_task_prompt(task["issue"], allowed)
            agent.run(prompt, on_event=_make_verbose(verbose, task["id"]))
        except ModelError as e:
            result["reason"] = f"模型错误：{str(e)[:200]}"
            result["seconds"] = round(time.time() - t0, 1)
            return result
        finally:
            restore_exec()
            restore()
            result["seconds"] = round(time.time() - t0, 1)

        for m in session.messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                result["steps"] += 1
                for tc in m["tool_calls"]:
                    nm = tc.get("function", {}).get("name", "?")
                    result["tools_used"][nm] = result["tools_used"].get(nm, 0) + 1

        # ---- 验收 ----
        after = _snapshot(work)
        changed = _diff_snapshot(before, after)
        result["files_changed"] = sorted(changed)
        denied = getattr(_make_verbose, "_denied", None)
        result["used_edit_tool"] = result["tools_used"].get(edit_tool, 0) > 0 if edit_tool else None
        if edit_tool and changed and not result["used_edit_tool"]:
            # 文件被改了，但一次都没用被测的编辑工具 -> 用旁路手段改的，结果不可信
            result["bypassed_edit_tool"] = True
        else:
            result["bypassed_edit_tool"] = False

        post_issue = run_pytest(work, TEST_ISSUE)
        post_existing = run_pytest(work, TEST_EXISTING)
        result["fail_to_pass"] = post_issue["tail"]
        result["pass_to_pass"] = post_existing["tail"]

        if not post_issue["ok"]:
            result["reason"] = f"未修复：{post_issue['tail']}"
        elif not post_existing["ok"]:
            result["reason"] = f"破坏原有测试：{post_existing['tail']}"
        elif result["bypassed_edit_tool"]:
            result["reason"] = "绕过编辑接口（用 exec 直接改文件）"
        else:
            result["resolved"] = True
            result["reason"] = "全部通过"
        return result
    except Exception as e:  # noqa: BLE001
        result["reason"] = f"运行异常：{type(e).__name__}: {str(e)[:200]}"
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        # 任务仓库只应作为「干净起点」；任何残留改动都会污染下一次运行
        src_repo = os.path.join(task["dir"], "repo")
        for root, dirs, _files in os.walk(src_repo):
            for d in list(dirs):
                if d in ("__pycache__", ".pytest_cache"):
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    dirs.remove(d)


def _make_verbose(verbose: bool, tid: str):
    if not verbose:
        return None

    def on_event(kind, payload):
        if kind == "thinking":
            print(f"\n[{tid}] 步骤 {payload['step']}", file=sys.stderr)
        elif kind == "tool":
            args = json.dumps(payload["args"], ensure_ascii=False)
            print(f"  -> {payload['name']} {args[:160]}", file=sys.stderr)
        elif kind == "tool_result":
            head = payload["content"].replace("\n", " | ")[:160]
            print(f"     <- {head}", file=sys.stderr)
        elif kind == "answer":
            print(f"  = {payload['text'][:200]}", file=sys.stderr)
    return on_event


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mini-codex 对照评测")
    ap.add_argument("--task", help="只跑某一个任务（目录名）")
    ap.add_argument("--tools", choices=sorted(MODE_TOOLS), default="all",
                    help="工具集：legacy=write_file / patch=apply_patch / all=两者都给")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--model", help="覆盖模型名")
    ap.add_argument("--json", dest="json_out", help="把结果写到该 json 文件")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每步工具调用")
    args = ap.parse_args(argv)

    tasks = load_tasks(only=args.task)
    if not tasks:
        print("没有找到任务", file=sys.stderr)
        return 2

    results = []
    for t in tasks:
        r = run_task(t, args.tools, args.max_steps, args.verbose, args.model)
        results.append(r)
        flag = "RESOLVED  " if r["resolved"] else "UNRESOLVED"
        print(f"{flag}  {r['title']:<24}  {r['reason']}  "
              f"[{r['steps']}步 {r['seconds']}s]")

    n = len(results)
    k = sum(1 for r in results if r["resolved"])
    print("-" * 72)
    print(f"resolved: {k}/{n} = {100.0 * k / n:.1f}%   (tools={args.tools})")
    for r in results:
        if r["tools_used"]:
            used = ", ".join(f"{a}x{b}" for a, b in sorted(r["tools_used"].items()))
            print(f"  {r['id']:<24} tools: {used}")
    avg_steps = sum(r["steps"] for r in results) / n
    print(f"平均步数: {avg_steps:.1f}")

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"tools": args.tools, "resolved": k, "total": n,
                       "results": results}, f, ensure_ascii=False, indent=2)
        print(f"结果已写入 {args.json_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
