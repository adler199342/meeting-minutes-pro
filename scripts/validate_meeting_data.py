#!/usr/bin/env python3
"""Validate meeting-minutes-pro canonical JSON (v2 with v1 compatibility)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


LAYOUTS = {"decision", "report", "progress", "briefing", "review"}
PRIORITIES = {"高", "中", "低"}


def load_data(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("根节点必须是 JSON 对象")
    return data


def _list(data: dict, key: str, errors: list[str]) -> list:
    value = data.get(key, [])
    if not isinstance(value, list):
        errors.append(f"{key}: 必须是数组")
        return []
    return value


def validate(data: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    version = data.get("schema_version")
    if version not in {"1.0", "2.0"}:
        errors.append("schema_version: 只支持 1.0 或 2.0")
    for key in ("title", "executive_summary"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key}: 必须是非空字符串")
    if len(str(data.get("executive_summary", ""))) > 110:
        warnings.append("executive_summary: 超过 110 字，顶部定调可能过长")

    for key in ("participants", "tags", "topics", "action_items", "pending_items"):
        _list(data, key, errors)

    if version == "1.0":
        warnings.append("schema_version: 1.0 仅兼容输出，建议升级为 2.0")
        return errors, warnings

    layout = data.get("summary_layout")
    if layout not in LAYOUTS:
        errors.append(f"summary_layout: 必须是 {sorted(LAYOUTS)} 之一")

    limits = {
        "decision_path": 5, "key_decisions": 4,
        "strategic_insights": 3, "tensions": 2, "risks": 3,
        "topics": 7, "action_items": 8,
    }
    for key, maximum in limits.items():
        value = _list(data, key, errors)
        if len(value) > maximum:
            errors.append(f"{key}: 数量 {len(value)} 超过上限 {maximum}")

    for index, item in enumerate(data.get("decision_path", [])):
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            errors.append(f"decision_path[{index}]: 必须包含 title")

    for index, item in enumerate(data.get("key_decisions", [])):
        if not isinstance(item, dict) or not str(item.get("decision", "")).strip():
            errors.append(f"key_decisions[{index}]: 必须包含 decision")
        elif not str(item.get("evidence", "")).strip():
            warnings.append(f"key_decisions[{index}].evidence: 建议保留时间戳或原文依据")

    for index, topic in enumerate(data.get("topics", [])):
        if not isinstance(topic, dict) or not str(topic.get("title", "")).strip() or not str(topic.get("thesis", "")).strip():
            errors.append(f"topics[{index}]: 必须包含 title 和 thesis")
            continue
        subsections = topic.get("subsections", [])
        if not isinstance(subsections, list) or not subsections:
            errors.append(f"topics[{index}].subsections: 必须是非空数组")
            continue
        for sub_index, subsection in enumerate(subsections):
            points = subsection.get("points", []) if isinstance(subsection, dict) else []
            if not isinstance(points, list) or not points:
                errors.append(f"topics[{index}].subsections[{sub_index}].points: 必须是非空数组")
            for point_index, point in enumerate(points):
                if not isinstance(point, dict) or not str(point.get("claim", "")).strip():
                    errors.append(f"topics[{index}].subsections[{sub_index}].points[{point_index}]: 必须包含 claim")

    analysis = data.get("meeting_analysis", {})
    if not isinstance(analysis, dict):
        errors.append("meeting_analysis: 必须是对象")
    elif not analysis.get("core_logic"):
        warnings.append("meeting_analysis.core_logic: 为空，正文将缺少综合分析")

    for index, item in enumerate(data.get("action_items", [])):
        if not isinstance(item, dict) or not str(item.get("action", "")).strip():
            errors.append(f"action_items[{index}]: 必须包含 action")
            continue
        if not str(item.get("owner", "")).strip():
            warnings.append(f"action_items[{index}].owner: 建议写“待指定”")
        if item.get("priority", "中") not in PRIORITIES:
            errors.append(f"action_items[{index}].priority: 只允许高、中、低")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        data = load_data(args.input)
        errors, warnings = validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}", file=sys.stderr)
    if errors:
        print(f"校验失败：{len(errors)} 个错误，{len(warnings)} 个警告", file=sys.stderr)
        return 1
    print(f"校验通过：0 个错误，{len(warnings)} 个警告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
