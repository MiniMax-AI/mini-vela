"""
LiteLLM 自定义 Callback - 轨迹日志记录器

将 API 请求和响应记录到 JSONL 文件，用于后续分析和评估。
输出格式与 convert 工具兼容（Claude API 原生格式）。

架构说明:
- Proxy 在宿主机运行，一直保持运行
- 通过共享文件 /tmp/current_instance_id.txt 获取当前 case 的 instance_id
- 每个 case 的轨迹写入独立的 {instance_id}.jsonl 文件

输出格式 (每行一个 JSON):
{
    "session_id": "instance_id",
    "biz_id": "",
    "request_time": 1234567890000,  // 毫秒时间戳
    "request_body": {
        "messages": [...],  // Claude API 格式
        "system": [...],    // 数组格式
        "tools": [...],     // Claude 工具格式
        "model": "...",
        "max_tokens": ...,
        "metadata": {}
    },
    "response_body": {
        "content": [...]  // Claude 格式的 content 数组
    }
}
"""

import json
import os
import time
from datetime import datetime
from litellm.integrations.custom_logger import CustomLogger


INSTANCE_ID_FILE = "/tmp/current_instance_id.txt"


class TrajectoryLogger(CustomLogger):
    def __init__(self):
        # 固定输出目录：相对于 proxy 目录的上级 results/trajectories
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)  # benchmark 目录
        self.output_dir = os.path.join(project_root, "results", "trajectories")
        
        os.makedirs(self.output_dir, exist_ok=True)
        self.excluded_models = ["haiku"]  # 排除 haiku 模型的轨迹记录
        self._pre_call_system = None
        print(f"[TrajectoryLogger] 初始化完成，日志目录: {self.output_dir}")
        print(f"[TrajectoryLogger] instance_id 文件: {INSTANCE_ID_FILE}")

    def log_pre_api_call(self, model, messages, kwargs):
        """在 LiteLLM 翻译请求格式之前捕获 system prompt"""
        try:
            optional_params = kwargs.get("optional_params", {})
            system = optional_params.get("system") or kwargs.get("system")
            self._pre_call_system = system if system else None
        except Exception:
            self._pre_call_system = None

    def _get_current_instance_id(self):
        """从共享文件读取当前 instance_id"""
        try:
            with open(INSTANCE_ID_FILE, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "unknown"
        except Exception as e:
            print(f"[TrajectoryLogger] 读取 instance_id 失败: {e}")
            return "unknown"

    def _should_log(self, model):
        """判断是否应该记录该模型的调用"""
        if not model:
            return True
        model_lower = model.lower()
        return not any(excluded in model_lower for excluded in self.excluded_models)

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """记录成功的 API 调用"""
        try:
            model = kwargs.get("model", "")
            if not self._should_log(model):
                return
            record = self._build_record(kwargs, response_obj, start_time, end_time)
            self._write_record(record)
        except Exception as e:
            print(f"[TrajectoryLogger] 记录失败: {e}")
            import traceback
            traceback.print_exc()

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """记录失败的 API 调用（跳过，只记录成功的）"""
        pass

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """异步记录成功的 API 调用"""
        self.log_success_event(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """异步记录失败的 API 调用"""
        pass

    def _normalize_system(self, system):
        """将 system 转换为 Claude API 期望的数组格式"""
        if system is None:
            return []
        if isinstance(system, str):
            return [{"type": "text", "text": system}]
        if isinstance(system, list):
            return system
        return []

    def _convert_tools_to_claude_format(self, tools):
        """将 OpenAI 格式的 tools 转换为 Claude 格式"""
        if not tools:
            return []
        
        claude_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                # OpenAI 格式
                func = tool.get("function", {})
                claude_tool = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {})
                }
            else:
                # 可能已经是 Claude 格式
                claude_tool = {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {})
                }
            claude_tools.append(claude_tool)
        
        return claude_tools

    def _build_response_content(self, response_obj):
        """
        从 LiteLLM 响应对象构建 Claude 格式的 content 数组
        
        Claude 格式:
        [
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": "..."},
            {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
        ]
        """
        content = []
        
        if not response_obj or not hasattr(response_obj, 'choices') or not response_obj.choices:
            return content
        
        choice = response_obj.choices[0]
        if not hasattr(choice, 'message'):
            return content
        
        msg = choice.message
        
        # 1. 添加 thinking blocks（如果有）
        thinking_blocks = getattr(msg, 'thinking_blocks', None)
        if thinking_blocks:
            for block in thinking_blocks:
                if isinstance(block, dict):
                    thinking_text = block.get("thinking", "")
                else:
                    thinking_text = getattr(block, 'thinking', str(block))
                content.append({
                    "type": "thinking",
                    "thinking": thinking_text
                })
        
        # 2. 添加 text content（如果有）
        text_content = getattr(msg, 'content', None)
        if text_content:
            content.append({
                "type": "text",
                "text": text_content
            })
        
        # 3. 添加 tool_use（从 OpenAI 的 tool_calls 转换）
        tool_calls = getattr(msg, 'tool_calls', None)
        if tool_calls:
            for tc in tool_calls:
                tool_id = tc.id if hasattr(tc, 'id') else None
                
                if hasattr(tc, 'function'):
                    tool_name = tc.function.name if hasattr(tc.function, 'name') else ""
                    tool_args = tc.function.arguments if hasattr(tc.function, 'arguments') else "{}"
                else:
                    tool_name = ""
                    tool_args = "{}"
                
                # 解析 arguments（可能是字符串或字典）
                if isinstance(tool_args, str):
                    try:
                        tool_input = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_input = {"raw": tool_args}
                else:
                    tool_input = tool_args
                
                content.append({
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input
                })
        
        return content

    def _convert_messages_to_claude_format(self, messages):
        """
        将 OpenAI 格式的 messages 统一转换为 Claude API 格式。
        如果已经是 Claude 格式则保持不变。
        
        OpenAI 格式特征: content 为字符串, tool_calls 在消息顶层, role="tool" 独立消息
        Claude 格式特征: content 为列表, tool_use 在 content 内, tool_result 在 user 消息内
        
        Returns:
            (normalized_messages, extracted_system_text)
        """
        if not messages:
            return [], None

        normalized = []
        extracted_system = None

        i = 0
        while i < len(messages):
            msg = messages[i]
            if not isinstance(msg, dict):
                i += 1
                continue

            role = msg.get("role", "")
            content = msg.get("content")

            if role == "system":
                if isinstance(content, str):
                    extracted_system = content
                elif isinstance(content, list):
                    texts = [
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    ]
                    extracted_system = "\n".join(texts)
                i += 1
                continue

            if role == "user":
                if isinstance(content, str):
                    new_content = [{"type": "text", "text": content}]
                elif isinstance(content, list):
                    new_content = content
                else:
                    new_content = [{"type": "text", "text": str(content) if content else ""}]
                normalized.append({"role": "user", "content": new_content})
                i += 1

            elif role == "assistant":
                new_content = []
                if isinstance(content, str):
                    if content:
                        new_content.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    new_content.extend(content)

                for tc in msg.get("tool_calls", []):
                    if isinstance(tc, dict):
                        func = tc.get("function", {})
                        tool_id = tc.get("id", "")
                        tool_name = func.get("name", "")
                        tool_args = func.get("arguments", "{}")
                    else:
                        tool_id = getattr(tc, "id", "")
                        func = getattr(tc, "function", None)
                        tool_name = getattr(func, "name", "") if func else ""
                        tool_args = getattr(func, "arguments", "{}") if func else "{}"

                    if isinstance(tool_args, str):
                        try:
                            tool_input = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_input = {"raw": tool_args}
                    else:
                        tool_input = tool_args

                    new_content.append({
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input
                    })

                normalized.append({"role": "assistant", "content": new_content})
                i += 1

            elif role == "tool":
                tool_results = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tool_msg = messages[i]
                    tc = tool_msg.get("content", "")
                    if not isinstance(tc, str):
                        tc = json.dumps(tc, ensure_ascii=False)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_msg.get("tool_call_id", ""),
                        "content": tc
                    })
                    i += 1
                normalized.append({"role": "user", "content": tool_results})

            else:
                normalized.append(msg)
                i += 1

        return normalized, extracted_system

    def _build_record(self, kwargs, response_obj, start_time, end_time):
        """
        构建日志记录（Claude API 原生格式，与 convert 工具兼容）
        """
        instance_id = self._get_current_instance_id()
        
        # 获取请求参数
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools", [])
        
        optional_params = kwargs.get("optional_params", {})
        system = optional_params.get("system") or kwargs.get("system")

        if not system:
            additional_args = kwargs.get("additional_args", {})
            complete_input = additional_args.get("complete_input_dict", {})
            if isinstance(complete_input, dict):
                system = complete_input.get("system")

        if not system and self._pre_call_system:
            system = self._pre_call_system

        max_tokens = optional_params.get("max_tokens") or kwargs.get("max_tokens", 8192)
        
        # 统一转换为 Claude API 格式（兼容 OpenAI 格式输入）
        normalized_messages, extracted_system = self._convert_messages_to_claude_format(messages)
        if extracted_system and not system:
            system = extracted_system

        # 构建 request_body
        request_body = {
            "messages": normalized_messages,
            "system": self._normalize_system(system),
            "tools": self._convert_tools_to_claude_format(tools),
            "model": kwargs.get("model", ""),
            "max_tokens": max_tokens,
            "metadata": {}
        }
        
        # 构建 response_body
        response_content = self._build_response_content(response_obj)
        response_body = {
            "content": response_content
        }
        
        # 构建最终记录（与 convert 工具的 Completion.from_dict 兼容）
        request_time = int(time.time() * 1000)  # 毫秒时间戳
        
        record = {
            "session_id": instance_id,
            "biz_id": "",
            "request_time": request_time,
            "request_body": request_body,
            "response_body": response_body
        }
        
        return record

    def _write_record(self, record):
        """写入记录到对应 instance 的 JSONL 文件"""
        session_id = record.get("session_id", "unknown")
        output_file = os.path.join(self.output_dir, f"{session_id}.jsonl")
        
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        
        # 简化日志输出
        model = record.get("request_body", {}).get("model", "unknown")
        content_types = [c.get("type") for c in record.get("response_body", {}).get("content", [])]
        print(f"[TrajectoryLogger] 已记录轨迹 -> {session_id}.jsonl (model={model}, content_types={content_types})")


trajectory_logger_instance = TrajectoryLogger()
