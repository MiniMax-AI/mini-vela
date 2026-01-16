#!/bin/bash
# OctoBench 评估流水线
# 用法: ./run.sh [--model MODEL] [--dataset DATASET] [--skip-eval]

set -e

# 默认参数
MODEL="claude-sonnet-4-5-20250929"
DATASET="MiniMaxAI/OctoCodingBench"
SKIP_EVAL=false
RESULTS_DIR="./results"
TRAJECTORIES_DIR="${RESULTS_DIR}/trajectories"
MERGED_FILE="${RESULTS_DIR}/merged_trajectories.jsonl"
SCORES_FILE="${RESULTS_DIR}/scores.json"

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --dataset)
            DATASET="$2"
            shift 2
            ;;
        --skip-eval)
            SKIP_EVAL=true
            shift
            ;;
        --help|-h)
            echo "用法: ./run.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --model MODEL      指定评估模型 (如 claude-sonnet-4-5-20250929)"
            echo "  --dataset DATASET  数据集路径或 HuggingFace ID"
            echo "  --skip-eval        跳过评估步骤，只运行任务和轨迹处理"
            echo "  -h, --help         显示帮助信息"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "OctoBench 评估流水线"
echo "=============================================="
echo "数据集: ${DATASET}"
echo "模型: ${MODEL}"
echo "结果目录: ${RESULTS_DIR}"
echo "=============================================="

# Step 1: 运行 Benchmark
echo ""
echo "[Step 1/3] 运行 Benchmark..."
if [ -n "$MODEL" ]; then
    python benchmark_runner.py --dataset "$DATASET" --model "$MODEL"
else
    python benchmark_runner.py --dataset "$DATASET"
fi

# Step 2: 轨迹处理
echo ""
echo "[Step 2/3] 处理轨迹..."
python convert/convert_cc_traj_to_msg.py \
    --input_path "$TRAJECTORIES_DIR" \
    --output_path "$MERGED_FILE"

# Step 3: 评估 (可选)
if [ "$SKIP_EVAL" = false ]; then
    echo ""
    echo "[Step 3/3] 评估轨迹..."
    python evaluate.py \
        --trajectories "$MERGED_FILE" \
        --data "$DATASET" \
        --output "$SCORES_FILE"
else
    echo ""
    echo "[Step 3/3] 跳过评估"
fi

echo ""
echo "=============================================="
echo "完成!"
echo "轨迹文件: ${MERGED_FILE}"
if [ "$SKIP_EVAL" = false ]; then
    echo "评估结果: ${SCORES_FILE}"
fi
echo "=============================================="
