import json
import os
import sys
import ray
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict



# convert
# 添加当前目录到 sys.path 以支持导入 utils
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from utils import (
    Completion,
    convert_completion_to_msg,
    session_id_to_bucket
)
from dedup import deduplicate_and_mark


@ray.remote
def read_and_bucket_file(file_path: str, num_buckets: int, bucket_dir: str, file_index: int) -> Dict[int, int]:
    """读取单个文件并分桶保存到独立的临时文件（避免文件锁竞争）"""
    buckets = defaultdict(list)
    total_records = 0
    
    # 读取文件并分桶到内存
    with open(file_path, 'r', encoding='utf-8', errors='surrogatepass') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                # 跳过 model 包含 haiku 的数据
                model_name = data.get("meta", {}).get("model", "")
                if "haiku" in model_name.lower():
                    continue
                session_id = data.get("session_id", "")
                bucket_id = session_id_to_bucket(session_id, num_buckets)
                buckets[bucket_id].append(data)
                total_records += 1
            except Exception as e:
                print(f"读取行时出错: {e}")
    
    # 每个桶写入独立的临时文件（使用 file_index 避免冲突）
    os.makedirs(bucket_dir, exist_ok=True)
    bucket_stats = {}
    for bucket_id, bucket_data in buckets.items():
        # 每个输入文件对应一个独立的临时桶文件
        bucket_file = os.path.join(bucket_dir, f"raw_bucket_{bucket_id:04d}_file_{file_index:06d}.jsonl")
        with open(bucket_file, 'w', encoding='utf-8', errors='surrogatepass') as f:
            for data in bucket_data:
                try:
                    json_str = json.dumps(data, ensure_ascii=False)
                except UnicodeEncodeError:
                    json_str = json.dumps(data, ensure_ascii=True)
                f.write(json_str + '\n')
        bucket_stats[bucket_id] = len(bucket_data)
    
    return bucket_stats


