import json
import hashlib
from typing import List, Dict
from copy import deepcopy
from utils import Completion

def get_messages_hash(messages: List[dict]) -> str:
    """计算消息列表的归一化哈希值"""
    # 移除无关字段以确保哈希一致性
    normalized_messages = deepcopy(messages)

    # 强制将第一条 user message 的 content 转换为 string
    for msg in normalized_messages:
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, list):
                text_content = ""
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_content += item.get("text", "")
                    elif isinstance(item, str):
                        text_content += item
                msg["content"] = text_content
            break
    
    def remove_keys(obj, keys_to_remove: list[str]):
        if isinstance(obj, dict):
            for key in keys_to_remove:
                obj.pop(key, None)
            for value in obj.values():
                remove_keys(value, keys_to_remove)
        elif isinstance(obj, list):
            for item in obj:
                remove_keys(item, keys_to_remove)
    
    def remove_thinking_items(obj):
        """递归移除 type=thinking 的 item，确保 hash 不受 thinking 影响"""
        if isinstance(obj, dict):
            # 如果 content 是 list，过滤掉 thinking items
            if "content" in obj and isinstance(obj["content"], list):
                obj["content"] = [
                    item for item in obj["content"] 
                    if not (isinstance(item, dict) and item.get("type") == "thinking")
                ]
            for value in obj.values():
                remove_thinking_items(value)
        elif isinstance(obj, list):
            for item in obj:
                remove_thinking_items(item)

    remove_keys(normalized_messages, ["cache_control", "signature", "generation"])
    remove_thinking_items(normalized_messages)
    # 使用 sort_keys=True 保证确定性
    normalized_str = json.dumps(normalized_messages, sort_keys=True)
    return hashlib.md5(normalized_str.encode()).hexdigest()

