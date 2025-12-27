import json
import hashlib
from dataclasses import dataclass
from copy import deepcopy
from collections import defaultdict
from typing import List


@dataclass
class Completion:
    """原始 Completion 数据结构"""
    session_id: str
    messages: list[dict]
    system: list[dict]
    tools: list[dict]
    completion: list[dict]
    model: str
    request_time: int
    biz_id: str
    max_tokens: int
    metadata: dict
    
    @staticmethod
    def from_dict(dict_data: dict) -> "Completion":
        """从原始字典创建 Completion 对象"""
        if isinstance(dict_data["request_body"], str):
            request_body = json.loads(dict_data["request_body"])
        else:
            request_body = dict_data["request_body"]
            
        if isinstance(dict_data["response_body"], str):
            response_body = json.loads(dict_data["response_body"])
        else:
            response_body = dict_data["response_body"]
        
        if isinstance(request_body.get("system"), str):
            request_body["system"] = [{"type": "text", "text": request_body["system"]}]

        return Completion(
            session_id=dict_data.get("session_id", ""),
            messages=request_body.get("messages", []),
            system=request_body.get("system", []),
            tools=request_body.get("tools", []),
            completion=response_body.get("content", []),
            model=request_body.get("model", ""),
            request_time=dict_data.get("request_time", 0),
            biz_id=dict_data.get("biz_id", ""),
            max_tokens=request_body.get("max_tokens", 0),
            metadata=request_body.get("metadata", {}),
        )
    
    def to_dict(self) -> dict:
        """转换回原始字典格式"""
        request_body = {
            "messages": self.messages,
            "system": self.system,
            "tools": self.tools,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "metadata": self.metadata,
        }
        response_body = {
            "content": self.completion
        }
        return {
            "session_id": self.session_id,
            "biz_id": self.biz_id,
            "request_time": self.request_time,
            "request_body": request_body,
            "response_body": response_body,
        }

    def normalize(self) -> str:
        """标准化messages，用于去重比较"""
        normalized_messages = deepcopy(self.system + self.messages)

        def remove_keys(obj, keys_to_remove: list[str]):
            """递归移除指定的键"""
            if isinstance(obj, dict):
                for key in keys_to_remove:
                    obj.pop(key, None)
                for value in obj.values():
                    remove_keys(value, keys_to_remove)
            elif isinstance(obj, list):
                for item in obj:
                    remove_keys(item, keys_to_remove)

        remove_keys(normalized_messages, ["cache_control", "signature"])
        normalized_str = json.dumps(normalized_messages, sort_keys=True)[1:-1]
        return normalized_str


