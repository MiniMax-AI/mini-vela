#!/usr/bin/env python3
"""
Benchmark Runner - 在 Docker 中运行测试用例并收集轨迹

架构说明:
- LiteLLM Proxy 在宿主机运行（需要先手动启动）
- 任务容器通过 host.docker.internal 访问宿主机的 Proxy
- 通过共享文件 /tmp/current_instance_id.txt 传递当前 case 的 instance_id
- 串行执行，每个 case 对应一个轨迹文件
- 支持多种脚手架：claudecode, kilo-dev, droid 等
- 支持指定模型，每次用一个模型完整运行所有 case

用法:
    # 1. 先启动 Proxy（在另一个终端）
    cd benchmark/proxy && python start_proxy.py

    # 2. 运行 benchmark（默认从 HuggingFace 加载 MiniMaxAI/OctoCodingBench）
    python benchmark_runner.py
    
    # 3. 使用本地文件调试
    python benchmark_runner.py --dataset test/data_debug.jsonl
    
    # 4. 指定模型运行
    python benchmark_runner.py --model MiniMax-M2.1
    
    # 5. 运行单个 case
    python benchmark_runner.py --case benchmark-md-emoji-test-001
    
    # 6. 查看支持的模型列表
    python benchmark_runner.py --list-models
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

from scaffolds import get_scaffold, SUPPORTED_MODELS, DEFAULT_MODEL


# 固定路径配置
SCRIPT_DIR = Path(__file__).parent.absolute()
OUTPUT_DIR = SCRIPT_DIR / "results"
TRAJECTORIES_DIR = OUTPUT_DIR / "trajectories"
INSTANCE_ID_FILE = "/tmp/current_instance_id.txt"
PROXY_PORT = 4000
PROXY_URL = f"http://host.docker.internal:{PROXY_PORT}"


def run_command(cmd, check=True, capture_output=False):
    """运行命令并返回结果"""
    print(f"[CMD] {' '.join(cmd)}")
    result = subprocess.run(cmd, check=check, capture_output=capture_output, text=True)
    return result


def set_current_instance_id(instance_id):
    """写入当前 instance_id 到共享文件"""
    with open(INSTANCE_ID_FILE, "w") as f:
        f.write(instance_id)
    print(f"[RUNNER] 设置当前 instance_id: {instance_id}")


def cleanup_container(container_name):
    """清理容器（如果存在）"""
    run_command(["docker", "rm", "-f", container_name], check=False, capture_output=True)


def run_task(case, timeout=3600, model=None):
    """
    运行任务容器
    
    根据 case 中的 scaffold 配置选择对应的脚手架实现，
    由脚手架负责构建环境变量、初始化脚本和任务命令。
    
    Args:
        case: 测试用例数据
        timeout: 超时时间（秒）
        model: 指定使用的模型名称，如 "MiniMax-M2.1"
    """
    instance_id = case["instance_id"]
    image = case["image"]
    workspace = case.get("workspace_abs_path", "/app")
    user_queries = case["user_query"]
    system_prompt = case.get("system_prompt", "")
    
    # 获取脚手架配置（默认使用 claudecode）
    scaffold_config = case.get("scaffold", {"name": "claudecode"})
    scaffold_name = scaffold_config.get("name", "claudecode")
    
    # 获取脚手架实例
    try:
        scaffold = get_scaffold(scaffold_name)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return False
    
    container_name = f"task-{instance_id}"
    cleanup_container(container_name)
    
    # 由脚手架构建初始化脚本和任务命令（传递 model 参数）
    setup_script = scaffold.get_setup_script(PROXY_URL, model=model)
    task_commands = scaffold.build_commands(user_queries, system_prompt, model=model)
    
    # 组合完整命令
    all_commands = [setup_script] + task_commands
    full_command = " && ".join(all_commands)
    
    # 构建 Docker 命令
    cmd = [
        "docker", "run",
        "--name", container_name,
        "--add-host=host.docker.internal:host-gateway",
    ]
    
    # 全部以 root 用户运行
    # cmd.extend(["--user", "1000:1000"])
    
    # 添加脚手架指定的环境变量
    env_vars = scaffold.get_docker_env(PROXY_URL, model=model)
    for key, value in env_vars.items():
        cmd.extend(["-e", f"{key}={value}"])
    
    cmd.extend([
        "-w", workspace,
        image,
        "bash", "-c", full_command
    ])
    
    # 打印任务信息
    print(f"[TASK] 启动任务容器: {instance_id}")
    print(f"[TASK] 脚手架: {scaffold_name}")
    print(f"[TASK] 模型: {model or DEFAULT_MODEL}")
    print(f"[TASK] 镜像: {image}")
    print(f"[TASK] 工作目录: {workspace}")
    print(f"[TASK] 环境变量: {env_vars}")
    print(f"[TASK] 命令数量: {len(task_commands)}")
    print(f"[TASK] 完整命令 (前200字符): {full_command[:200]}...")
    
    try:
        result = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
        print(f"[TASK] 任务完成，退出码: {result.returncode}")
        if result.stdout:
            print(f"[TASK] stdout (last 500 chars): {result.stdout[-500:]}")
        if result.stderr:
            print(f"[TASK] stderr (last 500 chars): {result.stderr[-500:]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[TASK] 任务超时 ({timeout}s)")
        run_command(["docker", "stop", container_name], check=False)
        return False
    finally:
        cleanup_container(container_name)


def run_single_case(case, trajectories_dir, timeout=3600, model=None):
    """运行单个测试用例"""
    instance_id = case["instance_id"]
    print(f"\n{'='*60}")
    print(f"[CASE] 开始运行: {instance_id}")
    print(f"{'='*60}")
    
    set_current_instance_id(instance_id)
    
    success = run_task(case, timeout, model=model)
    
    trajectory_file = os.path.join(trajectories_dir, f"{instance_id}.jsonl")
    if os.path.exists(trajectory_file):
        print(f"[CASE] ✓ 轨迹已保存: {trajectory_file}")
    else:
        print(f"[CASE] ✗ 轨迹文件不存在: {trajectory_file}")
    
    return success


def check_proxy_running():
    """检查 Proxy 是否在运行"""
    try:
        result = subprocess.run(
            ["curl", "-s", f"http://localhost:{PROXY_PORT}/health"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def load_cases(dataset_path, split="train"):
    """
    智能加载数据集：自动判断本地文件或 HuggingFace 数据集
    
    Args:
        dataset_path: 本地 JSONL 文件路径 或 HuggingFace 数据集名称
        split: HuggingFace 数据集分片，默认 "train"
    
    Returns:
        测试用例列表
    """
    # 判断是否为本地文件（文件存在 或 以 .jsonl 结尾）
    is_local = os.path.exists(dataset_path) or dataset_path.endswith('.jsonl')
    
    if is_local:
        if not os.path.exists(dataset_path):
            print(f"[ERROR] 本地文件不存在: {dataset_path}")
            return None
        print(f"[RUNNER] 从本地文件加载: {dataset_path}")
        with open(dataset_path) as f:
            cases = [json.loads(line) for line in f if line.strip()]
        print(f"[RUNNER] 加载完成，共 {len(cases)} 个测试用例")
        return cases
    else:
        try:
            from datasets import load_dataset
        except ImportError:
            print("[ERROR] 请先安装 datasets: pip install datasets")
            return None
        
        print(f"[RUNNER] 从 HuggingFace 加载数据集: {dataset_path}")
        dataset = load_dataset(dataset_path, split=split)
        
        # 转换为字典列表
        cases = [dict(item) for item in dataset]
        print(f"[RUNNER] 加载完成，共 {len(cases)} 个测试用例")
        
        return cases


def main():
    # 默认数据集
    DEFAULT_DATASET = "MiniMaxAI/OctoCodingBench"
    
    parser = argparse.ArgumentParser(description="Benchmark Runner - 多脚手架、多模型支持")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, 
                        help=f"数据集：本地 JSONL 文件路径 或 HuggingFace 数据集名称 (默认: {DEFAULT_DATASET})")
    parser.add_argument("--timeout", type=int, default=3600, help="单个任务超时时间(秒)")
    parser.add_argument("--case", help="只运行指定 instance_id 的用例")
    parser.add_argument("--model", help=f"指定使用的模型 (默认: {DEFAULT_MODEL})")
    parser.add_argument("--list-models", action="store_true", help="列出所有支持的模型")
    parser.add_argument("--skip-proxy-check", action="store_true", help="跳过 Proxy 检查")
    args = parser.parse_args()
    
    # 列出支持的模型
    if args.list_models:
        print("支持的模型列表:")
        for i, model in enumerate(SUPPORTED_MODELS):
            default_mark = " (默认)" if model == DEFAULT_MODEL else ""
            print(f"  {i+1}. {model}{default_mark}")
        return
    
    # 验证模型名称
    model = args.model
    if model and model not in SUPPORTED_MODELS:
        print(f"[ERROR] 不支持的模型: {model}")
        print(f"[ERROR] 支持的模型: {', '.join(SUPPORTED_MODELS)}")
        return
    
    if not args.skip_proxy_check and not check_proxy_running():
        print(f"[ERROR] LiteLLM Proxy 未运行！")
        print(f"[ERROR] 请先在另一个终端运行: cd benchmark/proxy && python start_proxy.py")
        return
    
    # 使用固定的输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRAJECTORIES_DIR.mkdir(parents=True, exist_ok=True)
    
    # 加载测试用例（自动判断本地文件或 HuggingFace）
    cases = load_cases(args.dataset)
    if cases is None:
        return
    print(f"[RUNNER] 使用模型: {model or DEFAULT_MODEL}")
    print(f"[RUNNER] 输出目录: {OUTPUT_DIR}")
    print(f"[RUNNER] 轨迹目录: {TRAJECTORIES_DIR}")
    print(f"[RUNNER] Proxy 地址: http://localhost:{PROXY_PORT}")
    
    # 统计各脚手架的用例数
    scaffold_counts = {}
    for case in cases:
        scaffold_name = case.get("scaffold", {}).get("name", "claudecode")
        scaffold_counts[scaffold_name] = scaffold_counts.get(scaffold_name, 0) + 1
    print(f"[RUNNER] 脚手架分布: {scaffold_counts}")
    
    if args.case:
        cases = [c for c in cases if c["instance_id"] == args.case]
        if not cases:
            print(f"[ERROR] 未找到 instance_id={args.case} 的用例")
            return
    
    results = []
    for i, case in enumerate(cases):
        print(f"\n[PROGRESS] {i+1}/{len(cases)}")
        success = run_single_case(case, str(TRAJECTORIES_DIR), args.timeout, model=model)
        results.append({
            "instance_id": case["instance_id"],
            "scaffold": case.get("scaffold", {}).get("name", "claudecode"),
            "model": model or DEFAULT_MODEL,
            "success": success
        })
    
    # 保存结果
    results_file = OUTPUT_DIR / "run_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    # 打印统计
    success_count = sum(1 for r in results if r["success"])
    print(f"\n{'='*60}")
    print(f"[DONE] 运行完成")
    print(f"[DONE] 模型: {model or DEFAULT_MODEL}")
    print(f"[DONE] 成功: {success_count}/{len(results)}")
    print(f"[DONE] 结果: {results_file}")
    print(f"[DONE] 轨迹目录: {TRAJECTORIES_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
