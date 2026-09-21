"""终端入口。"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import Agent, Session
from .model import ModelError, make_backend

# 流式输出状态：本轮是否已经实时流过最终文字答案
_streamed_text = [False]


def _reset_stream():
    _streamed_text[0] = False


def _print_event(kind: str, payload: dict):
    if kind == "thinking":
        print(f"\n[步骤 {payload['step']}] 思考中...", file=sys.stderr)
    elif kind == "tool":
        args = json.dumps(payload["args"], ensure_ascii=False)
        print(f"  → 调用工具 {payload['name']}: {args}", file=sys.stderr)
    elif kind == "tool_result":
        content = payload["content"].replace("\n", "\n    ")
        print(f"    ↳ 结果: {content}", file=sys.stderr)
    elif kind == "delta":
        if payload["kind"] == "reasoning":
            print(payload["text"], end="", file=sys.stderr, flush=True)
        else:
            _streamed_text[0] = True
            print(payload["text"], end="", file=sys.stdout, flush=True)
    elif kind == "answer":
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mini-codex",
                                 description="极简编码代理（Codex 最小克隆）")
    ap.add_argument("task", nargs="?", help="要执行的任务描述；省略则进入对话模式")
    ap.add_argument("--workdir", "-d", default=".", help="工作目录（默认当前目录）")
    ap.add_argument("--max-steps", type=int, default=30, help="最大工具循环步数")
    ap.add_argument("--backend", choices=["openai", "ollama"],
                    help="模型后端（默认读 MINI_CODEX_BACKEND 或 openai）")
    ap.add_argument("--model", help="覆盖模型名")
    ap.add_argument("--session", "-s", default=None,
                    help="会话文件(.jsonl)。对话模式下可记住历史")
    args = ap.parse_args(argv)

    if args.backend:
        os.environ["MINI_CODEX_BACKEND"] = args.backend
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model
        os.environ["OLLAMA_MODEL"] = args.model

    try:
        backend = make_backend()
    except ModelError as e:
        print(f"模型错误: {e}", file=sys.stderr)
        return 2

    session = Session(workdir=args.workdir)
    agent = Agent(backend, workdir=args.workdir, max_steps=args.max_steps,
                  session=session)

    if args.session and os.path.exists(args.session):
        agent.load_history(args.session)

    # 单次任务模式
    if args.task:
        _reset_stream()
        try:
            result = agent.run(args.task, on_event=_print_event)
        except ModelError as e:
            print(f"模型错误: {e}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("\n已中断", file=sys.stderr)
            return 130
        if args.session:
            agent.save_history(args.session)
        if _streamed_text[0]:
            print("\n" + "=" * 60)  # 流式已输出正文，只补个分隔
        else:
            print("\n" + "=" * 60)
            print(result)
        return 0

    # 对话模式
    print("进入对话模式（输入 exit / quit 退出，Ctrl+C 取消当前回复）")
    print(f"工作目录: {args.workdir}")
    if args.session:
        print(f"会话文件: {args.session}（将持久化历史）")
    print("-" * 60)

    while True:
        try:
            line = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            break
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            print("再见。")
            break
        _reset_stream()
        try:
            result = agent.run(line, on_event=_print_event)
        except ModelError as e:
            print(f"模型错误: {e}", file=sys.stderr)
            continue
        except KeyboardInterrupt:
            print("\n(已取消本次回复)", file=sys.stderr)
            continue
        if _streamed_text[0]:
            print()  # 流式正文已打印，补换行
        else:
            print(result)
        if args.session:
            agent.save_history(args.session)

    return 0
