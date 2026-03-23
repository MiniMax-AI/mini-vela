"""
Claude Code 脚手架实现

"""

import json
from typing import Dict, List, Optional

from .base import BaseScaffold, DEFAULT_MODEL


class ClaudeCodeScaffold(BaseScaffold):
    """
    Claude Code 脚手架
    """
    
    name = "claudecode"

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
    
    def get_docker_env(self, proxy_url: str, model: Optional[str] = None) -> Dict[str, str]:
        """
        返回 Claude Code 需要的 Docker 环境变量
        
        """
        return {
            "ANTHROPIC_BASE_URL": proxy_url,
            "ANTHROPIC_API_KEY": "fake-key",
            "IS_SANDBOX": "1",
        }
    
    def get_setup_script(self, proxy_url: str, model: Optional[str] = None) -> str:
        """
        返回 Claude Code 的初始化脚本
        
        """
        settings = {
            "env": {
                "ANTHROPIC_BASE_URL": proxy_url
            },
            "permissions": {
                "allow": self.ALLOWED_PERMISSIONS
            }
        }
        
        settings_json = json.dumps(settings, ensure_ascii=False)
        
        return f"mkdir -p ~/.claude && echo '{settings_json}' > ~/.claude/settings.json"
    
    def build_commands(
        self, 
        queries: List[str], 
        system_prompt: Optional[str] = None,
        model: Optional[str] = None
    ) -> List[str]:
        """
        构建 Claude Code CLI 命令序列
        
        Args:
            queries: 用户查询列表
            system_prompt: 可选的系统提示词（仅用于首次查询）
            model: 可选的模型名称，如 "claude-sonnet-4-5-20250929"
        
        Returns:
            命令字符串列表
        """
        commands = []
        
        # 使用指定模型或默认模型
        model_name = model or DEFAULT_MODEL
        
        for i, query in enumerate(queries):
            # 转义查询中的特殊字符
            escaped_query = self._escape_for_shell(query)
            
            if i == 0:
                # 首次查询：包含 --model 参数
                base_cmd = f'claude --model {model_name} --dangerously-skip-permissions'
                if system_prompt:
                    escaped_sp = self._escape_for_shell(system_prompt)
                    cmd = f'{base_cmd} -p "{escaped_query}" --system-prompt "{escaped_sp}"'
                else:
                    cmd = f'{base_cmd} -p "{escaped_query}"'
            else:
                # 继续对话：使用 -c 参数（不需要再指定模型）
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