def convert_tools(tools_data):
    """将原始工具格式转换为目标格式"""
    if not tools_data:
        return []
    
    converted_tools = []
    for tool in tools_data:
        converted_tool = {
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
        
        if "input_schema" in tool:
            input_schema = tool["input_schema"]
            
            if "properties" in input_schema:
                converted_tool["function"]["parameters"]["properties"] = input_schema["properties"]
            
            if "required" in input_schema:
                converted_tool["function"]["parameters"]["required"] = input_schema["required"]
        
        converted_tools.append(converted_tool)
    
    return converted_tools


def convert_messages(messages_data, system_prompt=None):
    """将原始消息格式转换为目标格式"""
    converted_messages = []
    
    tool_id_to_name = {}
    tool_call_order = []

    # 第一遍遍历，建立映射关系
    for msg in messages_data:
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            current_assistant_tools = []
            for item in content:
                if item.get("type") == "tool_use":
                    tool_id = item.get("id", "")
                    tool_name = item.get("name", "")
                    if tool_id and tool_name:
                        tool_id_to_name[tool_id] = tool_name
                        current_assistant_tools.append(tool_id)
            if current_assistant_tools:
                tool_call_order.append(current_assistant_tools)

    # 添加系统消息
    if system_prompt:
        converted_messages.append({
            "role": "system",
            "content": system_prompt
        })
    
    tool_call_index = 0
    
    for msg in messages_data:
        role = msg.get("role", "")
        content = msg.get("content", [])
        
        if role == "user":
            user_content = ""
            tool_result_dict = {}
            
            if isinstance(content, str):
                user_content = content
                converted_messages.append({
                    "role": "user",
                    "content": user_content
                })
            else:
                for item in content:
                    if item.get("type") == "text":
                        user_content += item.get("text", "")
                    elif item.get("type") == "tool_result":
                        tool_use_id = item.get("tool_use_id", "")
                        tool_name = tool_id_to_name.get(tool_use_id, tool_use_id)
                        tool_result_dict[tool_use_id] = {
                            "role": "tool",
                            "tool_name": tool_name,
                            "content": item.get("content", "")
                        }
                        
                if tool_result_dict:
                    if tool_call_index < len(tool_call_order):
                        current_order = tool_call_order[tool_call_index]
                        for tool_id in current_order:
                            if tool_id in tool_result_dict:
                                converted_messages.append(tool_result_dict[tool_id])
                        tool_call_index += 1
                    else:
                        for tool_result in tool_result_dict.values():
                            converted_messages.append(tool_result)
                    
                    if user_content:
                        converted_messages.append({
                            "role": "user",
                            "content": user_content
                        })
                else:
                    if user_content:
                        converted_messages.append({
                            "role": "user",
                            "content": user_content
                        })
        
        elif role == "assistant":
            text_content = ""
            tool_calls = []
            thinking_content = ""
            thinking_block_count = 0
            
            for item in content:
                if item.get("type") == "text":
                    text_content = item.get("text", "")
                elif item.get("type") == "tool_use":
                    tool_name = item.get("name", "")
                    tool_input = item.get("input", {})
                    
                    tool_calls.append({
                        "name": tool_name,
                        "arguments": tool_input
                    })
                elif item.get("type") == "thinking":
                    thinking_block_count += 1
                    thinking_content = item.get("thinking", "")
            
            if thinking_block_count > 1:
                return None
            
            assistant_message = {
                "role": "assistant",
                "content": text_content,
                "reasoning_content": thinking_content,
                "generation": msg.get("generation", False)  # 默认为 False
            }

            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            
            converted_messages.append(assistant_message)

    return converted_messages


def convert_response(response_data):
    """转换响应数据"""
    if not response_data:
        return {}
    
    content = ""
    reasoning_content = ""
    tool_calls = []
    
    # 默认 generation 为 False
    is_generation = False
    
    if "content" in response_data and isinstance(response_data["content"], list):
        for item in response_data["content"]:
            # 检查是否标记了 generation (由 dedup.py 注入)
            if item.get("generation") is True:
                is_generation = True
                
            if item.get("type") == "text":
                content = item.get("text", "")
            elif item.get("type") == "thinking":
                reasoning_content = item.get("thinking", "")
            elif item.get("type") == "tool_use":
                tool_name = item.get("name", "")
                tool_input = item.get("input", {})
                
                tool_calls.append({
                    "name": tool_name,
                    "arguments": tool_input
                })
    
    response_data = {
        "role": "assistant",
        "content": content,
        "reasoning_content": reasoning_content,
        "generation": is_generation
    }
    
    if tool_calls:
        response_data["tool_calls"] = tool_calls

    return response_data


def convert_completion_to_msg(completion: Completion, min_assistant_turns: int) -> dict:
    """将 Completion 转换为消息格式，并过滤 assistant 轮数"""
    # 提取系统提示
    
    # 提取元数据
    meta = completion.metadata.copy()
    meta['max_tokens'] = completion.max_tokens
    meta['session_id'] = completion.session_id
    meta['biz_id'] = completion.biz_id
    meta['model'] = completion.model
    
    # 转换工具
    tools = convert_tools(completion.tools)
    
    # 转换消息
    messages = convert_messages(completion.messages, completion.system)
    if messages is None:
        return None
    
    # 转换响应并添加到消息中
    response_message = convert_response({"content": completion.completion})
    if response_message:
        messages.append(response_message)
    
    # 统计 assistant 轮数
    assistant_count = sum(1 for msg in messages if msg.get("role") == "assistant")
    
    # 如果 assistant 轮数小于最小要求，返回 None
    if assistant_count < min_assistant_turns:
        return None
    
    return {
        "meta": meta,
        "tools": tools,
        "messages": messages
    }


def merge_completions(completions: List[Completion]) -> List[Completion]:
    """合并去重同一 session 的 completions"""
    if not completions:
        return []

    normalized_strs = [comp.normalize() for comp in completions]
    keep = [True] * len(completions)

    for i in range(len(completions)):
        if not keep[i]:
            continue

        for j in range(i + 1, len(completions)):
            if not keep[j]:
                continue

            if normalized_strs[j].startswith(normalized_strs[i]):
                keep[i] = False
                break

    result = [completions[i] for i in range(len(completions)) if keep[i]]
    return result


def session_id_to_bucket(session_id: str, num_buckets: int) -> int:
    """使用 hash 将 session_id 映射到桶编号"""
    hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
    return hash_val % num_buckets

