# mini-codex

一个从零手写的极简编程代理（coding agent），架构源自对
[openai/codex](https://github.com/openai/codex) `codex-rs` 源码的拆解与复刻。

它不是 Codex 的替代品，而是一个**教学性质的最小实现**：用约 400 行 Python 抓住
Codex 的核心本质——「模型 ↔ 工具」的执行循环（agent loop），让读者能逐行读懂
一个编程代理到底是怎么工作起来的。

## ✨ 特性

- 🔁 **Agent Loop**：模型自主决定调用工具、观察结果、继续推理，直至完成任务
- 🧰 **内置工具**：`exec`、`read_file`、`write_file`、`list_dir`
- 💬 **多轮对话**：交互式 REPL，跨轮次记住上下文
- 💾 **会话持久化**：历史保存到 `.jsonl`，重启后继续
- ⚡ **流式输出**：思考过程与回答逐字流式显示，体验更顺
- 🔌 **双后端**：任意 OpenAI 兼容接口 + 本地 Ollama

## 🚀 快速开始

### 环境要求

- Python 3.9+

### 1. 克隆

```bash
git clone <你的仓库地址>
cd mini-codex
```

### 2. 配置模型

**方式 A：OpenAI 兼容接口**（推荐，支持大多数模型）

```bash
export OPENAI_BASE_URL="https://api.openai.com/v1"   # 或任意兼容网关
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o-mini"
```

**方式 B：本地 Ollama**（免费、离线）

```bash
ollama pull qwen2.5   # 需先安装 Ollama 并运行 ollama serve
export MINI_CODEX_BACKEND=ollama
export OLLAMA_MODEL=qwen2.5
```

> PowerShell 用户把 `export X=Y` 换成 `$env:X="Y"`，
> 并使用 `python -X utf8 -m mini_codex ...` 避免中文乱码。

### 3. 运行

单次任务模式：

```bash
python -m mini_codex "列出当前目录下所有文件"
```

对话模式（带历史持久化）：

```bash
python -m mini_codex -s session.jsonl
```

## 📖 使用示例

```
$ python -m mini_codex "帮我看看这个项目里有哪些文件"

[步骤 1] 思考中...
The user wants to list the files...        ← 思考过程（流式）
  → 调用工具 list_dir: {"path": "."}
    ↳ 结果: README.md
      docs
      mini_codex
      pyproject.toml

[步骤 2] 思考中...
当前目录下有 README.md、docs、mini_codex、pyproject.toml ...   ← 最终回答（流式）
```

## 🧭 架构（与 Codex 的对应关系）

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。核心映射如下：

| Codex (`codex-rs`) | mini-codex | 说明 |
|---|---|---|
| `tools/src/tool_definition.rs` | `tools.py` 的 `ToolSpec` | 工具元数据（name + description + JSON Schema） |
| `core/src/tools/orchestrator.rs` | `agent.py` 的循环 | 审批→执行→回填结果的调度 |
| `core/src/session/turn.rs` | `agent.py` 的 while 循环 | 单轮执行 |
| `model-provider/` / `ollama/` | `model.py` | 模型后端抽象 |

```
mini_codex/
  model.py      # 模型后端（OpenAI 兼容 + Ollama，含流式）
  tools.py      # 工具定义 / 注册 / 执行
  agent.py      # agent loop（核心）
  cli.py        # 终端入口（单次 + 对话模式）
  __main__.py
```

## ⚠️ 局限

这是教学项目，刻意省略了真实 Codex 的工程能力，包括：

- ❌ `apply_patch`（精准修改大文件，当前只能整文件重写）
- ❌ 沙箱与权限审批
- ❌ 多 agent、MCP、插件、自动上下文压缩

## 📄 许可

[MIT](LICENSE)

## 🙏 致谢

架构理解源自 [openai/codex](https://github.com/openai/codex) 的开源代码。