@ray.remote
def process_and_save_bucket(
    bucket_id: int,
    raw_bucket_dir: str,
    min_assistant_turns: int,
    output_dir: str
) -> Tuple[int, int, str]:
    """从桶的所有临时文件读取数据，处理并保存：去重、转换、过滤、保存"""
    # 1. 找到该桶的所有临时文件
    import glob
    pattern = os.path.join(raw_bucket_dir, f"raw_bucket_{bucket_id:04d}_file_*.jsonl")
    bucket_files = glob.glob(pattern)
    
    if not bucket_files:
        return (0, 0, "")
    
    # 2. 从所有临时文件读取数据并转换为 Completion 对象
    completions = []
    total_records = 0
    
    for bucket_file in bucket_files:
        with open(bucket_file, 'r', encoding='utf-8', errors='surrogatepass') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    completions.append(Completion.from_dict(data))
                    total_records += 1
                except Exception as e:
                    print(f"桶 {bucket_id}: 读取/转换 Completion 时出错: {e}")
    
    # 3. 按 session_id 分组
    grouped = defaultdict(list)
    for comp in completions:
        grouped[comp.session_id].append(comp)
    
    # 4. 对每个 session 按时间排序
    for session_id in grouped:
        grouped[session_id].sort(key=lambda x: x.request_time)
    
    # 5. 合并去重
    merged_completions = []
    for session_id, comps in grouped.items():
        merged = deduplicate_and_mark(comps)
        merged_completions.extend(merged)
    
    # 6. 转换为消息格式并过滤
    converted_messages = []
    for comp in merged_completions:
        try:
            msg = convert_completion_to_msg(comp, min_assistant_turns)
            if msg is not None:
                converted_messages.append(msg)
        except Exception as e:
            print(f"桶 {bucket_id}: 转换消息时出错: {e}")
    
    # 7. 保存到文件（每个桶一个文件）
    output_file = os.path.join(output_dir, f"processed_bucket_{bucket_id:04d}.jsonl")
    saved_count = 0
    
    if converted_messages:
        os.makedirs(output_dir, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8', errors='surrogatepass') as f:
            for data in converted_messages:
                try:
                    json_str = json.dumps(data, ensure_ascii=False)
                except UnicodeEncodeError:
                    json_str = json.dumps(data, ensure_ascii=True)
                f.write(json_str + '\n')
                saved_count += 1
    
    return (total_records, saved_count, output_file if saved_count > 0 else "")


def process_files_with_ray(
    input_path: str,
    output_path: str,
    num_buckets: int = 100,
    min_assistant_turns: int = 3,
    chunk_size: int = 10000
):
    """使用 Ray 并发处理文件"""
    # 初始化 Ray
    if not ray.is_initialized():
        ray.init()
    
    print("=" * 60)
    print("开始处理数据")
    print("=" * 60)
    
    # 1. 收集所有输入文件（递归遍历所有子目录）
    input_path_obj = Path(input_path)
    if input_path_obj.is_file():
        input_files = [input_path_obj]
    else:
        input_files = [f for f in input_path_obj.rglob("*") if f.is_file()]
    
    print(f"找到 {len(input_files)} 个输入文件")
    
    # 2. 创建临时目录
    output_path_obj = Path(output_path)
    temp_base_dir = output_path_obj.parent / f"{output_path_obj.stem}_temp"
    raw_bucket_dir = temp_base_dir / "raw_buckets"
    processed_bucket_dir = temp_base_dir / "processed_buckets"
    os.makedirs(raw_bucket_dir, exist_ok=True)
    os.makedirs(processed_bucket_dir, exist_ok=True)
    
    # 3. 并发读取文件并分桶保存（每个文件写入独立的临时文件，避免锁竞争）
    print(f"\n开始读取文件并分桶保存 (共 {num_buckets} 个桶)...")
    read_tasks = [
        read_and_bucket_file.remote(str(f), num_buckets, str(raw_bucket_dir), file_idx) 
        for file_idx, f in enumerate(input_files)
    ]
    read_results = ray.get(read_tasks)
    
    # 4. 统计分桶结果（只收集统计信息，不收集数据）
    bucket_counts = defaultdict(int)
    total_records = 0
    for bucket_stats in read_results:
        for bucket_id, count in bucket_stats.items():
            bucket_counts[bucket_id] += count
            total_records += count
    
    print(f"总共读取 {total_records} 条记录")
    print(f"分配到 {len(bucket_counts)} 个非空桶")
    
    # 5. 并发处理每个桶（worker 节点从桶的所有临时文件读取、处理并保存）
    print(f"\n开始处理桶并保存 (最小 assistant 轮数: {min_assistant_turns})...")
    process_tasks = []
    for bucket_id in bucket_counts.keys():
        task = process_and_save_bucket.remote(
            bucket_id,
            str(raw_bucket_dir),
            min_assistant_turns,
            str(processed_bucket_dir)
        )
        process_tasks.append(task)
    
    # 等待所有任务完成，获取统计信息
    process_results = ray.get(process_tasks)
    
    # 6. 统计结果
    total_saved = sum(saved for _, saved, _ in process_results)
    saved_files = [f for _, _, f in process_results if f]
    
    print(f"\n处理完成，共保存 {total_saved} 条有效轨迹到 {len(saved_files)} 个桶文件")
    
    # 7. 合并桶文件到最终输出
    print(f"\n合并桶文件到最终输出...")
    os.makedirs(output_path_obj.parent, exist_ok=True)
    
    # 按 chunk_size 分块合并
    if total_saved > chunk_size:
        num_chunks = (total_saved + chunk_size - 1) // chunk_size
        print(f"结果数量 {total_saved} 超过分块大小 {chunk_size}，将分成 {num_chunks} 个文件保存")
        
        current_chunk = 0
        current_count = 0
        output_file = None
        
        for bucket_file in sorted(saved_files):
            with open(bucket_file, 'r', encoding='utf-8', errors='surrogatepass') as f:
                for line in f:
                    if current_count % chunk_size == 0:
                        if output_file:
                            output_file.close()
                        current_chunk += 1
                        chunk_output_path = output_path_obj.parent / f"{output_path_obj.stem}_part{current_chunk:03d}{output_path_obj.suffix}"
                        output_file = open(chunk_output_path, 'w', encoding='utf-8', errors='surrogatepass')
                        print(f"  创建分块 {current_chunk}/{num_chunks}: {chunk_output_path}")
                    
                    output_file.write(line)
                    current_count += 1
        
        if output_file:
            output_file.close()
    else:
        # 结果数量不超过 chunk_size，合并到单个文件
        with open(output_path, 'w', encoding='utf-8', errors='surrogatepass') as out_f:
            for bucket_file in sorted(saved_files):
                with open(bucket_file, 'r', encoding='utf-8', errors='surrogatepass') as in_f:
                    for line in in_f:
                        out_f.write(line)
        print(f"结果已保存到: {output_path}")
    
    # 8. 清理临时文件
    print(f"\n清理临时文件...")
    import shutil
    shutil.rmtree(temp_base_dir)
    
    print("\n" + "=" * 60)
    print("处理完成！")
    print(f"输入记录数: {total_records}")
    print(f"输出轨迹数: {total_saved}")
    print(f"过滤比例: {(total_records - total_saved) / total_records * 100:.1f}%")
    if total_saved > chunk_size:
        print(f"输出文件: {output_path_obj.parent} (共 {num_chunks} 个分块文件)")
    else:
        print(f"输出文件: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="使用 Ray 并发处理轨迹数据：去重、转换、过滤")
    parser.add_argument("--input_path", type=str, required=True, help="输入文件或目录路径")
    parser.add_argument("--output_path", type=str, required=True, help="输出文件路径")
    parser.add_argument("--num_buckets", type=int, default=100, help="分桶数量 (默认: 100)")
    parser.add_argument("--min_assistant_turns", type=int, default=3, help="最小 assistant 轮数 (默认: 3)")
    parser.add_argument("--chunk_size", type=int, default=10000, help="分块大小 (默认: 10000)")
    
    args = parser.parse_args()
    
    process_files_with_ray(
        input_path=args.input_path,
        output_path=args.output_path,
        num_buckets=args.num_buckets,
        min_assistant_turns=args.min_assistant_turns,
        chunk_size=args.chunk_size
    )

