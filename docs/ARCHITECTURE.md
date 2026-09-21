# Codex 拆解笔记：它到底是怎么工作的

> 结论基于 `openai/codex` 仓库 `codex-rs` 源码阅读。目标是抓住「本质」，
> 用于指导 `mini-codex` 的最小实现。

## 1. 一句话总结

Codex 的核心不是模型本身，而是一个**工具执行循环（agent loop）**：

```
用户输入 → 构造提示词(含工具 schema) → 调模型
        → 模型返回「要么回答，要么要调用工具」
        → 若调用工具：审批 → 选沙箱 → 执行 → 把结果塞回消息历史
        → 再次调模型 → ... 直到模型不再请求工具
```

模型权重和云端推理不开源；开源的 `codex-rs` 就是把这个循环工程化地做出来。

## 2. 仓库真实结构（不是直觉以为的那样）

- `codex-cli/` —— 只有一个 `bin/` + `package.json`，是 npm **发布壳**。
- `codex-rs/` —— 真正的本体，一个含 **100+ 个 crate 的 Rust workspace**。
- 关键 crate 按职责分层：

| 职责 | crate / 目录 | 关键文件 |
|---|---|---|
| 会话/状态机 | `core/src/session/` | `turn.rs`(3000+ 行单轮执行)、`session.rs`、`mod.rs` |
| 协议/消息模型 | `protocol/src/` | `items.rs`、`models.rs`、`protocol.rs` |
| 工具抽象 | `tools/src/` | `tool_definition.rs`、`tool_executor.rs` |
| 工具编排 | `core/src/tools/` | `orchestrator.rs`(审批+沙箱+重试)、`registry.rs`、`router.rs` |
| 命令执行 | `core/src/unified_exec/` | 长驻进程、stdin 交互、head/tail 缓冲 |
| 补丁应用 | `core/src/apply_patch.rs` | 模型改文件的文本 patch 协议 |
| 沙箱 | `sandboxing/`、`linux-sandbox/`、`windows-sandbox-rs/` | 进程隔离 |
| 模型提供商 | `model-provider/`、`ollama/`、`lmstudio/` | 后端抽象 + 本地模型 |
| 配置/登录 | `config/`、`login/`、`secrets/` | 配置与鉴权 |
| 前端 | `tui/`、`app-server/`、`code-mode/` | 终端UI / 桌面 / 编辑器 |

## 3. 工具系统：一切都是「定义 + 执行」

`ToolDefinition`（`tools/src/tool_definition.rs`）就是工具的全部元数据：

```rust
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub input_schema: JsonSchema,      // 输入参数 = JSON Schema
    pub output_schema: Option<ToolOutputSchema>,
    pub defer_loading: bool,
}
```

- `ToolExecutor::handle(...)` 返回 `Result<ToolOutput, FunctionCallError>`。
- 工具通过 `registry` 注册，通过 `router` 按名字分发；`Direct` 工具一开始
  就暴露给模型，`Deferred` 工具要靠 tool-search 按需加载（省 token）。

## 4. 工具编排（orchestrator.rs）的固定节奏

`ToolOrchestrator` 的注释写得明明白白，任何工具调用都是这套序列：

```
approval → select sandbox → attempt
        → (被拒绝时) 用升级后的沙箱策略重试（有缓存，无需重复审批）
```

即：**审批 → 选沙箱 → 执行 → 升级重试**。

## 5. 对 mini-codex 的映射

我们刻意砍掉沙箱、审批缓存、多 agent、MCP、TTY 长驻进程、autocompact 等
工程复杂度，只保留能跑通的最小闭环：

| Codex 概念 | mini-codex 对应 |
|---|---|
| `ModelClientSession` / Responses API | `model.py` 的 `complete()` 调用 |
| `ToolDefinition` | `tools.py` 里的 `ToolSpec` dataclass |
| `ToolExecutor::handle` | `tools.py` 里的工具函数 |
| `ToolOrchestrator` 循环 | `agent.py` 里的 `run_loop()` |
| `turn.rs` 单轮 | `agent.py` 的 while 循环一次迭代 |
| `unified_exec` 命令执行 | `subprocess` 包一层 |
| `apply_patch` | 简化版的 patch 文本协议 |

## 6. 最小闭环要满足的硬性条件

1. 消息历史里**必须回填工具结果**，模型才知道执行结果。
2. 工具 schema 要作为 `tools` 参数传给模型（function calling）。
3. 循环要有**上限**（max steps），防止死循环烧钱。
4. 命令执行要有**超时 + 输出截断**，避免卡死/爆上下文。
