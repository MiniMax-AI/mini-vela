"""
Claude Code 脚手架实现

Claude Code (claude.ai/code) 是 Anthropic 官方的 CLI 工具。
此模块实现了 Claude Code 特定的配置和命令构建逻辑。
"""

import json
from typing import Dict, List, Optional

from .base import BaseScaffold


class ClaudeCodeScaffold(BaseScaffold):
    """
    Claude Code 脚手架
    
    特点：
    - 配置文件位置：~/.claude/settings.json
    - 环境变量：ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY
    - 命令格式：claude -p "query" [--system-prompt "..."]
    - 继续对话：claude -c -p "query"
    """
    
    name = "claudecode"
    
    # Claude Code 权限配置：允许的工具列表
    # 这些权限让 Claude Code 可以自动执行操作，无需用户确认
    ALLOWED_PERMISSIONS = [
        "Bash(*)",
        "Write(*)",
        "Edit(*)",
        "Read(*)",
        "WebFetch(*)",
        "TodoRead(*)",
        "TodoWrite(*)",
        "Task(*)",
        "Glob(*)",
        "Grep(*)",
        "LS(*)",
    ]
    
    def get_docker_env(self, proxy_url: str) -> Dict[str, str]:
        """
        返回 Claude Code 需要的 Docker 环境变量
        
        Claude Code 使用以下环境变量：
        - ANTHROPIC_BASE_URL: API 端点（指向 LiteLLM Proxy）
        - ANTHROPIC_API_KEY: API 密钥（使用 fake-key，因为 Proxy 会转发）
        """
        return {
            "ANTHROPIC_BASE_URL": proxy_url,
            "ANTHROPIC_API_KEY": "fake-key",
        }
    
    def get_setup_script(self, proxy_url: str) -> str:
        """
        返回 Claude Code 的初始化脚本
        
        创建 ~/.claude/settings.json，配置：
        1. API 端点指向 LiteLLM Proxy
        2. 权限设置：允许所有工具操作，跳过用户确认
        """
        settings = {
            "env": {
                "ANTHROPIC_BASE_URL": proxy_url
            },
            "permissions": {
                "allow": self.ALLOWED_PERMISSIONS
            }
        }
        
        # 转义 JSON 中的单引号，确保 shell 命令正确
        settings_json = json.dumps(settings, ensure_ascii=False)
        
        return f"mkdir -p ~/.claude && echo '{settings_json}' > ~/.claude/settings.json"
    
    def build_commands(
        self, 
        queries: List[str], 
        system_prompt: Optional[str] = None
    ) -> List[str]:
        """
        构建 Claude Code CLI 命令序列
        
        命令格式：
        - 首次查询：claude --dangerously-skip-permissions -p "query" [--system-prompt "..."]
        - 继续对话：claude --dangerously-skip-permissions -c -p "query"
        
        注意：使用 --dangerously-skip-permissions 跳过所有权限确认，
        确保任务可以自动完成而无需用户交互。
        
        Args:
            queries: 用户查询列表
            system_prompt: 可选的系统提示词（仅用于首次查询）
        
        Returns:
            命令字符串列表
        """
        commands = []
        
        for i, query in enumerate(queries):
            # 转义查询中的特殊字符
            escaped_query = self._escape_for_shell(query)
            
            if i == 0:
                # 首次查询
                if system_prompt:
                    escaped_sp = self._escape_for_shell(system_prompt)
                    cmd = f'claude --dangerously-skip-permissions -p "{escaped_query}" --system-prompt "{escaped_sp}"'
                else:
                    cmd = f'claude --dangerously-skip-permissions -p "{escaped_query}"'
            else:
                # 继续对话：使用 -c 参数
                cmd = f'claude --dangerously-skip-permissions -c -p "{escaped_query}"'
            
            commands.append(cmd)
        
        return commands
    
    @staticmethod
    def _escape_for_shell(text: str) -> str:
        """
        转义文本中的特殊字符，使其可以安全地用在 shell 命令中
        """
        # 转义双引号和反斜杠
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        text = text.replace('$', '\\$')
        text = text.replace('`', '\\`')
        return text