def deduplicate_and_mark(completions: List[Completion]) -> List[Completion]:
    """
    高效去重并标记 generation 字段
    
    流程：
    1. 构建真实请求指纹库 (Ground Truth) 和响应内容映射
    2. 原版去重逻辑 (复用原始 utils.py 的逻辑)
    3. 回放轨迹并标记 generation，同时恢复前置轮次的 reasoning_content
    """
    if not completions:
        return []

    # 0. 确保按时间排序 (复刻原始逻辑的前提)
    completions.sort(key=lambda x: x.request_time)

    # 1. 构建真实请求指纹库和响应内容映射
    # 记录所有在原始数据中出现过的 "System + User History" 状态及其出现次数
    valid_request_hash_counts: Dict[str, int] = {}
    # 新增：记录每个上下文对应的完整 response 内容（包含 reasoning_content/thinking）
    context_to_response: Dict[str, List[list]] = {}
    
    normalized_strs = []

    for i, comp in enumerate(completions):
        # 1.1 记录这个 Completion 对应的请求上下文指纹及其出现次数
        system = comp.system if comp.system is not None else []
        messages = comp.messages if comp.messages is not None else []
        completion_content = comp.completion if comp.completion is not None else []

        full_context = system + messages
        context_hash = get_messages_hash(full_context)
        roles = [m.get("role", "system") for m in full_context]
        if len(roles) <= 3:
            with open("dedup.log", "a") as f:
                f.write(f"DEBUG: Pass 1 [Idx {i}] History Assistant. Hash={context_hash}... History Roles={roles}, full_context={len(full_context)}\n")
        valid_request_hash_counts[context_hash] = valid_request_hash_counts.get(context_hash, 0) + 1
        
        # 1.2 新增：记录该上下文对应的完整 response 内容
        if context_hash not in context_to_response:
            context_to_response[context_hash] = []
        context_to_response[context_hash].append(deepcopy(completion_content))
        
        # 1.3 准备去重用的字符串
        # 严格复刻 utils.py 的 normalize 逻辑：只包含 system + messages
        
        trajectory_for_dedup = system + messages
        traj_copy = deepcopy(trajectory_for_dedup)
        
        def clean_for_sort(obj):
            if isinstance(obj, dict):
                obj.pop("cache_control", None)
                obj.pop("signature", None)
                obj.pop("generation", None)
                for v in obj.values():
                    clean_for_sort(v)
            elif isinstance(obj, list):
                for item in obj:
                    clean_for_sort(item)
        
        clean_for_sort(traj_copy)
        
        norm_str = json.dumps(traj_copy, sort_keys=True)[1:-1]
        normalized_strs.append(norm_str)

    # 2. 去重
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

    final_completions = []
    for i in range(len(completions)):
        if keep[i]:
            final_completions.append(completions[i])

    # print(f"final_completions: {len(final_completions)}")
    # print(f"valid_request_hash_counts: {len(valid_request_hash_counts)}")

    # 3. 轨迹回放与 Generation 标记 + 恢复前置轮次的 reasoning_content
    # 复制一份计数字典用于消耗，避免同一状态被多次训练
    remaining_hash_counts = dict(valid_request_hash_counts)
    # 复制响应内容映射用于消耗
    remaining_response_contents: Dict[str, List[list]] = {k: list(v) for k, v in context_to_response.items()}
    
    for idx, comp in enumerate(final_completions):
        # 重建完整消息流
        system = comp.system if comp.system is not None else []
        messages = comp.messages if comp.messages is not None else []
        completion_content = comp.completion if comp.completion is not None else []
        
        current_history = list(system)
        
        # 遍历 messages (History)
        # roles = []
        # generation_list = []
        for msg in messages:
            role = msg.get("role", "system")
            if role == "assistant":
                # 判断当前 accumulated history 是否是真实的 request，且还有剩余配额
                h_hash = get_messages_hash(current_history)
                is_generation = remaining_hash_counts.get(h_hash, 0) > 0
                msg["generation"] = is_generation
                
                # 新增：恢复完整的 response 内容（包含 reasoning_content/thinking）
                if h_hash in remaining_response_contents and remaining_response_contents[h_hash]:
                    original_response = remaining_response_contents[h_hash].pop(0)
                    # 用完整的 response content 替换 assistant msg 的 content
                    # 这样可以恢复被 request body 丢弃的 thinking block
                    msg["content"] = original_response
                
                # 如果匹配成功，消耗一次配额
                if is_generation:
                    remaining_hash_counts[h_hash] -= 1
                # roles = [m.get("role", "system") for m in current_history]
                # generation_list.append(is_generation)
                # if len(roles) <= 5:
                #     with open("dedup.log", "a") as f:
                #         f.write(f"DEBUG: Pass 3 [Idx {idx}] History Assistant. Hash={h_hash}... Found={is_generation}. History Roles={roles}, current_history={len(current_history)}\n")
            current_history.append(msg)
        
        # 处理 completion (Response) 部分
        final_context = system + messages
        final_hash = get_messages_hash(final_context)
        is_generation = remaining_hash_counts.get(final_hash, 0) > 0
        
        # 添加 completion 部分的 debug 日志
        # final_roles = [m.get("role", "system") for m in final_context]
        # if len(final_roles) <= 5:
        #     with open("dedup.log", "a") as f:
        #         f.write(f"DEBUG: Pass 3 [Idx {idx}] Completion. Hash={final_hash}... Found={is_generation}. Final Roles={final_roles}, final_context={len(final_context)}\n")
        
        for msg in completion_content:
            # completion_content 里的 items 通常没有 role 字段，直接标记
            msg["generation"] = is_generation
        # 如果匹配成功，消耗一次配额
        # if is_generation:
        #     remaining_hash_counts[final_hash] -= 1
        # generation_list.append(is_generation)

        # with open("dedup.log", "a") as f:
        #     f.write(f"DEBUG: Pass 3 [Idx {idx}]generation_list={generation_list}\n")
    return final_completions
