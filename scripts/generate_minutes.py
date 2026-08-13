#!/usr/bin/env python3
"""Generate editorial HTML, clean summary PNG, and editable DOCX."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from validate_meeting_data import load_data, validate
except ModuleNotFoundError:  # Allow importing as scripts.generate_minutes in services/tests.
    from .validate_meeting_data import load_data, validate


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "assets" / "meeting-template.html"
STYLE_PATH = ROOT / "assets" / "meeting-style.css"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def text(value: object, fallback: str = "未明确") -> str:
    value = str(value or "").strip()
    return value or fallback


def safe_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", value).strip().strip(".")
    return re.sub(r"\s+", " ", value)[:80] or "会议"


def slug(index: int) -> str:
    return f"topic-{index}"


def adapt_v1(data: dict) -> dict:
    """Lossless display compatibility for existing v1 JSON."""
    if data.get("schema_version") != "1.0":
        return data
    cards = data.get("conclusion_cards", [])
    return {
        **data,
        "summary_layout": "briefing",
        "decision_path": [
            {"stage": item.get("time", f"阶段 {i}"), "title": item.get("title", ""), "description": item.get("description", "")}
            for i, item in enumerate(data.get("timeline", []), 1)
        ][:5],
        "key_decisions": data.get("decisions", []),
        "strategic_insights": [
            {"insight": card.get("title", ""), "implication": "；".join(card.get("points", [])[:2])}
            for card in cards[:2]
        ],
        "tensions": [], "risks": [],
        "topics": [
            {
                "title": item.get("title", ""), "thesis": item.get("summary", ""),
                "subsections": [{"subtitle": "关键内容", "points": [{"claim": p} for p in item.get("points", [])]}],
                "implications": [], "open_questions": item.get("open_questions", []),
            } for item in data.get("topics", [])
        ],
        "meeting_analysis": {"core_logic": [], "management_implications": [], "risks": []},
    }


def render_summary(data: dict) -> str:
    meta = [("日期", data.get("date")), ("类型", data.get("meeting_type")), ("时长", data.get("duration"))]
    meta_html = "".join(
        f'<span class="meta-item"><span class="meta-dot"></span>{esc(k)} · {esc(v)}</span>' for k, v in meta if v
    )
    tags = "".join(f'<span class="tag">{esc(v)}</span>' for v in data.get("tags", [])[:4])

    path = data.get("decision_path", [])[:5]
    path_html = ""
    if path:
        items = "".join(
            f'<div class="path-step"><div class="path-index">{esc(p.get("stage") or f"STEP {i:02d}")}</div>'
            f'<div class="path-title">{esc(p.get("title"))}</div><div class="path-desc">{esc(p.get("description"))}</div></div>'
            for i, p in enumerate(path, 1)
        )
        path_html = f'<div class="section-eyebrow">会议脉络 · DISCUSSION LOGIC</div><section class="path" style="--path-count:{len(path)}">{items}</section>'

    decisions = data.get("key_decisions", [])[:4]
    if decisions:
        decision_items = "".join(
            f'<article class="decision-item"><span class="decision-no">{i}</span><h3 class="decision-title">{esc(d.get("decision"))}</h3>'
            f'<p class="decision-rationale">依据：{esc(text(d.get("rationale")))} · <span class="owner">{esc(text(d.get("owner"), "待指定"))}</span></p></article>'
            for i, d in enumerate(decisions, 1)
        )
        core_title = "核心决策"
        decision_columns = min(len(decisions), 3)
    else:
        insights = data.get("strategic_insights", [])[:4]
        decision_items = "".join(
            f'<article class="decision-item"><span class="decision-no">{i}</span><h3 class="decision-title">{esc(v.get("insight"))}</h3>'
            f'<p class="decision-rationale">{esc(v.get("implication"))}</p></article>' for i, v in enumerate(insights, 1)
        )
        core_title = "核心结论"
        decision_columns = min(max(len(insights), 1), 3)

    actions = sorted(data.get("action_items", []), key=lambda x: {"高": 0, "中": 1, "低": 2}.get(x.get("priority", "中"), 1))[:4]
    action_html = "".join(
        f'<div class="action-item"><span class="action-owner">{esc(text(a.get("owner"), "待指定"))}</span>'
        f'<span>{esc(a.get("action"))}</span><span class="action-deadline">{esc(text(a.get("deadline")))}</span></div>' for a in actions
    ) or '<div class="action-item"><span>本次会议未形成明确行动项</span></div>'

    return f'''
<main class="summary-board" id="summary-board" data-layout="{esc(data.get('summary_layout'))}">
  <header class="masthead"><div><h1 class="meeting-title">{esc(data.get('title'))}</h1><div class="meta-list">{meta_html}</div></div><div class="tag-list">{tags}</div></header>
  <div class="section-eyebrow">会议定调 · EXECUTIVE THESIS</div>
  <section class="thesis-bar"><div class="thesis-label">会议定调</div><div class="thesis-text">{esc(data.get('executive_summary'))}</div></section>
  {path_html}
  <section class="summary-core"><div class="panel"><div class="panel-head"><span>{core_title}</span><span class="panel-note">决定了什么、为什么、由谁负责</span></div><div class="decision-list" style="--decision-cols:{decision_columns}">{decision_items}</div></div></section>
  <section class="action-strip"><div class="action-title">近期行动</div><div class="action-grid">{action_html}</div></section>
</main>'''


def render_topics(data: dict) -> str:
    blocks = []
    for index, topic in enumerate(data.get("topics", []), 1):
        subs = []
        for sub in topic.get("subsections", []):
            points = []
            for point in sub.get("points", []):
                evidence = point.get("evidence")
                source_parts = [point.get("speaker"), point.get("timestamp")]
                source = " · ".join(str(x) for x in source_parts if x)
                extra = ""
                if evidence or source:
                    extra = f'<span class="evidence">{("证据：" + esc(evidence)) if evidence else ""}{(" <span class=source>· " + esc(source) + "</span>") if source else ""}</span>'
                points.append(f'<li>{esc(point.get("claim"))}{extra}</li>')
            subs.append(f'<section class="subsection"><h4>{esc(sub.get("subtitle"))}</h4><ul class="evidence-list">{"".join(points)}</ul></section>')
        implications = "".join(f'<div class="callout implication"><strong>管理含义</strong>{esc(v)}</div>' for v in topic.get("implications", []))
        pending = "".join(f'<div class="callout pending"><strong>待确认</strong>{esc(v)}</div>' for v in topic.get("open_questions", []))
        blocks.append(
            f'<article class="topic" id="{slug(index)}"><h3>{index}. {esc(topic.get("title"))}</h3>'
            f'<p class="topic-thesis">{esc(topic.get("thesis"))}</p>{"".join(subs)}{implications}{pending}</article>'
        )
    return "".join(blocks) or '<div class="empty">原文未形成可独立拆分的议题。</div>'


def render_details(data: dict) -> str:
    toc = "".join(f'<a href="#{slug(i)}">{i}. {esc(v.get("title"))}</a>' for i, v in enumerate(data.get("topics", []), 1))
    decisions = data.get("key_decisions", [])
    decision_html = "".join(
        f'<article class="decision-card"><h3>{esc(v.get("decision"))}</h3><div class="decision-meta">依据：{esc(text(v.get("rationale")))} · 负责人：{esc(text(v.get("owner"), "待指定"))} · 证据：{esc(text(v.get("evidence")))}</div></article>'
        for v in decisions
    ) or '<div class="empty">本次会议未形成明确决策。</div>'
    analysis = data.get("meeting_analysis", {})
    analysis_defs = [("逻辑主线", analysis.get("core_logic", [])), ("管理含义", analysis.get("management_implications", [])), ("主要风险", analysis.get("risks", []))]
    analysis_html = "".join(f'<article class="analysis-card"><h3>{title}</h3><ul>{"".join(f"<li>{esc(x)}</li>" for x in values)}</ul></article>' for title, values in analysis_defs if values)
    pending = "".join(f'<div class="callout pending"><strong>待确认</strong>{esc(v)}</div>' for v in data.get("pending_items", [])) or '<div class="empty">暂无全局待确认事项。</div>'
    rows = "".join(
        f'<tr><td data-label="责任人">{esc(text(a.get("owner"), "待指定"))}</td><td data-label="行动项">{esc(a.get("action"))}</td>'
        f'<td data-label="截止日期">{esc(text(a.get("deadline")))}</td><td data-label="验收标准">{esc(text(a.get("acceptance_criteria")))}</td>'
        f'<td data-label="优先级" class="{"priority-high" if a.get("priority") == "高" else ""}">{esc(text(a.get("priority"), "中"))}</td></tr>' for a in data.get("action_items", [])
    )
    action_table = f'<div class="action-table-wrap"><table class="action-table"><thead><tr><th>责任人</th><th>行动项</th><th>截止日期</th><th>验收标准</th><th>优先级</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else '<div class="empty">本次会议未形成明确待办。</div>'
    return f'''
<article class="minutes-shell"><div class="doc-kicker">MEETING MINUTES</div><h1 class="doc-title">详细会议纪要</h1><p class="doc-lead">从会议定调到执行证据，按议题整理关键判断、分歧与行动。</p>
  <nav class="toc">{toc}<a href="#decisions">明确决策</a><a href="#analysis">会议分析</a><a href="#actions">完整待办</a></nav>
  <section class="doc-section"><h2>会议背景与目标</h2><p>{esc(text(data.get('background'), '原文未提供明确背景。'))}</p></section>
  <section class="doc-section"><h2>会议内容</h2>{render_topics(data)}</section>
  <section class="doc-section" id="decisions"><h2>明确决策</h2><div class="decision-cards">{decision_html}</div></section>
  <section class="doc-section" id="analysis"><h2>会议分析</h2><div class="analysis-grid">{analysis_html}</div></section>
  <section class="doc-section"><h2>待确认事项</h2>{pending}</section>
  <section class="doc-section" id="actions"><h2>完整待办</h2>{action_table}</section>
</article>'''


def build_html(data: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    css = STYLE_PATH.read_text(encoding="utf-8")
    return template.replace("__DOCUMENT_TITLE__", esc(f"{data['title']} - 会议纪要")).replace("__INLINE_STYLE__", css).replace("__DOCUMENT_BODY__", render_summary(data) + render_details(data))


def run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=capture, text=True)


def capture_summary(html_path: Path, png_path: Path) -> None:
    session = "meeting-minutes-pro"
    prefix = ["agent-browser", "--session", session]
    commands = [
        prefix + ["open", html_path.resolve().as_uri()],
        prefix + ["set", "viewport", "1440", "1100"],
        prefix + ["wait", "300"],
        prefix + ["eval", "document.activeElement?.blur();document.querySelectorAll('*').forEach(e=>e.style.cursor='none');document.documentElement.setAttribute('data-capture','true');true"],
        prefix + ["mouse", "move", "1438", "1098"],
        prefix + ["wait", "150"],
        # Capture only the summary board. Capture-specific CSS makes it a compact
        # landscape panel so it fits Word's first page without page content.
        prefix + ["eval", "const e=document.querySelector('#summary-board');e.scrollIntoView({block:'start'});true"],
        prefix + ["screenshot", "#summary-board", str(png_path)],
        prefix + ["close"],
    ]
    try:
        for command in commands:
            run(command)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"总结截图失败：{getattr(exc, 'stderr', '') or exc}") from exc


def office(file: Path, args: list[str]) -> None:
    try:
        run(["officecli"] + args)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"Word 生成失败：{getattr(exc, 'stderr', '') or exc}") from exc


def add_p(file: Path, value: str = "", **props) -> None:
    args = ["add", str(file), "/body", "--type", "paragraph"]
    combined = {"text": value, **props}
    for key, val in combined.items():
        if val is not None and val != "":
            args += ["--prop", f"{key}={val}"]
    office(file, args)


def build_docx(data: dict, summary_png: Path, output: Path) -> None:
    if output.exists(): output.unlink()
    office(output, ["create", str(output)])
    office(output, ["set", str(output), "/styles/Normal", "--prop", "size=10.5pt", "--prop", "font.ea=Microsoft YaHei", "--prop", "font.latin=Microsoft YaHei", "--prop", "color=343A46", "--prop", "spaceAfter=6pt", "--prop", "lineSpacing=1.2x"])
    for sid, name, size, color, before, after in (("Heading1","Heading 1","18pt","1D477B","16pt","8pt"),("Heading2","Heading 2","14pt","285A92","14pt","7pt"),("Heading3","Heading 3","11.5pt","203858","10pt","4pt")):
        office(output, ["add", str(output), "/styles", "--type", "style", "--prop", f"id={sid}", "--prop", f"name={name}", "--prop", "type=paragraph", "--prop", "basedOn=Normal", "--prop", f"size={size}", "--prop", "bold=true", "--prop", f"color={color}", "--prop", f"spaceBefore={before}", "--prop", f"spaceAfter={after}", "--prop", "keepNext=true", "--prop", "font.ea=Microsoft YaHei", "--prop", "font.latin=Microsoft YaHei"])
    # Final section is portrait; the inserted section break closes the landscape summary section.
    office(output, ["set", str(output), "/", "--prop", "pageWidth=21cm", "--prop", "pageHeight=29.7cm", "--prop", "orientation=portrait", "--prop", "marginTop=2.1cm", "--prop", "marginBottom=2.1cm", "--prop", "marginLeft=2.1cm", "--prop", "marginRight=2.1cm", "--prop", "marginHeader=1cm", "--prop", "marginFooter=1cm"])
    add_p(output, align="center", spaceAfter="0pt")
    # Keep the raster summary fully inside the A4 landscape printable area.
    office(output, ["add", str(output), "/body/p[1]", "--type", "picture", "--prop", f"path={summary_png.resolve()}", "--prop", "width=9.85in"])
    office(output, ["add", str(output), "/body", "--type", "section", "--prop", "type=nextPage", "--prop", "pageWidth=29.7cm", "--prop", "pageHeight=21cm", "--prop", "orientation=landscape", "--prop", "marginTop=1.3cm", "--prop", "marginBottom=1.3cm", "--prop", "marginLeft=1.3cm", "--prop", "marginRight=1.3cm"])
    add_p(output, "详细会议纪要", style="Heading1")
    meta = "  |  ".join([f"日期：{data.get('date','未明确')}", f"类型：{data.get('meeting_type','未明确')}", f"时长：{data.get('duration','未明确')}", "参与人：" + "、".join(data.get("participants", []))])
    add_p(output, meta, color="6F7784", size="9pt", spaceAfter="12pt")
    add_p(output, "会议定调", style="Heading2")
    add_p(output, data.get("executive_summary", ""), bold="true", fill="EDF4FF", leftIndent="0.25in", rightIndent="0.25in", spaceBefore="5pt", spaceAfter="10pt")
    add_p(output, "会议背景与目标", style="Heading2")
    add_p(output, text(data.get("background"), "原文未提供明确背景。"))
    add_p(output, "会议内容", style="Heading2")
    for index, topic in enumerate(data.get("topics", []), 1):
        add_p(output, f"{index}. {topic.get('title','')}", style="Heading3")
        add_p(output, topic.get("thesis", ""), bold="true", color="26364C", keepNext="true")
        for sub in topic.get("subsections", []):
            add_p(output, sub.get("subtitle", ""), bold="true", color="4A5565", spaceBefore="6pt", spaceAfter="3pt", keepNext="true")
            for point in sub.get("points", []):
                detail = point.get("claim", "")
                if point.get("evidence"): detail += f"（依据：{point['evidence']}）"
                add_p(output, detail, listStyle="bullet", leftIndent="0.42in", hangingIndent="0.2in", spaceAfter="4pt")
        for value in topic.get("implications", []): add_p(output, f"管理含义：{value}", fill="EEF5FF", color="2E4E78", leftIndent="0.2in", rightIndent="0.2in")
        for value in topic.get("open_questions", []): add_p(output, f"待确认：{value}", fill="FFF6E8", color="785019", leftIndent="0.2in", rightIndent="0.2in")
    add_p(output, "明确决策", style="Heading2")
    for item in data.get("key_decisions", []):
        add_p(output, item.get("decision", ""), bold="true", fill="F4F8FF", keepNext="true")
        add_p(output, f"依据：{text(item.get('rationale'))}；负责人：{text(item.get('owner'),'待指定')}；证据：{text(item.get('evidence'))}", color="6F7784", size="9pt", leftIndent="0.2in")
    add_p(output, "会议分析", style="Heading2")
    analysis = data.get("meeting_analysis", {})
    for title, values in (("逻辑主线",analysis.get("core_logic",[])),("管理含义",analysis.get("management_implications",[])),("主要风险",analysis.get("risks",[]))):
        if values:
            add_p(output, title, bold="true", color="344A68", keepNext="true")
            for value in values: add_p(output, value, listStyle="bullet", leftIndent="0.42in", hangingIndent="0.2in")
    add_p(output, "待确认事项", style="Heading2")
    for value in data.get("pending_items", []): add_p(output, value, listStyle="bullet", fill="FFF6E8", color="785019")
    # A natural page break here prevents the action table from being stranded as
    # one or two rows on a mostly empty trailing page.
    add_p(output, "完整待办", style="Heading2", pageBreakBefore="true")
    actions = data.get("action_items", [])
    if actions:
        office(output, ["add", str(output), "/body", "--type", "table", "--prop", "colWidths=1050,3000,1250,2800,850", "--prop", "layout=fixed", "--prop", "border.all=single;0.6pt;B9C4D2"])
        headers=("责任人","行动项","截止日期","验收标准","优先级")
        for i,label in enumerate(headers,1): office(output,["set",str(output),f"/body/tbl[1]/tr[1]/tc[{i}]","--prop",f"text={label}","--prop","bold=true","--prop","fill=EAF0F7","--prop","align=center","--prop","valign=center"])
        for r,item in enumerate(actions,2):
            office(output,["add",str(output),"/body/tbl[1]","--type","row"])
            vals=(text(item.get("owner"),"待指定"),text(item.get("action")),text(item.get("deadline")),text(item.get("acceptance_criteria")),text(item.get("priority"),"中"))
            for c,value in enumerate(vals,1): office(output,["set",str(output),f"/body/tbl[1]/tr[{r}]/tc[{c}]","--prop",f"text={value}","--prop",f"align={'center' if c in (1,3,5) else 'left'}","--prop","valign=center","--prop","padding=0.08in"])
    office(output, ["save", str(output)])
    office(output, ["close", str(output)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args()
    try:
        raw = load_data(args.input)
        errors, warnings = validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2
    for warning in warnings: print(f"WARNING: {warning}")
    if errors:
        for error in errors: print(f"ERROR: {error}", file=sys.stderr)
        return 1
    data = adapt_v1(raw)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build_dir = args.output_dir / ".build"; build_dir.mkdir(exist_ok=True)
    stem = safe_filename(data["title"]) + "-会议纪要"
    html_path = args.output_dir / f"{stem}.html"; png_path = build_dir / f"{stem}-总体总结.png"; docx_path = args.output_dir / f"{stem}.docx"
    html_path.write_text(build_html(data), encoding="utf-8")
    try:
        capture_summary(html_path, png_path)
        build_docx(data, png_path, docx_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 3
    print(f"HTML: {html_path.resolve()}\nDOCX: {docx_path.resolve()}\nBUILD: {png_path.resolve()}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
