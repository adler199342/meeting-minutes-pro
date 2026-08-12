---
name: meeting-minutes-pro
description: 将会议转写、录音文字稿或聊天记录编辑为决策友好的专业会议纪要，并生成自包含 HTML 与可编辑 DOCX。支持决策会、汇报会、项目推进会、培训宣讲会和复盘会；输出会议定调、讨论脉络、核心决策、分层议题、证据、管理含义、风险、待确认与可执行待办。用户要求整理会议、生成会议总结、HTML 纪要或 Word 纪要时使用。
---

# Meeting Minutes Pro

把会议原文编辑成可决策、可查证、可执行的正式纪要。禁止只把 JSON 字段排版出来。

## 固定依赖

- `python3`：运行标准库脚本。
- `agent-browser`：离线检查 HTML 并截取总结区。
- `officecli`：生成可编辑 Word。
- documents 技能的 `render_docx.py`：最终 Word 视觉验收。

## 工作流

### 1. 编辑会议内容

完整读取原文，读取 [references/meeting-data-schema.md](references/meeting-data-schema.md) 与 [references/content-rules.md](references/content-rules.md)，生成 2.0 版 `meeting-data.json`。

先识别会议类型，再按“事实—判断—管理含义—行动”提炼。保留数字、分歧、案例和约束；不得把建议升级为决策。

### 2. 校验

```bash
python3 scripts/validate_meeting_data.py meeting-data.json
```

错误必须修复。警告项需要回看原文确认，不能为了消除警告虚构内容。

### 3. 生成

读取 [references/output-layout.md](references/output-layout.md)，运行：

```bash
python3 scripts/generate_minutes.py meeting-data.json --output-dir output
```

生成自包含 HTML、无光标标记的总结 PNG 和 DOCX。HTML 与 Word 必须来自同一 JSON。

### 4. 验收

HTML：使用 agent-browser 在 1440px 与 390px 宽度检查页面，确认无横向溢出、遮挡、控制台错误或点击标记。

Word：使用 documents 技能的 `render_docx.py` 渲染全部页面，逐页检查字体、图片清晰度、分页、表格、页眉页脚与空白页。发现问题后修复并重新渲染。

### 5. 交付

只交付最终 HTML 和 DOCX，除非用户明确要求 JSON、PNG 或 QA 文件。

## 硬性质量门槛

- 顶部总结只回答“讨论主线、定调、决定、下一步”，不设置独立的关键判断侧栏，不机械复制正文；风险、分歧和管理含义放入详细纪要，不得单独堆砌数字看板。
- HTML 顶部总结与下方正文使用相同内容宽度和左右边界。
- 不默认使用时间线；使用与会议类型匹配的决策路径。
- 正文有结论、有证据、有管理含义，且保留真实分歧。
- Word 第 1 页横向总结，第 2 页起竖向可编辑正文。
- 所有关键数字、决策和待办在 HTML 与 Word 中一致。
- 最终文件不得包含占位符、自动化点击标记、工具日志或内部分析。
