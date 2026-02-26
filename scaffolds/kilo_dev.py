"""
Kilo Code 脚手架实现

"""

import json
from typing import Dict, List, Optional

from .base import BaseScaffold, DEFAULT_MODEL


class KiloDevScaffold(BaseScaffold):
    """
    Kilo Code 脚手架
    """
    
    name = "kilo-dev"
    
    AUTO_APPROVAL_CONFIG = {
        "enabled": True,
        "read": {"enabled": True, "outside": True},
        "write": {"enabled": True, "outside": True, "protected": True},
        "browser": {"enabled": True},
        "retry": {"enabled": True, "delay": 10},
        "mcp": {"enabled": True},
        "mode": {"enabled": True},
        "subtasks": {"enabled": True},
        "execute": {
            "enabled": True,
            "allowed": [],  # 空列表表示允许所有命令
            "denied": []
        },
        "question": {"enabled": True, "timeout": 60},
        "todo": {"enabled": True}
    }
    
    def get_docker_env(self, proxy_url: str, model: Optional[str] = None) -> Dict[str, str]:
        """
        返回 Kilo Code 需要的 Docker 环境变量
        """
        return {
            "HOME": "/tmp",  # 设置 HOME 目录，确保非 root 用户有写权限
            "CI": "true",  # 禁用交互式界面
            "TERM": "dumb",  # 禁用高级终端功能
            "NO_COLOR": "1",  # 禁用颜色输出
        }
    
    def get_setup_script(self, proxy_url: str, model: Optional[str] = None) -> str:
        """
        返回 Kilo Code 的初始化脚本
        
        Args:
            proxy_url: LiteLLM Proxy 的 URL
            model: 可选的模型名称，如 "claude-sonnet-4-5-20250929"
        """
        # 使用指定模型或默认模型
        model_name = model or DEFAULT_MODEL
        
        # 构建配置文件内容
        config = {
            "version": "1.0.0",
            "mode": "code",
            "telemetry": False,
            "provider": "default",
            "providers": [
                {
                    "id": "default",
                    "provider": "openai",
                    "openAiApiKey": "fake-api-key-for-proxy",  # Proxy 会使用自己的 key（至少10字符）
                    "openAiBaseUrl": f"{proxy_url}/v1",  # 需要 /v1 后缀
                    "openAiModelId": model_name  # 使用指定的模型
                }
            ],
            "autoApproval": self.AUTO_APPROVAL_CONFIG,
            "theme": "dark",
            "customThemes": {}
        }
        
        config_json = json.dumps(config, ensure_ascii=False)
      
        setup_script = f'''
mkdir -p $HOME/.npm-global && \
npm config set prefix $HOME/.npm-global && \
npm install -g @kilocode/cli@0.10.2 && \
export PATH="$HOME/.npm-global/bin:$PATH" && \
mkdir -p $HOME/.kilocode/cli && \
echo '{config_json}' > $HOME/.kilocode/cli/config.json
'''.strip()
        
        return setup_script
    
    def build_commands(
        self, 
        queries: List[str], 
        system_prompt: Optional[str] = None,
        model: Optional[str] = None
    ) -> List[str]:
        """
        构建 Kilo Code CLI 命令序列
        
        参数说明（v0.10.2）：
        - --auto: 自动模式，非交互式运行
        - --json: JSON 输出模式，禁用 TUI
        - 自动批准通过配置文件 autoApproval 实现
                
        Args:
            queries: 用户查询列表
            system_prompt: 可选的系统提示词
            model: 可选的模型名称，如 "claude-sonnet-4-5-20250929"
        
        Returns:
            命令字符串列表
        """
        commands = []
        
        for i, query in enumerate(queries):
            # 转义查询中的特殊字符
            escaped_query = self._escape_for_shell(query)
            
            # 构建基础命令（v0.10.2 参数格式）
            # --auto: 自动模式（非交互式）
            # --json: JSON 输出模式，完全禁用 TUI（适合 Docker 环境）
            # 自动批准通过配置文件 autoApproval 实现，无需 CLI 参数
            cmd = f'kilocode --auto --json "{escaped_query}"'
            
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
