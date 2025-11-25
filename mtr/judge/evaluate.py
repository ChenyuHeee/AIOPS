"""
评测提交结果
根据result.jsonl 文件进行评测

"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# 本程序的数据结构
# ---------------------------------------------------------------------------

@dataclass
class SampleScore:
    # 单条样本的打分结果，用于 --show-details 或报告输出
    uuid: str
    component_correct: bool
    reason_correct: bool
    step_count: int
    evidence_hit: int
    evidence_total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_SUBMISSION_FIELDS = ("uuid", "component", "reason", "reasoning_trace")
REQUIRED_TRACE_FIELDS = ("step", "action", "observation")


def load_jsonl(path: Path, allow_empty: bool = False) -> List[Dict[str, Any]]:
    # 逐行读入JSONL
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no} of {path}: {exc}") from exc
    if not records and not allow_empty:
        raise ValueError(f"File {path} is empty; expected at least one record")
    return records


def build_index(records: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # 将 uuid 映射到对应记录，方便随机访问
    index: Dict[str, Dict[str, Any]] = {}
    for record in records:
        uuid = record.get("uuid")
        if not isinstance(uuid, str) or not uuid:
            raise ValueError("Each record must contain a non-empty string uuid")
        if uuid in index:
            raise ValueError(f"Duplicate uuid detected: {uuid}")
        index[uuid] = record
    return index


def ensure_submission_schema(record: Dict[str, Any]) -> None:
    # 严格检查提交格式，提前抛出可读错误
    for field in REQUIRED_SUBMISSION_FIELDS:
        if field not in record:
            raise ValueError(f"Submission entry {record.get('uuid')} missing field '{field}'")

    if not isinstance(record["component"], str):
        raise ValueError(f"component must be string in entry {record['uuid']}")
    if not isinstance(record["reason"], str):
        raise ValueError(f"reason must be string in entry {record['uuid']}")

    trace = record["reasoning_trace"]
    if not isinstance(trace, list):
        raise ValueError(f"reasoning_trace must be a list in entry {record['uuid']}")
    for idx, step in enumerate(trace, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"reasoning_trace[{idx}] must be an object in entry {record['uuid']}")
        for field in REQUIRED_TRACE_FIELDS:
            if field not in step:
                raise ValueError(
                    f"reasoning_trace[{idx}] in entry {record['uuid']} missing field '{field}'"
                )
        if not isinstance(step["step"], int):
            raise ValueError(f"reasoning_trace[{idx}].step must be int in entry {record['uuid']}")
        if not isinstance(step["action"], str):
            raise ValueError(
                f"reasoning_trace[{idx}].action must be string in entry {record['uuid']}"
            )
        if not isinstance(step["observation"], str):
            raise ValueError(
                f"reasoning_trace[{idx}].observation must be string in entry {record['uuid']}"
            )


def tokenize(text: str) -> List[str]:
    return [token for token in text.lower().split() if token]


def truncate_words(text: str, limit: int) -> str:
    tokens = text.split()
    if len(tokens) <= limit:
        return text.strip()
    return " ".join(tokens[:limit])


def sequence_similarity(a: str, b: str) -> float:
    return SequenceMatcher(a=a.lower(), b=b.lower()).ratio()


def jaccard_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def reason_matches(gt_reason: str, submission_reason: str, keywords: Sequence[str], threshold: float) -> bool:
    # 先用关键词判断，再回退到相似度，避免语义描述差异造成误伤
    trimmed_submission = truncate_words(submission_reason, 20)
    trimmed_gt = truncate_words(gt_reason, 20)
    submission_lower = trimmed_submission.lower()

    for keyword in keywords:
        kw_lower = keyword.lower().strip()
        if kw_lower and kw_lower in submission_lower:
            return True

    seq_score = sequence_similarity(trimmed_submission, trimmed_gt)
    token_score = jaccard_similarity(tokenize(trimmed_submission), tokenize(trimmed_gt))
    return max(seq_score, token_score) >= threshold


def normalize_component(value: str) -> str:
    return value.strip()


def normalize_observation(value: str, char_limit: int = 100, word_limit: int = 20) -> str:
    snippet = value.strip()[:char_limit]
    tokens = snippet.split()
    if len(tokens) <= word_limit:
        return " ".join(tokens)
    return " ".join(tokens[:word_limit])


def evidence_hits(evidence_points: Sequence[Dict[str, Any]], reasoning_trace: Sequence[Dict[str, Any]]) -> Tuple[int, int]:
    # 对每个 evidence 点检查推理链是否提到对应关键词
    if not evidence_points:
        return 0, 0

    normalized_observations = [normalize_observation(step.get("observation", "")) for step in reasoning_trace]
    hits = 0
    total = 0
    for point in evidence_points:
        keywords = point.get("keywords") or []
        if not isinstance(keywords, list) or not keywords:
            continue
        total += 1
        lowered_keywords = [kw.lower().strip() for kw in keywords if isinstance(kw, str) and kw.strip()]
        if not lowered_keywords:
            total -= 1
            continue
        if any(kw in obs.lower() for kw in lowered_keywords for obs in normalized_observations):
            hits += 1
    return hits, total


# ---------------------------------------------------------------------------
# Scoring pipeline
# ---------------------------------------------------------------------------


def score_submission(
    ground_truth: Dict[str, Dict[str, Any]],
    submission: Dict[str, Dict[str, Any]],
    reason_threshold: float = 0.65,
) -> Tuple[Dict[str, float], List[SampleScore]]:
    # 主打分流程：遍历 uuid，计算四项指标并汇总加权
    total_samples = len(ground_truth)
    component_hits = 0
    reason_hits_total = 0
    path_lengths: List[int] = []
    total_evidence_hits = 0
    total_evidence_points = 0
    per_sample: List[SampleScore] = []

    for uuid, gt_entry in ground_truth.items():
        submission_entry = submission[uuid]
        ensure_submission_schema(submission_entry)

        gt_component = normalize_component(gt_entry.get("component", ""))
        submission_component = normalize_component(submission_entry["component"])
        component_correct = gt_component == submission_component and bool(gt_component)
        if component_correct:
            component_hits += 1

        gt_reason = gt_entry.get("reason", "")
        gt_keywords = gt_entry.get("reason_keywords") or []
        if not isinstance(gt_keywords, list):
            gt_keywords = []
        reason_correct = False
        if isinstance(gt_reason, str) and gt_reason.strip():
            reason_correct = reason_matches(gt_reason, submission_entry["reason"], gt_keywords, reason_threshold)
        if reason_correct:
            reason_hits_total += 1

        trace_steps = submission_entry.get("reasoning_trace", [])
        step_count = len(trace_steps)
        if component_correct:
            path_lengths.append(step_count)

        evidence = gt_entry.get("evidence_points") or []
        evidence_hit, evidence_total = evidence_hits(evidence, trace_steps)
        total_evidence_hits += evidence_hit
        total_evidence_points += evidence_total

        per_sample.append(
            SampleScore(
                uuid=uuid,
                component_correct=component_correct,
                reason_correct=reason_correct,
                step_count=step_count,
                evidence_hit=evidence_hit,
                evidence_total=evidence_total,
            )
        )

    la = component_hits / total_samples
    ta = reason_hits_total / total_samples
    efficiency = 0.0
    if path_lengths:
        apl = sum(path_lengths) / len(path_lengths)
        efficiency = math.exp(-(apl - 5.0) / 5.0)
        efficiency = min(max(efficiency, 0.0), 1.0)

    explainability = 0.0
    if total_evidence_points:
        explainability = total_evidence_hits / total_evidence_points

    final_score = 100.0 * (0.40 * la + 0.40 * ta + 0.10 * efficiency + 0.10 * explainability)

    metrics = {
        "component_accuracy": la,
        "reason_accuracy": ta,
        "efficiency": efficiency,
        "explainability": explainability,
        "final_score": final_score,
    }
    return metrics, per_sample


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate AIOps root-cause predictions")
    parser.add_argument("--ground-truth", "-g", type=Path, required=True, help="Ground-truth JSONL file")
    parser.add_argument("--submission", "-s", type=Path, required=True, help="Submission JSONL file")
    parser.add_argument(
        "--report",
        "-o",
        type=Path,
        default=None,
        help="Optional path to save a JSON report with aggregate and per-sample scores",
    )
    parser.add_argument(
        "--reason-threshold",
        type=float,
        default=0.65,
        help="Minimum similarity score (0-1) required to accept a reason when keywords miss",
    )
    parser.add_argument(
        "--show-details",
        action="store_true",
        help="Print per-sample breakdown to stdout",
    )
    return parser.parse_args(argv)


def format_percentage(value: float) -> str:
    return f"{value * 100:.2f}%"


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    ground_truth_records = load_jsonl(args.ground_truth)
    submission_records = load_jsonl(args.submission, allow_empty=True)

    gt_index = build_index(ground_truth_records)
    submission_index = build_index(submission_records)

    gt_uuids = set(gt_index.keys())
    submission_uuids = set(submission_index.keys())
    extra = sorted(submission_uuids - gt_uuids)
    missing = sorted(gt_uuids - submission_uuids)
    if extra:
        print(
            "[WARN] submission contains uuids not present in ground truth; they will be ignored:",
            ", ".join(extra),
        )
        for uuid in extra:
            submission_index.pop(uuid, None)
    if missing:
        print(
            "[WARN] submission missing uuids present in ground truth; blank predictions will be assumed:",
            ", ".join(missing),
        )
        for uuid in missing:
            submission_index[uuid] = {
                "uuid": uuid,
                "component": "",
                "reason": "",
                "reasoning_trace": [],
            }

    metrics, per_sample = score_submission(gt_index, submission_index, args.reason_threshold)

    print("===== Overall Metrics =====")
    print(f"Component Accuracy (LA): {format_percentage(metrics['component_accuracy'])}")
    print(f"Reason Accuracy (TA):    {format_percentage(metrics['reason_accuracy'])}")
    print(f"Efficiency:              {format_percentage(metrics['efficiency'])}")
    print(f"Explainability:          {format_percentage(metrics['explainability'])}")
    print(f"Final Score:             {metrics['final_score']:.2f}")

    if args.show_details:
        print("\n===== Per-sample Breakdown =====")
        header = "uuid,component_ok,reason_ok,steps,evidence_hit,evidence_total"
        print(header)
        for sample in per_sample:
            print(
                f"{sample.uuid},{sample.component_correct},{sample.reason_correct},"
                f"{sample.step_count},{sample.evidence_hit},{sample.evidence_total}"
            )

    if args.report:
        report_payload = {
            "metrics": metrics,
            "samples": [sample.__dict__ for sample in per_sample],
        }
        args.report.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
        print(f"\nReport saved to {args.report}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # pragma: no cover - CLI convenience
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
