# 会议数据结构 2.0

所有输出共用一份 UTF-8 JSON。结构区分事实、判断、决策、风险与行动，避免把不同性质的信息塞入相同卡片。

```json
{
  "schema_version": "2.0",
  "title": "会议标题",
  "date": "YYYY-MM-DD",
  "meeting_type": "决策会｜汇报会｜项目推进会｜培训宣讲会｜复盘会｜交流会",
  "duration": "55分钟",
  "participants": ["姓名/角色"],
  "tags": ["标签"],
  "executive_summary": "会议最终定调或最重要结论",
  "summary_layout": "decision｜report｜progress｜briefing｜review",
  "decision_path": [
    {"stage": "现状", "title": "已有基础", "description": "一句话"}
  ],
  "key_decisions": [
    {"decision": "明确决定", "rationale": "依据", "owner": "负责方", "evidence": "时间戳或原文依据"}
  ],
  "strategic_insights": [
    {"insight": "归纳判断", "implication": "对管理或执行意味着什么"}
  ],
  "tensions": [
    {"topic": "分歧主题", "side_a": "观点A", "side_b": "观点B", "resolution": "结论或待确认"}
  ],
  "risks": [
    {"risk": "风险", "impact": "影响", "response": "应对或未明确"}
  ],
  "background": "背景与目标",
  "topics": [
    {
      "title": "议题",
      "thesis": "本议题结论",
      "subsections": [
        {
          "subtitle": "子议题",
          "points": [
            {"claim": "信息或判断", "evidence": "事实/数字/案例", "speaker": "发言人", "timestamp": "00:00"}
          ]
        }
      ],
      "implications": ["管理含义"],
      "open_questions": ["待确认问题"]
    }
  ],
  "meeting_analysis": {
    "core_logic": ["会议逻辑链"],
    "management_implications": ["管理含义"],
    "risks": ["综合风险"]
  },
  "action_items": [
    {
      "owner": "责任人或待指定",
      "action": "具体动作",
      "deadline": "期限或未明确",
      "acceptance_criteria": "验收标准或未明确",
      "priority": "高｜中｜低"
    }
  ],
  "pending_items": ["全局待确认事项"]
}
```

## 数量与篇幅

- `decision_path`：3–5 步；表达逻辑推进，不要求绑定时间。
- `key_decisions`：1–4 条；没有明确决定时允许为空。
- `strategic_insights`：1–3 条；必须同时写出管理含义。
- `tensions`：0–2 条；只记录真实分歧或取舍。
- `risks`：0–3 条。
- `topics`：3–7 个；每个议题 1–3 个子议题。
- 每个子议题 1–4 个 point；`claim` 必填，其他证据字段按原文填写。
- `action_items`：1–8 条。

## 兼容规则

生成器仍可读取 1.0 数据，但只作为兼容降级。正式生成前优先升级为 2.0；不得继续创建 `conclusion_cards`。
