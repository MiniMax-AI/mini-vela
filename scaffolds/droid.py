"""
Droid 脚手架实现

"""

import json
import os
from typing import Dict, List, Optional

from .base import BaseScaffold, SUPPORTED_MODELS, DEFAULT_MODEL


class DroidScaffold(BaseScaffold):
    """
    Droid 脚手架
    """
    
    name = "droid"
    
    def get_docker_env(self, proxy_url: str, model: Optional[str] = None) -> Dict[str, str]:
        """
        返回 Droid 需要的 Docker 环境变量
        
        """
        return {
            "FACTORY_API_KEY": os.environ.get("FACTORY_API_KEY", ""),
            "HOME": "/tmp", 
        }
    
    def get_setup_script(self, proxy_url: str, model: Optional[str] = None) -> str:
        """
        返回 Droid 的初始化脚本
        
        """
        # 构建所有模型的配置
        custom_models = []
        for i, model_name in enumerate(SUPPORTED_MODELS):
            model_config = {
                "model": model_name,
                "id": model_name,  # 直接使用模型名称作为 id
                "index": i,
                "baseUrl": proxy_url,
                "apiKey": "fake-key",
                "displayName": model_name,
                "noImageSupport": False,
                "provider": "anthropic",
            }
            custom_models.append(model_config)
        
        settings = {
            "customModels": custom_models
        }
        
        settings_json = json.dumps(settings, ensure_ascii=False)
        
        setup_script = f'''
curl -fsSL https://app.factory.ai/cli | sh && \
export PATH="$HOME/.local/bin:$PATH" && \
mkdir -p ~/.factory && \
echo '{settings_json}' > ~/.factory/settings.json
'''.strip()
        
        return setup_script
    
    def build_commands(
        self, 
        queries: List[str], 
        system_prompt: Optional[str] = None,
        model: Optional[str] = None
    ) -> List[str]:
        """
        构建 Droid CLI 命令序列
        
        Args:
            queries: 用户查询列表
            model: 可选的模型名称，如 "claude-sonnet-4-5-20250929"
        
        Returns:
            命令字符串列表
        """
        commands = []
        
        # 使用指定模型或默认模型
        model_name = model or DEFAULT_MODEL
        
        for query in queries:
            # 转义查询中的特殊字符
            escaped_query = self._escape_for_shell(query)
            
            # 构建 droid exec 命令
            cmd = f'droid exec --skip-permissions-unsafe -m "{model_name}" "{escaped_query}"'
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

