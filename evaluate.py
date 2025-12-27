#!/usr/bin/env python3
"""
轨迹评估器 - 评估 convert 后的轨迹

用法:
    python evaluate.py \
        --trajectories ./results/converted_for_training.jsonl \
        --data data_checklist.jsonl \
        --output ./results/scores.json

流程:
    1. 读取 convert 后的轨迹文件
    2. 选择主轨迹（tools 非空的记录）
    3. 根据 checklist 构造评估 prompt
    4. 调用 LLM 评分
    5. 汇总结果
"""

import argparse
import json
import os
from pathlib import Path
from copy import deepcopy
from openai import OpenAI


# 评估 Prompt - 复用 run_agent_evaluate.py 的逻辑
EVAL_PROMPT = """
你是一个「Agent 指令遵循」评审模型。

你的任务是：根据给定的 **Checklist**，逐项评估 assistant 在对话中的表现。

=====INPUT CONVERSATION=====
====TOOLS===
{tools}
====TOOLS===
====MESSAGES===
{messages}
====MESSAGES===
=====INPUT CONVERSATION=====

=====CHECKLIST TO EVALUATE=====
{checklist}
=====CHECKLIST TO EVALUATE=====

--------------------------------------------------
评估规则
--------------------------------------------------

1. **逐项评估**：对 Checklist 中的每个 check_id，判断 assistant 是否遵循该要求

2. **评估依据**：检查所有 `role == "assistant"` 的消息，包括：
   - 自然语言输出（content）
   - 内部推理（reasoning_content，如有）
   - 工具调用（tool_calls）

3. **判定标准**：
   - `"success"`：assistant 明确遵循了该要求
   - `"fail"`：assistant 明显违背了该要求，或在应该遵循时未遵循

4. **reasoning 字段**：
   - 对于 "fail"：简要说明 assistant 如何违背该要求（可引用消息索引）
   - 对于 "success"：简要说明 assistant 如何遵循该要求

--------------------------------------------------
输出格式（必须为合法 JSON）
--------------------------------------------------

输出一个 JSON 对象，结构与输入的 Checklist 相同，但每个 check 增加 "reasoning" 和 "result" 字段：

{{
  "CategoryName": {{
    "description": "...(保持原样)",
    "checks": [
      {{
        "check_id": "xxx",
        "description": "...(保持原样)",
        "check_type": "...(保持原样)",
        "reasoning": "简要说明判定依据",
        "result": "success 或 fail"
      }}
    ]
  }}
}}

--------------------------------------------------
注意事项
--------------------------------------------------

1. 必须对 Checklist 中的**每个** check_id 进行评估，不可遗漏
2. result 只能是 "success" 或 "fail"（小写），不允许其他值
3. 输出必须是合法 JSON，不要在 JSON 外添加任何文字
4. 保持原有的 category 结构和字段

请严格按照 Checklist 进行评估，输出完整的 JSON 结果。
"""


def load_trajectory(filepath):
    """加载 convert 后的轨迹，返回主轨迹
    
    主轨迹判断规则：
    1. 优先选择有 tools 的记录（非空数组）
    2. 如果有多个有 tools 的，选 messages 最多的
    3. 如果都没有 tools，选最后一条
    """
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    
    if not records:
        return None
    
    # 过滤出有 tools 的记录（主轨迹）
    with_tools = [r for r in records if r.get("tools")]
    
    if with_tools:
        # 有多个的话，选 messages 最多的那个
        return max(with_tools, key=lambda r: len(r.get("messages", [])))
    
    # 都没有 tools，返回最后一条
    return records[-1]


