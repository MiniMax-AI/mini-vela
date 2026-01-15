# mini-vela

一个用于评估 AI Coding Agent 指令遵循能力的基准测试框架。通过 LiteLLM Proxy 拦截 API 调用，收集完整的交互轨迹，并使用 LLM 进行自动化评分。

## 🌟 特性

- **多脚手架支持**：支持 Claude Code、Kilo-Dev、Droid 等多种 AI 开发工具
- **轨迹收集**：自动拦截并记录完整的 API 调用轨迹
- **自动评估**：基于 Checklist 使用 LLM 对轨迹进行多维度评分
- **Docker 隔离**：每个任务实例在独立容器中运行，环境干净隔离

## 🏗️ 核心流程

1. **Proxy 启动**：LiteLLM Proxy 在宿主机运行，拦截所有 API 调用
2. **任务执行**：Docker 容器中运行 Claude Code、Kilo、Droid 等脚手架完成任务
3. **轨迹收集**：每个 API 请求/响应被记录到独立的 JSONL 文件（原始轨迹）
4. **轨迹处理**：使用 `convert/` 工具对原始轨迹进行去重、合并，生成完整的对话轨迹
5. **自动评估**：基于 Checklist 使用 LLM 对合并后的轨迹进行评分

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Docker
- LLM API Key（Anthropic / MiniMax / Gemini 等）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置 API Keys

```bash
cd proxy
cp env.sh.example env.sh
# 编辑 env.sh，填入你的 API Keys
source env.sh
```

### 运行评估

```bash
# 1. 启动 Proxy（终端窗口 1）
cd proxy
source env.sh
python start_proxy.py

# 2. 运行评估流水线（终端窗口 2）
./run.sh

# 指定模型
./run.sh --model claude-opus-4-5-20251101
```

## 📁 项目结构

```
benchmark/
├── run.sh                   # 一键运行脚本（任务执行 + 轨迹处理 + 评估）
├── benchmark_runner.py      # Benchmark 运行器主程序
├── evaluate.py              # 轨迹评估脚本
├── requirements.txt         # Python 依赖
│
├── scaffolds/               # 脚手架模块（多工具支持）
│   ├── __init__.py          # 脚手架注册与工厂函数
│   ├── base.py              # 抽象基类定义
│   ├── claudecode.py        # Claude Code 脚手架实现
│   ├── kilo_dev.py          # Kilo-Dev 脚手架实现
│   └── droid.py             # Droid 脚手架实现
│
├── proxy/                   # LiteLLM Proxy 组件（轨迹收集）
│   ├── start_proxy.py       # Proxy 启动脚本
│   ├── trajectory_logger.py # 轨迹日志记录器（自定义 Callback）
│   ├── litellm_config.yaml  # LiteLLM 模型配置
│   ├── env.sh.example       # 环境变量配置模板
│   └── Dockerfile           # Proxy 容器化配置
│
└── convert/                 # 轨迹处理工具（去重合并）
    ├── convert_cc_traj_to_msg.py  # 主程序：Ray 并行处理轨迹
    ├── dedup.py             # 去重逻辑
    └── utils.py             # Completion 数据结构 + 格式转换
```

## 📊 数据格式

### 任务实例格式

