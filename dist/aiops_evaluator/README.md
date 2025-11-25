# 评测工具


## 评测文件

results_phase_1.json

## 数据格式长这样

提交文件和标准答案都必须是 JSON Lines，每行一个样本，最少要有下面几个字段：

```
{
  "uuid": "33c11d00-2",
  "component": "checkoutservice",
  "reason": "disk IO overload",
  "reasoning_trace": [
    {"step": 1, "action": "QueryMetric", "observation": "disk_read_latency spike"}
  ]
}
```

标准答案里如果还有 `reason_keywords`、`evidence_points` 这些字段，可以保留，打分脚本会自动使用。

## 最快的使用方法

1. 在命令行里进入本文件夹
2. 运行：

```
python evaluate.py -g ground_truth_phase1.jsonl -s results_phase_1.json --show-details
```

3. 屏幕上会看到总分和逐条样本的命中情况。

常用参数：
- `-g` 或 `--ground-truth`：标准答案路径。
- `-s` 或 `--submission`：提交文件路径。
- `--reason-threshold`：理由相似度阈值，默认 0.65，不懂就别改。
- `--show-details`：输出每条样本的命中情况，方便排查。
- `-o 报告文件`：把详细结果写成 JSON 文件。