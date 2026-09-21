"""Agent loop —— mini-codex 的核心。

对应 Codex 的 session/turn.rs + tools/orchestrator.rs 的极简版：

    while 未完成 and steps < max_steps:
        resp = model.complete(messages, tools)   # 调模型
        if resp.tool_calls:                       # 模型要调工具
            for call in resp.tool_calls:
                result = execute_tool(...)        # 执行工具
                messages 回填 assistant(tool_calls) + tool(result)
        else:                                     # 模型直接回答
            结束

一个 Agent 实例对应一个「会话」。会话的 messages 可以：
- 序列化保存到 .jsonl 文件（save_history）
- 从 .jsonl 恢复（load_history）
从而实现跨次启动的多轮对话记忆。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .model import BaseBackend, ModelResponse
from .tools import execute_tool, tool_schemas


SYSTEM_PROMPT = """你是一个编码代理（coding agent），在用户的文件系统里工作。

你的工作方式是一个循环：
1. 分析当前任务，决定下一步该做什么。
2. 要么直接调用工具（exec/read_file/write_file/list_dir）去观察或修改环境，
   要么给出最终回答。
3. 每次调用工具后会看到结果，再决定下一步，直到任务完成。

规则：
- 写代码前先看现有文件（read_file / list_dir），不要盲目覆盖。
- 对不确定的环境，先用 exec 做只读探查。
- 任务真正完成后，用简洁的中文总结你做了什么（关键文件、如何验证）。
- 如果卡住了，说明卡在哪里、需要什么。
"""


@dataclass
class Session:
    """一个可持久化的会话。"""
    workdir: str
    messages: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.messages:
            self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]


class Agent:
    def __init__(self, backend: BaseBackend, workdir: str = ".", max_steps: int = 30,
                 session: Session | None = None):
        self.backend = backend
        self.workdir = workdir
        self.max_steps = max_steps
        self.session = session or Session(workdir=workdir)

    # ---------- 历史存取 ----------
    def save_history(self, path: str):
        """把会话 messages 存成 .jsonl（每行一条消息）。"""
        with open(path, "w", encoding="utf-8") as f:
            for m in self.session.messages:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def load_history(self, path: str):
        """从 .jsonl 恢复会话 messages（会覆盖当前 session 消息）。"""
        msgs = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    msgs.append(json.loads(line))
        if not msgs or msgs[0].get("role") != "system":
            msgs.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
        self.session.messages = msgs

    # ---------- 核心 loop ----------
    def run(self, task: str | None, on_event=None) -> str:
        """执行一次对话。

        - task 为空字符串/None 时：仅在没有用户消息的情况下视为需要新输入，
          由调用方先行 append 用户消息。
        实际约定：调用前若 task 非空，则由 run 负责 append 一条用户消息。
        """
        emit = on_event or (lambda kind, payload: None)

        if task:
            content = f"工作目录：{self.workdir}\n\n任务：{task}"
            self.session.messages.append({"role": "user", "content": content})

        tools = tool_schemas()

        for step in range(self.max_steps):
            emit("thinking", {"step": step + 1})
            resp: ModelResponse = self.backend.complete_stream(
                self.session.messages, tools,
                on_delta=lambda kind, text: emit("delta", {"kind": kind, "text": text}),
            )

            if resp.tool_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": resp.text or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": _dumps(tc.arguments),
                            },
                        }
                        for tc in resp.tool_calls
                    ],
                }
                self.session.messages.append(assistant_msg)

                for tc in resp.tool_calls:
                    emit("tool", {"name": tc.name, "args": tc.arguments})
                    res = execute_tool(tc.name, tc.arguments)
                    self.session.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": res.to_message(),
                    })
                    emit("tool_result", {
                        "name": tc.name,
                        "content": res.to_message()[:400],
                    })
                continue

            # 模型直接回答：记录并返回
            final = (resp.text or "").strip()
            if final:
                self.session.messages.append({"role": "assistant", "content": final})
            emit("answer", {"text": final})
            return final or "(模型未产生文本输出)"

        fallback = f"(达到最大步数 {self.max_steps}，任务未明确完成)"
        emit("answer", {"text": fallback})
        return fallback


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)

