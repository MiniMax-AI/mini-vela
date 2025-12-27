"""
脚手架模块

提供统一的接口来管理不同的脚手架（Claude Code, Kilo-Dev, Droid 等）。

使用方法：
    from scaffolds import get_scaffold
    
    scaffold = get_scaffold("claudecode")
    env_vars = scaffold.get_docker_env(proxy_url)
    setup_script = scaffold.get_setup_script(proxy_url)
    commands = scaffold.build_commands(queries, system_prompt)

添加新脚手架：
    1. 在 scaffolds/ 目录下创建新文件（如 my_scaffold.py）
    2. 继承 BaseScaffold 并实现所有抽象方法
    3. 在本文件的 _REGISTRY 中注册新脚手架
"""

from typing import Type

from .base import BaseScaffold
from .claudecode import ClaudeCodeScaffold
from .kilo_dev import KiloDevScaffold
from .droid import DroidScaffold


# 脚手架注册表：名称 -> 类
_REGISTRY: dict[str, Type[BaseScaffold]] = {
    "claudecode": ClaudeCodeScaffold,
    "kilo-dev": KiloDevScaffold,
    "droid": DroidScaffold,
}


def get_scaffold(name: str) -> BaseScaffold:
    """
    工厂函数：根据名称获取脚手架实例
    
    Args:
        name: 脚手架名称，如 "claudecode", "kilo-dev", "droid"
    
    Returns:
        对应的脚手架实例
    
    Raises:
        ValueError: 如果名称未注册
    
    示例：
        scaffold = get_scaffold("claudecode")
        print(scaffold.name)  # "claudecode"
    """
    scaffold_class = _REGISTRY.get(name)
    
    if scaffold_class is None:
        available = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"未知脚手架: '{name}'。可用的脚手架: {available}"
        )
    
    return scaffold_class()


def list_scaffolds() -> list[str]:
    """
    列出所有已注册的脚手架名称
    
    Returns:
        脚手架名称列表
    """
    return list(_REGISTRY.keys())


# 导出公共接口
__all__ = [
    "BaseScaffold",
    "ClaudeCodeScaffold",
    "KiloDevScaffold",
    "DroidScaffold",
    "get_scaffold",
    "list_scaffolds",
]

