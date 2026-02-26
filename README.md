# mini-vela

[![arXiv](https://img.shields.io/badge/arXiv-2601.10343-b31b1b.svg)](https://arxiv.org/abs/2601.10343)
[![Dataset](https://img.shields.io/badge/🤗%20Hugging%20Face-Dataset-yellow)](https://huggingface.co/datasets/MiniMaxAI/OctoBench)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[English](README.md) | [中文](README_CN.md)

## 📰 News

- **[2026-01-16]** 📄 Paper released on arXiv: [OctoBench: Benchmarking Scaffold-Aware Instruction Following in Repository-Grounded Agentic Coding](https://arxiv.org/abs/2601.10343)
- **[2026-01]** 🎉 Dataset & Framework released

---

A benchmark framework for evaluating instruction-following capabilities of AI Coding Agents. It intercepts API calls via LiteLLM Proxy, collects complete interaction trajectories, and performs automated scoring using LLM.

## 🌟 Features

- **Multi-Scaffold Support**: Supports Claude Code, Kilo-Dev, Droid and other AI development tools
- **Trajectory Collection**: Automatically intercepts and records complete API call trajectories
- **Automated Evaluation**: Multi-dimensional scoring of trajectories using LLM based on Checklist
- **Docker Isolation**: Each task instance runs in an isolated container with a clean environment

## 🏗️ Core Pipeline

1. **Proxy Startup**: LiteLLM Proxy runs on the host machine, intercepting all API calls
2. **Task Execution**: Scaffolds (Claude Code, Kilo, Droid) complete tasks in Docker containers
3. **Trajectory Collection**: Each API request/response is recorded to individual JSONL files (raw trajectories)
4. **Trajectory Processing**: Use `convert/` tools to deduplicate and merge raw trajectories into complete conversation trajectories
5. **Automated Evaluation**: Score merged trajectories using LLM based on Checklist

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker
- LLM API Key (Anthropic / MiniMax / Gemini, etc.)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure API Keys

```bash
cd proxy
cp env.sh.example env.sh
# Edit env.sh and fill in your API Keys
source env.sh
```

### Run Evaluation

```bash
# 1. Start Proxy (Terminal 1)
cd proxy
source env.sh
python start_proxy.py

# 2. Run evaluation pipeline (Terminal 2)
./run.sh

# Specify model
./run.sh --model claude-opus-4-5-20251101
```

## 📁 Project Structure

```
benchmark/
├── run.sh                   # One-click run script (task execution + trajectory processing + evaluation)
├── benchmark_runner.py      # Benchmark runner main program
├── evaluate.py              # Trajectory evaluation script
├── requirements.txt         # Python dependencies
│
├── scaffolds/               # Scaffold modules (multi-tool support)
│   ├── __init__.py          # Scaffold registry and factory functions
│   ├── base.py              # Abstract base class definition
│   ├── claudecode.py        # Claude Code scaffold implementation
│   ├── kilo_dev.py          # Kilo-Dev scaffold implementation
│   └── droid.py             # Droid scaffold implementation
│
├── proxy/                   # LiteLLM Proxy component (trajectory collection)
│   ├── start_proxy.py       # Proxy startup script
│   ├── trajectory_logger.py # Trajectory logger (custom Callback)
│   ├── litellm_config.yaml  # LiteLLM model configuration
│   ├── env.sh.example       # Environment variable template
│   └── Dockerfile           # Proxy containerization config
│
└── convert/                 # Trajectory processing tools (dedup & merge)
    ├── convert_cc_traj_to_msg.py  # Main program: Ray parallel trajectory processing
    ├── dedup.py             # Deduplication logic
    └── utils.py             # Completion data structures + format conversion
```

## 📊 Data Formats

### Task Instance Format

Task instances are loaded from [MiniMaxAI/OctoBench](https://huggingface.co/datasets/MiniMaxAI/OctoBench), each record in JSON format:

```json
{
  "instance_id": "benchmark-example-001",
  "user_query": ["Please help me analyze how this function works"],
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
      "description": "System Prompt constraints",
      "checks": [
        {
          "check_id": "SP_language_match",
          "description": "Check if correct language is used",
          "check_type": "compliance"
        }
      ]
    }
  }
}
```

**Key Fields:**

- `scaffold.name`: Scaffold name (claudecode / kilo-dev / droid)
- `user_query`: List of user queries, supports multi-turn conversations
- `checklist`: Evaluation check items, organized by category

### Raw Trajectory Format (trajectories/*.jsonl)

Raw trajectories collected by Proxy, one record per API call:

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

### Merged Trajectory Format (merged_trajectories.jsonl)

Complete conversation trajectories after `convert/` processing:

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
        "description": "Read file content",
        "parameters": { "type": "object", "properties": {...} }
      }
    }
  ],
  "messages": [
    { "role": "system", "content": "You are a helpful assistant..." },
    { "role": "user", "content": "Please help me analyze this function" },
    { 
      "role": "assistant", 
      "content": "OK, let me read the file first...",
      "reasoning_content": "User needs to analyze function, I should first...",
      "tool_calls": [{ "name": "Read", "arguments": {...} }],
      "generation": true
    },
    { "role": "tool", "tool_name": "Read", "content": "File content..." },
    { 
      "role": "assistant", 
      "content": "This function does...",
      "reasoning_content": "Based on the code content...",
      "generation": true
    }
  ]
}
```

**Key Fields:**

- `reasoning_content`: Model's thinking process (thinking block)
- `tool_calls`: List of tool calls

### Evaluation Result Format (scores.json)

```json
{
  "results": [
    {
      "instance_id": "benchmark-example-001",
      "success": true,
      "reward": 0.85,
      "eval_result": {
        "SP": {
          "reasoning": "Overall analysis...",
          "checklist": [
            {
              "check_id": "SP_language_match",
              "reasoning": "Specific analysis...",
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

## ⚙️ Configuration

### LiteLLM Proxy Configuration (proxy/litellm_config.yaml)

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

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TRAJECTORY_OUTPUT_DIR` | Trajectory output directory | `./trajectories` |
| `LITELLM_PORT` | Proxy listening port | `4000` |
| `ANTHROPIC_API_KEY` | Anthropic API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key (for evaluation) | - |
| `OPENAI_BASE_URL` | OpenAI API Base URL | - |

#### Scaffold-Specific Environment Variables

> **Important**: The following variables must be configured correctly for the corresponding scaffolds to work. Missing or incorrect values will cause task execution failures.

| Variable | Scaffold | Description | Required |
|----------|----------|-------------|----------|
| `IS_SANDBOX` | **Claude Code** | Set to `1` to allow Claude Code to run as root with `--dangerously-skip-permissions`. Without this, Claude Code will refuse to execute in root Docker containers. | **Yes** |
| `FACTORY_API_KEY` | **Droid** | Factory API Key for Droid authentication. Obtain from [Factory](https://app.factory.ai/). Without a valid key, all Droid tasks will fail with "Authentication failed". | **Yes** |

## 🔧 Advanced Usage

### Docker Deployment for Proxy

```bash
cd proxy
docker build -t benchmark-proxy .
docker run -d \
    -p 4000:4000 \
    -v /path/to/trajectories:/app/trajectories \
    -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
    benchmark-proxy
```

### Extending Trajectory Logging

Inherit the `TrajectoryLogger` class and override the `_build_record` method to add custom fields.

## 📝 License

MIT License
