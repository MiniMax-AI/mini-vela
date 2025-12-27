#!/usr/bin/env python3
"""
启动 LiteLLM Proxy 并加载自定义轨迹日志 Callback

用法：
    cd ./benchmark/proxy
    python start_proxy.py
    
架构说明：
- Proxy 在宿主机运行，监听 4000 端口
- 通过 /tmp/current_instance_id.txt 获取当前 case 的 instance_id
- 轨迹保存到 ./trajectories/{instance_id}.jsonl
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
os.chdir(script_dir)

import litellm
from trajectory_logger import trajectory_logger_instance

litellm.callbacks.append(trajectory_logger_instance)

print("=" * 60)
print("[start_proxy] ✓ 已注册 TrajectoryLogger callback")
print(f"[start_proxy] ✓ 轨迹目录: {trajectory_logger_instance.output_dir}")
print("=" * 60)

if __name__ == "__main__":
    config_path = os.path.join(script_dir, "litellm_config.yaml")
    port = int(os.environ.get("LITELLM_PORT", "4000"))
    
    print(f"[start_proxy] ✓ 配置文件: {config_path}")
    print(f"[start_proxy] ✓ 监听端口: {port}")
    print("-" * 60)
    
    sys.argv = [
        "litellm",
        "--config", config_path,
        "--port", str(port),
    ]
    
    from litellm.proxy.proxy_cli import run_server
    run_server()

