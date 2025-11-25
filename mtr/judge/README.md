# AIOps 提交评测工具

这个文件夹里放着线下打分脚本，专门用来评测提交结果。想不明白的时候，可以先看同目录的《评测程序编写思路.md》。

## 你需要准备什么

1. Python 3.10 及以上版本（系统自带或者虚拟环境都行）。
2. 一份标准答案（ground truth）JSONL 文件。
3. 一份待评测的提交 JSONL 文件。

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

1. 在命令行里进入本文件夹，例如：`cd mtr/judge`。
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

## 想重新生成标准答案？

官方提供的原始标注是 `phase1.json`、`phase2.jsonl`。运行下面命令就能转换成评测脚本需要的格式：

```
python convert_ground_truth.py phase1.json --output ground_truth_phase1.jsonl
python convert_ground_truth.py phase1.json phase2.jsonl --output ground_truth_phase12.jsonl
```

转换脚本已经按官方文档处理好 component 命名，不需要再手动改。

## 先试试示例数据

`samples/` 文件夹里有两条示例题，适合快速检查环境：

```
python evaluate.py -g samples/ground_truth.jsonl -s samples/submission.jsonl --show-details
```

只要能打印出分数，就说明环境没问题。剩下的就是把你们自己的提交放进来打分啦。
