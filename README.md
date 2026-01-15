# mini-vela

一个用于评估 AI Coding Agent 指令遵循能力的基准测试框架。通过 LiteLLM Proxy 拦截 API 调用，收集完整的交互轨迹，并使用 LLM 进行自动化评分。

## 🌟 特性

- **多脚手架支持**：支持 Claude Code、Kilo-Dev、Droid 等多种 AI 开发工具
- **轨迹收集**：自动拦截并记录完整的 API 调用轨迹
- **自动评估**：基于 Checklist 使用 LLM 对轨迹进行多维度评分
- **Docker 隔离**：每个测试用例在独立容器中运行，环境干净隔离

## 🏗️ 核心流程

1. **Proxy 启动**：LiteLLM Proxy 在宿主机运行，拦截所有 API 调用
2. **任务执行**：Docker 容器中运行 Claude Code、Kilo、Droid 等脚手架完成测试任务
3. **轨迹收集**：每个 API 请求/响应被记录到独立的 JSONL 文件（原始轨迹）
4. **轨迹处理**：使用 `convert/` 工具对原始轨迹进行去重、合并，生成完整的对话轨迹
5. **自动评估**：基于 Checklist 使用 LLM 对合并后的轨迹进行评分

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Docker
- 有效的 Anthropic API Key

### 安装依赖

```bash
# 安装 LiteLLM Proxy 依赖
pip install 'litellm[proxy]'

# 安装轨迹处理依赖
pip install ray

# 安装评估脚本依赖
pip install openai
```

### 配置 API Keys

```bash
cd proxy
cp env.sh.example env.sh
# 编辑 env.sh，填入你的 API Keys
source env.sh
```

### 运行示例

```bash
# 1. 启动 Proxy（新终端窗口）
cd proxy
source env.sh  # 加载 API Keys
python start_proxy.py

# 2. 运行 Benchmark（另一个终端窗口）
# 默认从 HuggingFace 加载 MiniMaxAI/OctoCodingBench 数据集
python benchmark_runner.py

# 使用本地文件调试
python benchmark_runner.py --dataset test/data_debug.jsonl

# 指定模型运行
python benchmark_runner.py --model claude-opus-4-5-20251101

# 查看支持的模型列表
python benchmark_runner.py --list-models

# 3. 轨迹处理：去重合并原始轨迹
python convert/convert_cc_traj_to_msg.py \
    --input_path ./results/trajectories \
    --output_path ./results/merged_trajectories.jsonl

# 4. 评估结果
python evaluate.py \
    --trajectories ./results/merged_trajectories.jsonl \
    --dataset MiniMaxAI/OctoCodingBench \
    --output ./results/scores.json
```

## 📁 项目结构

```
benchmark/
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
    ├── dedup.py             # 去重逻辑 + Generation 标记
    └── utils.py             # Completion 数据结构 + 格式转换
```

## 📖 使用说明

### 运行 Benchmark

`benchmark_runner.py` 负责调度测试用例并在 Docker 容器中执行任务。支持多种脚手架和模型。

```bash
python benchmark_runner.py \
    --dataset MiniMaxAI/OctoCodingBench \  # HuggingFace 数据集或本地 JSONL 文件
    --model claude-sonnet-4-5-20250929 \   # 指定模型（可选）
    --timeout 3600 \                       # 单任务超时（秒）
    --case instance_id                     # 可选：只运行指定用例
```

**工作流程：**

1. 读取测试用例文件（JSONL 格式）
2. 根据 `scaffold.name` 选择对应的脚手架实现
3. 启动 Docker 容器执行任务（脚手架负责构建命令）
4. Proxy 自动将轨迹写入对应的 `{instance_id}.jsonl`

### 脚手架（Scaffolds）

脚手架是对不同 AI 开发工具的抽象封装，负责：
- 配置 Docker 环境变量
- 生成初始化脚本
- 构建任务执行命令

**已支持的脚手架：**

| 脚手架名称 | 工具 | 状态 |
|-----------|------|------|
| `claudecode` | Claude Code (Anthropic) | ✅ 已实现 |
| `kilo-dev` | Kilo Code | ✅ 已实现 |
| `droid` | Droid (Factory AI) | ✅ 已实现 |

**添加新脚手架：**

1. 在 `scaffolds/` 目录下创建新文件
2. 继承 `BaseScaffold` 并实现所有抽象方法
3. 在 `scaffolds/__init__.py` 的 `_REGISTRY` 中注册

### 轨迹处理（去重合并）

Proxy 收集的原始轨迹是每个 API 调用一条记录。在评估之前，需要使用 `convert/` 模块将同一 session 的多条记录去重、合并为一条完整的对话轨迹。

```bash
python convert/convert_cc_traj_to_msg.py \
    --input_path ./results/trajectories \  # 原始轨迹目录
    --output_path ./results/merged.jsonl \ # 合并后的轨迹文件
```


### 评估轨迹

`evaluate.py` 使用 LLM 对合并后的轨迹进行评估。

```bash
python evaluate.py \
    --trajectories ./results/merged.jsonl \  # 合并后的轨迹文件
    --dataset MiniMaxAI/OctoCodingBench \    # HuggingFace 数据
    --output ./results/scores.json \         # 评估结果输出
    --model gpt-4o \                         # 评估用模型
    --api-key $OPENAI_API_KEY                # API Key
```

**评估维度：**

- **SP (System Prompt)**: 是否遵循系统提示的约束
- **System Reminder**: 是否正确响应系统提醒
- **User Query**: 是否满足用户需求
- **Agents.md**: 是否遵循项目特定约束
- **Skill.md**: 是否正确使用和遵守技能定义的规范与约束
- **Memory**: 是否正确利用上下文记忆，保持对话一致性
- **Tool Schema**: 工具调用是否符合规范

## 📊 数据格式

### 测试用例格式

测试用例从 [HuggingFace MiniMaxAI/OctoCodingBench](https://huggingface.co/datasets/MiniMaxAI/OctoCodingBench) 加载，每条记录为 JSON 格式：

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