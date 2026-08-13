#!/usr/bin/env python3
"""Generate editorial HTML, clean summary PNG, and editable DOCX."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

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


def choose_cjk_font() -> str:
    """Allow the service to pin its installed CJK font."""
    return os.environ.get("MEETING_DOCX_CJK_FONT", "Microsoft YaHei").strip() or "Microsoft YaHei"


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


def run(command: list[str], *, capture: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=capture, text=True, env=env)


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


def office(file: Path, args: list[str]) -> subprocess.CompletedProcess:
    try:
        return run(["officecli"] + args)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"Word 生成失败：{getattr(exc, 'stderr', '') or exc}") from exc


def add_command(commands: list[dict], command: str, *, parent: str | None = None,
                path: str | None = None, element_type: str | None = None, **props) -> None:
    item: dict = {"command": command}
    if parent is not None:
        item["parent"] = parent
    if path is not None:
        item["path"] = path
    if element_type is not None:
        item["type"] = element_type
    clean = {key: value for key, value in props.items() if value is not None and value != ""}
    if clean:
        item["props"] = clean
    commands.append(item)


def add_p(commands: list[dict], value: str = "", **props) -> None:
    add_command(commands, "add", parent="/body", element_type="paragraph", text=value, **props)


def run_office_batch(file: Path, commands: list[dict], work_dir: Path) -> None:
    """Execute all document mutations in one open/save cycle and fail loudly."""
    batch_file = work_dir / f"officecli-{uuid.uuid4().hex}.json"
    batch_file.write_text(json.dumps(commands, ensure_ascii=False), encoding="utf-8")
    env = os.environ.copy()
    # A live resident may otherwise defer disk writes for several seconds.
    env["OFFICECLI_RESIDENT_FLUSH"] = "each"
    try:
        result = run(
            ["officecli", "batch", str(file), "--input", str(batch_file), "--stop-on-error", "--json"],
            env=env,
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Word 批处理返回了无法解析的结果：{result.stdout[-500:]}") from exc
        summary = report.get("data", {}).get("summary", {})
        if not report.get("success") or summary.get("failed", 0):
            raise RuntimeError(f"Word 批处理失败：{json.dumps(report, ensure_ascii=False)[-1200:]}")
        # Batch may run through a resident process. Explicit close is the disk
        # durability barrier before a non-officecli reader inspects the DOCX.
        run(["officecli", "close", str(file), "--json"], env=env)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or str(exc)
        raise RuntimeError(f"Word 批处理失败：{detail[-1200:]}") from exc
    finally:
        batch_file.unlink(missing_ok=True)


def validate_docx(file: Path, data: dict) -> dict[str, int]:
    """Read the DOCX back from disk; an unverified file must never be published."""
    if not file.is_file() or file.stat().st_size == 0:
        raise RuntimeError("Word 自检失败：文件不存在或大小为 0")
    try:
        with zipfile.ZipFile(file) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"Word 自检失败：压缩成员损坏 {bad_member}")
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "word/document.xml"}
            if missing := required - names:
                raise RuntimeError(f"Word 自检失败：缺少 {', '.join(sorted(missing))}")
            root = ET.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = root.findall(".//w:p", ns)
            tables = root.findall(".//w:tbl", ns)
            body_text = "".join(node.text or "" for node in root.findall(".//w:t", ns))
            # officecli versions differ: some store media at word/media/*,
            # while 1.0.131 may serialize it at package-root media/*.
            media = [name for name in names if name.startswith(("word/media/", "media/"))]
    except (zipfile.BadZipFile, ET.ParseError, OSError) as exc:
        raise RuntimeError(f"Word 自检失败：无法读取 DOCX 结构：{exc}") from exc

    if len(paragraphs) < 8 or "详细会议纪要" not in body_text:
        raise RuntimeError(f"Word 自检失败：正文不完整（段落 {len(paragraphs)}）")
    # Office may serialize a picture as DrawingML or legacy VML; the embedded
    # media part is the format-independent durability check.
    if not media:
        raise RuntimeError("Word 自检失败：总结首页图片未写入")
    if data.get("action_items") and not tables:
        raise RuntimeError("Word 自检失败：存在待办数据但未写入表格")
    return {"paragraphs": len(paragraphs), "tables": len(tables), "images": len(media)}


def build_docx_once(data: dict, summary_png: Path, output: Path, work_dir: Path) -> dict[str, int]:
    output.unlink(missing_ok=True)
    office(output, ["create", str(output)])
    commands: list[dict] = []
    cjk_font = choose_cjk_font()
    add_command(commands, "set", path="/styles/Normal", size="10.5pt", **{"font.ea": cjk_font, "font.latin": "Arial"}, color="343A46", spaceAfter="6pt", lineSpacing="1.2x")
    for sid, name, size, color, before, after in (("Heading1","Heading 1","18pt","1D477B","16pt","8pt"),("Heading2","Heading 2","14pt","285A92","14pt","7pt"),("Heading3","Heading 3","11.5pt","203858","10pt","4pt")):
        add_command(commands, "add", parent="/styles", element_type="style", id=sid, name=name, type="paragraph", basedOn="Normal", size=size, bold="true", color=color, spaceBefore=before, spaceAfter=after, keepNext="true", **{"font.ea": cjk_font, "font.latin": "Arial"})
    # Final section is portrait; the inserted section break closes the landscape summary section.
    add_command(commands, "set", path="/", pageWidth="21cm", pageHeight="29.7cm", orientation="portrait", marginTop="2.1cm", marginBottom="2.1cm", marginLeft="2.1cm", marginRight="2.1cm", marginHeader="1cm", marginFooter="1cm")
    add_p(commands, align="center", spaceAfter="0pt")
    # Keep the raster summary fully inside the A4 landscape printable area.
    add_command(commands, "add", parent="/body/p[1]", element_type="picture", src=str(summary_png.resolve()), width="9.85in")
    add_command(commands, "add", parent="/body", element_type="section", type="nextPage", pageWidth="29.7cm", pageHeight="21cm", orientation="landscape", marginTop="1.3cm", marginBottom="1.3cm", marginLeft="1.3cm", marginRight="1.3cm")
    add_p(commands, "详细会议纪要", style="Heading1")
    meta = "  |  ".join([f"日期：{data.get('date','未明确')}", f"类型：{data.get('meeting_type','未明确')}", f"时长：{data.get('duration','未明确')}", "参与人：" + "、".join(data.get("participants", []))])
    add_p(commands, meta, color="6F7784", size="9pt", spaceAfter="12pt")
    add_p(commands, "会议定调", style="Heading2")
    add_p(commands, data.get("executive_summary", ""), bold="true", fill="EDF4FF", leftIndent="0.25in", rightIndent="0.25in", spaceBefore="5pt", spaceAfter="10pt")
    add_p(commands, "会议背景与目标", style="Heading2")
    add_p(commands, text(data.get("background"), "原文未提供明确背景。"))
    add_p(commands, "会议内容", style="Heading2")
    for index, topic in enumerate(data.get("topics", []), 1):
        add_p(commands, f"{index}. {topic.get('title','')}", style="Heading3")
        add_p(commands, topic.get("thesis", ""), bold="true", color="26364C", keepNext="true")
        for sub in topic.get("subsections", []):
            add_p(commands, sub.get("subtitle", ""), bold="true", color="4A5565", spaceBefore="6pt", spaceAfter="3pt", keepNext="true")
            for point in sub.get("points", []):
                detail = point.get("claim", "")
                if point.get("evidence"): detail += f"（依据：{point['evidence']}）"
                add_p(commands, detail, listStyle="bullet", leftIndent="0.42in", hangingIndent="0.2in", spaceAfter="4pt")
        for value in topic.get("implications", []): add_p(commands, f"管理含义：{value}", fill="EEF5FF", color="2E4E78", leftIndent="0.2in", rightIndent="0.2in")
        for value in topic.get("open_questions", []): add_p(commands, f"待确认：{value}", fill="FFF6E8", color="785019", leftIndent="0.2in", rightIndent="0.2in")
    add_p(commands, "明确决策", style="Heading2")
    for item in data.get("key_decisions", []):
        add_p(commands, item.get("decision", ""), bold="true", fill="F4F8FF", keepNext="true")
        add_p(commands, f"依据：{text(item.get('rationale'))}；负责人：{text(item.get('owner'),'待指定')}；证据：{text(item.get('evidence'))}", color="6F7784", size="9pt", leftIndent="0.2in")
    add_p(commands, "会议分析", style="Heading2")
    analysis = data.get("meeting_analysis", {})
    for title, values in (("逻辑主线",analysis.get("core_logic",[])),("管理含义",analysis.get("management_implications",[])),("主要风险",analysis.get("risks",[]))):
        if values:
            add_p(commands, title, bold="true", color="344A68", keepNext="true")
            for value in values: add_p(commands, value, listStyle="bullet", leftIndent="0.42in", hangingIndent="0.2in")
    add_p(commands, "待确认事项", style="Heading2")
    for value in data.get("pending_items", []): add_p(commands, value, listStyle="bullet", fill="FFF6E8", color="785019")
    # A natural page break here prevents the action table from being stranded as
    # one or two rows on a mostly empty trailing page.
    add_p(commands, "完整待办", style="Heading2", pageBreakBefore="true")
    actions = data.get("action_items", [])
    if actions:
        add_command(commands, "add", parent="/body", element_type="table", colWidths="1050,3000,1250,2800,850", layout="fixed", **{"border.all": "single;0.6pt;B9C4D2"})
        headers=("责任人","行动项","截止日期","验收标准","优先级")
        for i,label in enumerate(headers,1): add_command(commands, "set", path=f"/body/tbl[1]/tr[1]/tc[{i}]", text=label, bold="true", fill="EAF0F7", align="center", valign="center")
        for r,item in enumerate(actions,2):
            add_command(commands, "add", parent="/body/tbl[1]", element_type="row")
            vals=(text(item.get("owner"),"待指定"),text(item.get("action")),text(item.get("deadline")),text(item.get("acceptance_criteria")),text(item.get("priority"),"中"))
            for c,value in enumerate(vals,1): add_command(commands, "set", path=f"/body/tbl[1]/tr[{r}]/tc[{c}]", text=value, align="center" if c in (1,3,5) else "left", valign="center", padding="0.08in")
    run_office_batch(output, commands, work_dir)
    return validate_docx(output, data)


def build_docx(data: dict, summary_png: Path, output: Path, *, attempts: int = 2) -> dict[str, int]:
    """Build in an isolated file, validate, then atomically publish the result."""
    output.parent.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        temp_output = output.parent / f".{output.stem}.{uuid.uuid4().hex}.tmp.docx"
        try:
            stats = build_docx_once(data, summary_png, temp_output, output.parent)
            os.replace(temp_output, output)
            return stats
        except Exception as exc:
            failures.append(f"第 {attempt} 次：{exc}")
            temp_output.unlink(missing_ok=True)
            if attempt < attempts:
                print(f"WARNING: Word 生成失败，准备重试：{exc}", file=sys.stderr)
    output.unlink(missing_ok=True)
    raise RuntimeError("Word 生成在重试后仍未通过自检：" + "；".join(failures))


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
        stats = build_docx(data, png_path, docx_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 3
    print(f"HTML: {html_path.resolve()}\nDOCX: {docx_path.resolve()}\nBUILD: {png_path.resolve()}")
    print(f"VERIFY: paragraphs={stats['paragraphs']} tables={stats['tables']} images={stats['images']}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