任务实例从 [HuggingFace MiniMaxAI/OctoCodingBench](https://huggingface.co/datasets/MiniMaxAI/OctoCodingBench) 加载，每条记录为 JSON 格式：

```json
{
  "instance_id": "benchmark-example-001",
  "user_query": ["请帮我分析这个函数的工作原理"],
  "system_prompt": "",
  "category": "Claude.md",
  "image": "docker-image:tag",
  "workspace_abs_path": "/app",
  "scaffold": {
    "name": "claudecode",
    "version": "2.0.69"
  },
  "checklist": {
    "SP": {
      "description": "System Prompt 约束说明",
      "checks": [
        {
          "check_id": "SP_language_match",
          "description": "检查是否使用正确的语言",
          "check_type": "compliance"
        }
      ]
    }
  }
}
```

**关键字段说明：**

- `scaffold.name`: 使用的脚手架名称（claudecode / kilo-dev / droid）
- `user_query`: 用户查询列表，支持多轮对话
- `checklist`: 评估检查项，按类别组织

### 原始轨迹格式 (trajectories/*.jsonl)

Proxy 收集的原始轨迹，每个 API 调用一条记录：

```json
{
  "instance_id": "benchmark-example-001",
  "timestamp": "2024-12-27T10:00:00.000Z",
  "success": true,
  "model": "claude-sonnet-4-5-20250929",
  "request": {
    "messages": [...],
    "tools": [...],
    "system": [...]
  },
  "response": {
    "content": "...",
    "thinking_blocks": [...],
    "tool_calls": [...],
    "finish_reason": "end_turn"
  },
  "usage": {
    "prompt_tokens": 1000,
    "completion_tokens": 500,
    "total_tokens": 1500
  }
}
```

### 合并后轨迹格式 (merged_trajectories.jsonl)

经过 `convert/` 处理后的完整对话轨迹：

```json
{
  "meta": {
    "session_id": "abc123",
    "biz_id": "benchmark",
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 8192
  },
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "Read",
        "description": "读取文件内容",
        "parameters": { "type": "object", "properties": {...} }
      }
    }
  ],
  "messages": [
    { "role": "system", "content": "You are a helpful assistant..." },
    { "role": "user", "content": "请帮我分析这个函数" },
    { 
      "role": "assistant", 
      "content": "好的，让我先读取文件...",
      "reasoning_content": "用户需要分析函数，我应该先...",
      "tool_calls": [{ "name": "Read", "arguments": {...} }],
      "generation": true
    },
    { "role": "tool", "tool_name": "Read", "content": "文件内容..." },
    { 
      "role": "assistant", 
      "content": "这个函数的作用是...",
      "reasoning_content": "根据代码内容...",
      "generation": true
    }
  ]
}
```

**关键字段说明：**

- `reasoning_content`: 模型的思考过程（thinking block）
- `tool_calls`: 工具调用列表

### 评估结果格式 (scores.json)

```json
{
  "results": [
    {
      "instance_id": "benchmark-example-001",
      "success": true,
      "reward": 0.85,
      "eval_result": {
        "SP": {
          "reasoning": "整体分析...",
          "checklist": [
            {
              "check_id": "SP_language_match",
              "reasoning": "具体分析...",
              "result": "success"
            }
          ]
        }
      }
    }
  ],
  "summary": {
    "total": 10,
    "success_count": 9,
    "avg_reward": 0.82
  }
}
```

## ⚙️ 配置说明

### LiteLLM Proxy 配置 (proxy/litellm_config.yaml)

```yaml
model_list:
  # Anthropic Claude
  - model_name: claude-sonnet-4-5-20250929
    litellm_params:
      model: anthropic/claude-sonnet-4-5-20250929
      api_key: os.environ/ANTHROPIC_API_KEY

  # Google Gemini
  - model_name: gemini-3-pro
    litellm_params:
      model: gemini/gemini-3-pro-preview-05-06
      api_key: os.environ/GEMINI_API_KEY

  # MiniMax
  - model_name: MiniMax-M2.1
    litellm_params:
      model: anthropic/MiniMax-M2.1
      api_base: https://api.minimaxi.com/anthropic
      api_key: os.environ/MINIMAX_API_KEY
```

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `TRAJECTORY_OUTPUT_DIR` | 轨迹输出目录 | `./trajectories` |
| `LITELLM_PORT` | Proxy 监听端口 | `4000` |
| `ANTHROPIC_API_KEY` | Anthropic API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key（评估用） | - |
| `OPENAI_BASE_URL` | OpenAI API Base URL | - |

## 🔧 高级用法

### Docker 部署 Proxy

```bash
cd proxy
docker build -t benchmark-proxy .
docker run -d \
    -p 4000:4000 \
    -v /path/to/trajectories:/app/trajectories \
    -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
    benchmark-proxy
```

### 扩展轨迹记录

继承 `TrajectoryLogger` 类并重写 `_build_record` 方法来添加自定义字段。

## 📝 License

MIT License