def format_trajectory_for_eval(record, checklist):
    """格式化轨迹用于评估 - convert 后的格式
    
    格式：
    - record["tools"]
    - record["messages"]
    """
    max_tool_content_length = 5000
    max_assistant_content_length = 50000
    max_assistant_reasoning_content_length = 50000

    messages = record.get("messages", [])
    tools = record.get("tools", [])
    
    truncated_messages = []
    assistant_turn_index = 0
    
    for message in messages:
        msg = deepcopy(message)
        role = msg.get("role")
        
        if role == "tool":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > max_tool_content_length:
                msg["content"] = (
                    content[:max_tool_content_length//2] + 
                    "\n\n[content too long, truncated]\n\n" + 
                    content[-max_tool_content_length//2:]
                )
        elif role == "assistant":
            # 处理 content（可能是 string 或 list）
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > max_assistant_content_length:
                msg["content"] = (
                    content[:max_assistant_content_length//2] + 
                    "\n\n[content too long, truncated]\n\n" + 
                    content[-max_assistant_content_length//2:]
                )
            elif isinstance(content, list):
                # 处理 list 格式的 content
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        if len(text) > max_assistant_content_length:
                            item["text"] = (
                                text[:max_assistant_content_length//2] + 
                                "\n\n[content too long, truncated]\n\n" + 
                                text[-max_assistant_content_length//2:]
                            )
            
            # 处理 reasoning_content
            reasoning = msg.get("reasoning_content", "")
            if isinstance(reasoning, str) and len(reasoning) > max_assistant_reasoning_content_length:
                msg["reasoning_content"] = (
                    reasoning[:max_assistant_reasoning_content_length//2] + 
                    "\n\n[reasoning too long, truncated]\n\n" + 
                    reasoning[-max_assistant_reasoning_content_length//2:]
                )
            
            msg["assistant_turn_index"] = assistant_turn_index
            assistant_turn_index += 1
        
        truncated_messages.append(msg)
    
    # 格式化输出
    tools_str = "\n".join([json.dumps(t, ensure_ascii=False) for t in tools])
    messages_str = "\n".join([json.dumps(m, ensure_ascii=False) for m in truncated_messages])
    checklist_str = json.dumps(checklist, ensure_ascii=False, indent=2)
    
    return EVAL_PROMPT.format(
        tools=tools_str, 
        messages=messages_str,
        checklist=checklist_str
    )


def call_llm(prompt, api_key=None, base_url=None, model="gpt-4o"):
    """调用 LLM 进行评估"""
    client = OpenAI(
        api_key=api_key or os.environ.get("OPENAI_API_KEY"),
        base_url=base_url or os.environ.get("OPENAI_BASE_URL")
    )
    
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=4096
    )
    
    return response.choices[0].message.content


def parse_eval_result(response_text):
    """解析 LLM 返回的评估结果"""
    try:
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        return {"error": str(e), "raw_response": response_text}


def calculate_reward(eval_result):
    """计算 reward 分数"""
    if "error" in eval_result:
        return 0.0
    
    total = 0
    success = 0
    
    for category, data in eval_result.items():
        checklist = data.get("checks", [])
        for item in checklist:
            total += 1
            if item.get("result") == "success":
                success += 1
    
    if total == 0:
        return 0.0
    
    return round(success / total, 3)


def get_detailed_results(eval_result):
    """获取详细的评估结果统计"""
    if "error" in eval_result:
        return {}
    
    results = {
        "total_checks": 0,
        "total_success": 0,
        "total_fail": 0,
        "by_category": {},
        "by_check_type": {}
    }
    
    for category, value in eval_result.items():
        cat_success = 0
        cat_fail = 0
        
        for item in value.get("checks", []):
            check_type = item.get("check_type", "unknown")
            is_success = item.get("result") == "success"
            
            if is_success:
                cat_success += 1
                results["total_success"] += 1
            else:
                cat_fail += 1
                results["total_fail"] += 1
            
            results["total_checks"] += 1
            
            # 按 check_type 统计
            if check_type not in results["by_check_type"]:
                results["by_check_type"][check_type] = {"success": 0, "fail": 0}
            if is_success:
                results["by_check_type"][check_type]["success"] += 1
            else:
                results["by_check_type"][check_type]["fail"] += 1
        
        results["by_category"][category] = {
            "success": cat_success,
            "fail": cat_fail,
            "total": cat_success + cat_fail
        }
    
    return results


def evaluate_single(trajectory_path, case_data, llm_config):
    """评估单个轨迹"""
    # 加载主轨迹
    record = load_trajectory(trajectory_path)
    if not record:
        return {
            "success": False,
            "error": "轨迹文件为空",
            "reward": 0.0
        }
    
    # 获取 checklist
    checklist = case_data.get("checklist", {})
    if not checklist:
        return {
            "success": False,
            "error": "case 中没有 checklist",
            "reward": 0.0
        }
    
    # 构建评估 prompt
    prompt = format_trajectory_for_eval(record, checklist)
    
    try:
        # 调用 LLM
        response = call_llm(
            prompt,
            api_key=llm_config.get("api_key"),
            base_url=llm_config.get("base_url"),
            model=llm_config.get("model", "gpt-4o")
        )
        
        eval_result = parse_eval_result(response)
        reward = calculate_reward(eval_result)
        detailed = get_detailed_results(eval_result)
        
        return {
            "success": True,
            "eval_result": eval_result,
            "detailed_results": detailed,
            "reward": reward,
            "binary_reward": 1 if reward == 1.0 else 0
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "reward": 0.0
        }


def main():
    parser = argparse.ArgumentParser(description="轨迹评估器 - 评估 convert 后的轨迹")
    parser.add_argument("--trajectories", required=True, help="convert 后的轨迹文件或目录")
    parser.add_argument("--data", required=True, help="测试用例文件 (包含 checklist 的 JSONL)")
    parser.add_argument("--output", default="./scores.json", help="输出文件")
    parser.add_argument("--model", default="gpt-4o", help="评估用的 LLM 模型")
    parser.add_argument("--api-key", help="LLM API Key")
    parser.add_argument("--base-url", help="LLM API Base URL")
    parser.add_argument("--case", help="只评估指定 instance_id")
    args = parser.parse_args()
    
    # 加载测试用例（包含 checklist）
    with open(args.data) as f:
        cases = {json.loads(line)["instance_id"]: json.loads(line) for line in f if line.strip()}
    
    print(f"[EVAL] 加载了 {len(cases)} 个测试用例")
    
    # 获取轨迹文件
    traj_path = Path(args.trajectories)
    if traj_path.is_file():
        # 单个文件（如 converted_for_training.jsonl）
        # 需要从 meta.session_id 获取 instance_id
        trajectory_files = [traj_path]
        # 读取文件获取所有 session_id
        session_to_file = {}
        with open(traj_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    session_id = record.get("meta", {}).get("session_id", "")
                    if session_id and session_id not in session_to_file:
                        session_to_file[session_id] = str(traj_path)
        print(f"[EVAL] 从文件中找到 {len(session_to_file)} 个 session")
    else:
        # 目录（每个 case 一个文件）
        trajectory_files = list(traj_path.glob("*.jsonl"))
        session_to_file = {f.stem: str(f) for f in trajectory_files}
        print(f"[EVAL] 找到 {len(trajectory_files)} 个轨迹文件")
    
    llm_config = {
        "api_key": args.api_key,
        "base_url": args.base_url,
        "model": args.model
    }
    
    results = []
    
    for instance_id, case_data in cases.items():
        if args.case and instance_id != args.case:
            continue
        
        if instance_id not in session_to_file:
            print(f"[WARN] {instance_id} 没有对应的轨迹文件，跳过")
            continue
        
        print(f"[EVAL] 评估: {instance_id}")
        
        traj_file = session_to_file[instance_id]
        eval_result = evaluate_single(traj_file, case_data, llm_config)
        
        results.append({
            "instance_id": instance_id,
            **eval_result
        })
        
        status = "success" if eval_result.get("success") else "failed"
        print(f"[EVAL] {instance_id}: {status}, reward={eval_result.get('reward', 0)}")
    
    # 汇总结果
    output_data = {
        "results": results,
        "summary": {
            "total": len(results),
            "success_count": sum(1 for r in results if r.get("success")),
            "avg_reward": round(sum(r.get("reward", 0) for r in results) / len(results), 3) if results else 0,
            "pass_count": sum(1 for r in results if r.get("binary_reward") == 1)
        }
    }
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"[DONE] 评估完成")
    print(f"[DONE] 总数: {output_data['summary']['total']}")
    print(f"[DONE] 成功: {output_data['summary']['success_count']}")
    print(f"[DONE] 平均分: {output_data['summary']['avg_reward']}")
    print(f"[DONE] 通过数: {output_data['summary']['pass_count']}")
    print(f"[DONE] 结果: {args.output}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
