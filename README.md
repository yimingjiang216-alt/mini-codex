# mini-codex

一个从零手写的极简编程代理（coding agent），架构源自对
[openai/codex](https://github.com/openai/codex) `codex-rs` 源码的拆解与复刻。

它不是 Codex 的替代品，而是一个**教学性质的最小实现**：用约 400 行 Python 抓住
Codex 的核心本质——「模型 ↔ 工具」的执行循环（agent loop），让读者能逐行读懂
一个编程代理到底是怎么工作起来的。

## ✨ 特性

- 🔁 **Agent Loop**：模型自主决定调用工具、观察结果、继续推理，直至完成任务
- 🧰 **内置工具**：`exec`、`read_file`、`apply_patch`、`write_file`、`list_dir`
- 🩹 **补丁式编辑**：`apply_patch` 复刻 Codex 的补丁语法，改大文件不必整文件重写；
  语法与边界行为对齐 `codex-rs/apply-patch` 的 25 个官方测试场景
- 🔍 **编辑后自动语法检查**：补丁应用后立刻做一次语法检查，发现问题直接回灌给模型
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
| `apply-patch/src/parser.rs` | `patch.py` | 补丁语法解析 |
| `apply-patch/src/file_update.rs` | `patch_apply.py` | 按 chunk 定位并改写文件 |

```
mini_codex/
  model.py        # 模型后端（OpenAI 兼容 + Ollama，含流式）
  tools.py        # 工具定义 / 注册 / 执行
  patch.py        # apply_patch 补丁语法解析
  patch_apply.py  # 补丁落盘（定位、替换、移动、新增、删除）
  linting.py      # 编辑后语法检查
  agent.py        # agent loop（核心）
  cli.py          # 终端入口（单次 + 对话模式）
  __main__.py

eval/
  run_eval.py     # 对照实验脚本
  results.json    # 实测结果

tasks/            # 7 个自建任务（各自是一个带 bug 的迷你仓库）
```

## 🧪 评测

`tasks/` 下有 7 个自建任务，每个都是一个独立的小仓库：一个带 bug 的实现、
一组「必须保持通过」的原有测试（`test_existing.py`）、一组「修复前必须是红的」
验收测试（`tests/test_issue.py`），以及给 agent 看的 `issue.md`。

同一批任务、同一个模型，分别只给两种编辑接口跑一遍对照：

| 模式 | 编辑接口 | 解决 | 总步数 | 总耗时 |
|---|---|---|---|---|
| legacy | `write_file`（整文件重写） | 7/7 | 77 | 200.7s |
| patch | `apply_patch`（补丁式） | 7/7 | 65 | 164.0s |

模型 `deepseek-v4-flash`，步数上限 30，`exec` 限制为只读以免绕过被测的编辑接口。

**要如实说明的结论**：在这个任务规模上，两种接口的**解决率没有差别**，都是全对。
差别体现在**开销**上——任务越大越明显：

| 任务 | 源文件行数 | legacy 步/耗时 | patch 步/耗时 | write_file 输出 | apply_patch 输出 |
|---|---|---|---|---|---|
| t4 LRU 缓存 | 29 | 7 步 14.6s | 8 步 19.9s | 684 字符 | 289 字符 |
| t6 日程区间（大文件） | 348 | 15 步 66.8s | 8 步 17.5s | 9597 字符 | 293 字符 |
| t7 单位换算（大文件） | 462 | 20 步 43.5s | 14 步 28.9s | 13892 字符 | 352 字符 |

小文件上两者基本等价，甚至 `write_file` 更省事（`apply_patch` 要额外花步骤理解补丁语法）。
一旦文件到几百行、而改动只有一两行，`write_file` 需要模型把整个文件重新输出一遍，
开销随文件大小线性增长；`apply_patch` 的输出量基本只由改动大小决定。

复现：

```bash
python eval/run_eval.py --tools legacy --json eval/result_legacy.json
python eval/run_eval.py --tools patch  --json eval/result_patch.json
```


## ⚠️ 局限

这是教学项目，刻意省略了真实 Codex 的工程能力，包括：

- ❌ 沙箱与权限审批
- ❌ 多 agent、MCP、插件、自动上下文压缩
- ❌ 流式解析（工具调用要等完整 JSON 才能执行）
- ❌ 会话级上下文压缩与 token 预算控制

## 📄 许可

[MIT](LICENSE)

## 🙏 致谢

架构理解源自 [openai/codex](https://github.com/openai/codex) 的开源代码。
