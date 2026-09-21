"""模型后端抽象。

对应 Codex 的 `codex-client` / `model-provider` / `ollama` 层：
把「调用一次能 function-calling 的模型」统一成一个接口，屏蔽
OpenAI 兼容接口和本地 Ollama 的差异。

返回协议统一为最小三元组：
    text: str            模型的文字/结论
    tool_calls: list     本次请求出的工具调用

流式支持：`complete_stream(messages, tools, on_delta)`，on_delta(kind, text)
kind ∈ {"reasoning", "text"}。工具调用阶段需要完整 JSON，故工具调用不带流式。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelError(RuntimeError):
    pass


class BaseBackend:
    def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        raise NotImplementedError

    def complete_stream(self, messages: list[dict], tools: list[dict], on_delta) -> ModelResponse:
        # 默认退化到非流式
        resp = self.complete(messages, tools)
        if resp.text:
            on_delta("text", resp.text)
        return resp


def _parse_tool_calls(choice_msg: dict) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for tc in choice_msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments") or "{}"
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}
        else:
            args = raw_args
        tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""),
                                   arguments=args))
    return tool_calls


class OpenAICompatibleBackend(BaseBackend):
    def __init__(self, base_url=None, api_key=None, model=None):
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL",
                                                    "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def _payload(self, messages, tools, stream):
        p = {"model": self.model, "messages": messages,
             "temperature": 0.2, "max_tokens": 4096, "stream": stream}
        if tools:
            p["tools"] = [{"type": "function", "function": t} for t in tools]
            p["tool_choice"] = "auto"
        return p

    def complete(self, messages, tools) -> ModelResponse:
        from urllib import request as urlreq
        from urllib.error import HTTPError, URLError
        payload = self._payload(messages, tools, stream=False)
        req = urlreq.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urlreq.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            raise ModelError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:500]}")
        except URLError as e:
            raise ModelError(f"网络错误: {e.reason}")
        msg = data["choices"][0]["message"]
        return ModelResponse(text=msg.get("content") or "",
                             tool_calls=_parse_tool_calls(msg))

    def complete_stream(self, messages, tools, on_delta) -> ModelResponse:
        from urllib import request as urlreq
        from urllib.error import HTTPError, URLError
        payload = self._payload(messages, tools, stream=True)
        req = urlreq.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            resp = urlreq.urlopen(req, timeout=300)
        except HTTPError as e:
            raise ModelError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:500]}")
        except URLError as e:
            raise ModelError(f"网络错误: {e.reason}")

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        # 按工具索引累积片段
        tc_acc: dict[int, dict] = {}

        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                # reasoning 增量（kimi / deepseek 等）
                rc = delta.get("reasoning_content")
                if rc:
                    reasoning_parts.append(rc)
                    on_delta("reasoning", rc)

                c = delta.get("content")
                if c:
                    content_parts.append(c)
                    on_delta("text", c)

                # 工具调用增量
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tc_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]

        for idx in sorted(tc_acc):
            s = tc_acc[idx]
            try:
                args = json.loads(s["args"]) if s["args"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=s["id"], name=s["name"], arguments=args))

        return ModelResponse(text="".join(content_parts), tool_calls=tool_calls)


class OllamaBackend(BaseBackend):
    def __init__(self, base_url=None, model=None):
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL",
                                                    "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5")

    def _payload(self, messages, tools, stream):
        p = {"model": self.model, "messages": messages, "stream": stream}
        if tools:
            p["tools"] = tools
        return p

    def complete(self, messages, tools) -> ModelResponse:
        from urllib import request as urlreq
        from urllib.error import HTTPError, URLError
        req = urlreq.Request(
            self.base_url + "/api/chat",
            data=json.dumps(self._payload(messages, tools, False)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlreq.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            raise ModelError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:500]}")
        except URLError as e:
            raise ModelError(f"无法连接 Ollama（{self.base_url}）: {e.reason}")
        msg = data.get("message", {})
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(id=str(len(tool_calls)), name=fn.get("name", ""),
                                       arguments=args))
        return ModelResponse(text=msg.get("content") or "", tool_calls=tool_calls)

    def complete_stream(self, messages, tools, on_delta) -> ModelResponse:
        from urllib import request as urlreq
        from urllib.error import HTTPError, URLError
        req = urlreq.Request(
            self.base_url + "/api/chat",
            data=json.dumps(self._payload(messages, tools, True)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urlreq.urlopen(req, timeout=600)
        except HTTPError as e:
            raise ModelError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:500]}")
        except URLError as e:
            raise ModelError(f"无法连接 Ollama（{self.base_url}）: {e.reason}")
        text = []
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                c = (chunk.get("message") or {}).get("content") or ""
                if c:
                    text.append(c)
                    on_delta("text", c)
        return ModelResponse(text="".join(text))


def make_backend() -> BaseBackend:
    kind = os.environ.get("MINI_CODEX_BACKEND", "openai").lower()
    if kind == "ollama":
        return OllamaBackend()
    return OpenAICompatibleBackend()
