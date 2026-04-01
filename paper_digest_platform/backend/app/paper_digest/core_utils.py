import argparse
import dataclasses
import datetime as dt
import html
import io
import json
import math
import os
import re
import ssl
import smtplib
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.header import Header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Iterable, Optional

import requests

"""
Paper Digest Agent（平台执行核心）
--------------------------------

该脚本用于执行一次完整的论文检索与邮件推送流程，主要职责：

1. 读取运行配置（搜索源、LLM、邮件、状态参数）
2. 基于关键词检索论文并合并去重
3. 执行可选的相关性过滤、偏好重排、中文摘要
4. 生成日报/周报邮件并发送
5. 维护去重与历史状态（支持文件状态与外部状态两种模式）

在当前后端平台中的推荐调用方式：
- 通过 `run_once(...)` 调用
- 使用 `keywords_override` 注入前端关键词（优先于配置文件）
- 使用 `state_override` 注入数据库状态
- 配合 `persist_state_to_file=False` 禁止写回 JSON 状态文件
"""


LLM_IMPORT_ERROR = ""


def _try_import_llm_client():
    """尽力导入 `llm_tools.LLMClient`，失败时返回 `None` 并记录原因。"""
    global LLM_IMPORT_ERROR

    errors: list[str] = []

    # 1) 优先按当前 Python 路径直接导入
    try:
        from llm_tools import LLMClient as _LLMClient  # type: ignore

        LLM_IMPORT_ERROR = ""
        return _LLMClient
    except Exception as exc:
        errors.append(f"direct import failed: {exc}")

    # 2) 兼容常见目录布局，按候选目录补充 sys.path 后再尝试导入
    base_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.abspath(os.path.join(base_dir, "..", ".."))
    project_root = os.path.abspath(os.path.join(base_dir, "..", "..", ".."))
    candidates = [
        os.path.join(backend_dir, "yangjie-llm-paper-search"),
        os.path.join(project_root, "yangjie-llm-paper-search"),
        project_root,
    ]

    seen: set[str] = set()
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if candidate in seen:
            continue
        seen.add(candidate)
        if not os.path.isfile(os.path.join(candidate, "llm_tools.py")):
            continue

        if candidate not in sys.path:
            sys.path.insert(0, candidate)

        try:
            from llm_tools import LLMClient as _LLMClient  # type: ignore

            LLM_IMPORT_ERROR = ""
            return _LLMClient
        except Exception as exc:
            errors.append(f"import from '{candidate}' failed: {exc}")

    LLM_IMPORT_ERROR = " | ".join(errors)
    return None


LLMClient = _try_import_llm_client()
USER_AGENT = "paper-digest-agent/0.1"


@dataclass(frozen=True)
class Paper:
    source: str
    title: str
    url: str
    venue: str
    published_date: Optional[dt.date]
    authors: list[str]
    abstract: str
    publisher: str
    doi: str
    arxiv_id: str
    pdf_url: str
    keywords: list[str]


_SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "arxiv": "arXiv",
    "crossref": "Crossref",
    "pubmed": "PubMed",
    "ieee": "IEEE Xplore",
    "semantic_scholar": "Semantic Scholar",
}

_WEEKDAY_LABELS: dict[int, str] = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}

_WEEKLY_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("血压监测", ("blood pressure", "hypertension", "cuffless", "ppg", "hemodynamic")),
    ("葡萄糖监测", ("glucose", "glycemic", "glycaemic", "sweat glucose")),
    ("可穿戴形态", ("wearable", "patch", "epidermal", "textile", "on-skin", "wrist")),
    (
        "柔性/电子器件",
        ("flexible", "stretchable", "electronics", "electrode", "hardware", "device"),
    ),
    (
        "传感机制",
        (
            "sensor",
            "biosensor",
            "electrochemical",
            "photoplethysmography",
            "transducer",
        ),
    ),
)


def _configure_stdio() -> None:
    # Windows consoles often use GBK; replace unsupported chars instead of crashing.
    """
    功能说明：
        执行 `_configure_stdio` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - 无。
    返回值：
        返回类型为 `None`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            continue


def _today_local() -> dt.date:
    """
    功能说明：
        执行 `_today_local` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - 无。
    返回值：
        返回类型为 `dt.date`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    return dt.datetime.now().date()


def _parse_date(s: str) -> Optional[dt.date]:
    """
    功能说明：
        解析输入内容并转换为结构化结果，供后续逻辑安全使用。
    参数说明：
        - s: 业务输入参数。
    返回值：
        返回类型为 `Optional[dt.date]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not s:
        return None
    try:
        # arXiv: 2026-02-27T00:00:00Z
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _parse_date_fuzzy(s: str) -> Optional[dt.date]:
    """
    功能说明：
        解析输入内容并转换为结构化结果，供后续逻辑安全使用。
    参数说明：
        - s: 业务输入参数。
    返回值：
        返回类型为 `Optional[dt.date]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    raw = (s or "").strip()
    if not raw:
        return None

    parsed = _parse_date(raw)
    if parsed:
        return parsed

    norm = re.sub(r"\s+", " ", raw.replace(",", " ")).strip()
    norm = re.sub(r"[.;]+$", "", norm)

    # Try common publication date formats from PubMed / IEEE.
    fmts = (
        "%Y %b %d",
        "%Y %B %d",
        "%d %b %Y",
        "%d %B %Y",
        "%Y/%m/%d",
        "%Y %b",
        "%Y %B",
        "%b %Y",
        "%B %Y",
        "%Y",
    )
    for fmt in fmts:
        try:
            d = dt.datetime.strptime(norm, fmt).date()
            if fmt in ("%Y %b", "%Y %B", "%b %Y", "%B %Y", "%Y"):
                return dt.date(d.year, d.month if d.month else 1, 1)
            return d
        except Exception:
            continue

    # Fallback: find a year-month-day like pattern inside noisy strings.
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", norm)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    m = re.search(r"(\d{4})", norm)
    if m:
        try:
            return dt.date(int(m.group(1)), 1, 1)
        except Exception:
            pass
    return None


def _pubmed_pick_date(item: dict[str, Any]) -> Optional[dt.date]:
    # Prefer explicit publication text over sortpubdate, because sortpubdate is
    # often normalized to the first day of month in PubMed eSummary.
    """
    功能说明：
        执行 `_pubmed_pick_date` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - item: 业务输入参数。
    返回值：
        返回类型为 `Optional[dt.date]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    raw_candidates = [
        str(item.get("epubdate") or "").strip(),
        str(item.get("pubdate") or "").strip(),
        str(item.get("sortpubdate") or "").strip(),
    ]
    for raw in raw_candidates:
        if not raw:
            continue
        picked = _parse_date_fuzzy(raw)
        if picked:
            return picked
    return None


def _safe_join(parts: Iterable[str], sep: str = ", ") -> str:
    """
    功能说明：
        执行安全处理逻辑，尽量避免异常向上冒泡影响主流程。
    参数说明：
        - parts: 业务输入参数。
        - sep: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    return sep.join([p for p in parts if p])


def _unique_clean_list(values: Iterable[Any]) -> list[str]:
    """
    功能说明：
        执行 `_unique_clean_list` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - values: 业务输入参数。
    返回值：
        返回类型为 `list[str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _source_display_name(source: str) -> str:
    """
    功能说明：
        执行 `_source_display_name` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - source: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    key = (source or "").strip().lower()
    if not key:
        return ""
    return _SOURCE_DISPLAY_NAMES.get(key, source)


def _source_breakdown(papers: list[Paper]) -> str:
    """
    功能说明：
        执行 `_source_breakdown` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - papers: 待处理的数据集合。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not papers:
        return "none"
    counts: dict[str, int] = {}
    for p in papers:
        key = (p.source or "").strip().lower() or "unknown"
        counts[key] = counts.get(key, 0) + 1

    preferred_order = (
        "pubmed",
        "crossref",
        "arxiv",
        "ieee",
        "semantic_scholar",
        "unknown",
    )
    parts: list[str] = []
    emitted: set[str] = set()
    for key in preferred_order:
        if key in counts:
            parts.append(f"{_source_display_name(key) or key}={counts[key]}")
            emitted.add(key)
    for key in sorted(counts.keys()):
        if key not in emitted:
            parts.append(f"{_source_display_name(key) or key}={counts[key]}")
    return ", ".join(parts)


def _truncate_text(text: str, max_len: int) -> str:
    """
    功能说明：
        执行 `_truncate_text` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - text: 业务输入参数。
        - max_len: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return ""
    if len(clean) <= max_len:
        return clean
    clipped = clean[:max_len]
    last_space = clipped.rfind(" ")
    if last_space >= int(max_len * 0.65):
        clipped = clipped[:last_space]
    return clipped.rstrip(" ,.;:") + "..."


def _paper_intro(paper: Paper, summary: dict[str, str], max_len: int = 420) -> str:
    """
    功能说明：
        执行 `_paper_intro` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
        - summary: 业务输入参数。
        - max_len: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if paper.abstract:
        return _truncate_text(paper.abstract, max_len=max_len)
    if summary:
        merged = _safe_join([v for _, v in _ordered_summary_items(summary)], sep=" ")
        if merged:
            return _truncate_text(merged, max_len=max_len)
    return ""


def _ordered_summary_items(summary: dict[str, str]) -> list[tuple[str, str]]:
    """
    功能说明：
        执行 `_ordered_summary_items` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `list[tuple[str, str]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not summary:
        return []
    items: list[tuple[str, str]] = []
    emitted: set[str] = set()
    for key in SUMMARY_RENDER_ORDER:
        value = (summary.get(key) or "").strip()
        if value:
            items.append((key, value))
            emitted.add(key)
    for key, value in summary.items():
        clean = (value or "").strip()
        if key not in emitted and clean:
            items.append((key, clean))
    return items


def _html_badge(text: str, *, bg: str, fg: str, border: str = "") -> str:
    """
    功能说明：
        执行 `_html_badge` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - text: 业务输入参数。
        - bg: 业务输入参数。
        - fg: 业务输入参数。
        - border: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    clean = html.escape((text or "").strip())
    if not clean:
        return ""
    border_css = (
        f"border:1px solid {border};" if border else "border:1px solid transparent;"
    )
    return (
        '<span style="display:inline-block;margin:0 8px 8px 0;padding:6px 10px;'
        f"border-radius:999px;background:{bg};color:{fg};{border_css}"
        'font-size:12px;font-weight:700;line-height:1.2;">'
        f"{clean}</span>"
    )


def _render_keyword_badges_html(keywords: list[str]) -> str:
    """
    功能说明：
        渲染 keyword badges html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - keywords: 关键词或关键词集合。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not keywords:
        return ""
    badges = [
        _html_badge(kw, bg="#eff6ff", fg="#1d4ed8", border="#bfdbfe")
        for kw in keywords
        if kw and kw.strip()
    ]
    badges = [b for b in badges if b]
    if not badges:
        return ""
    return (
        '<div style="margin:10px 0 4px;">'
        '<div style="font-size:12px;font-weight:800;color:#475569;'
        'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px;">关键词命中</div>'
        + "".join(badges)
        + "</div>"
    )


def _render_meta_badges_html(paper: Paper) -> str:
    """
    功能说明：
        渲染 meta badges html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - paper: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    badges: list[str] = []
    source_name = _source_display_name(paper.source)
    if source_name:
        badges.append(
            _html_badge(source_name, bg="#dcfce7", fg="#166534", border="#86efac")
        )
    if paper.published_date:
        badges.append(
            _html_badge(
                f"发表 {paper.published_date.isoformat()}",
                bg="#fef3c7",
                fg="#92400e",
                border="#fde68a",
            )
        )
    if paper.venue:
        badges.append(
            _html_badge(paper.venue, bg="#f1f5f9", fg="#334155", border="#cbd5e1")
        )
    return "".join(badges)


def _summary_block_palette(label: str) -> tuple[str, str, str]:
    """
    功能说明：
        执行 `_summary_block_palette` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - label: 业务输入参数。
    返回值：
        返回类型为 `tuple[str, str, str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    palettes = {
        "一句话看点": ("#fff7ed", "#f59e0b", "#9a3412"),
        "编辑判断": ("#ecfeff", "#0891b2", "#164e63"),
        "科学问题": ("#eff6ff", "#3b82f6", "#1e3a8a"),
        "关键问题": ("#eff6ff", "#3b82f6", "#1e3a8a"),
        "核心思路": ("#eef2ff", "#6366f1", "#3730a3"),
        "方法设计": ("#ecfdf5", "#10b981", "#065f46"),
        "关键结果": ("#f5f3ff", "#8b5cf6", "#5b21b6"),
        "可借鉴之处": ("#fdf2f8", "#ec4899", "#9d174d"),
        "局限与边界": ("#fef2f2", "#ef4444", "#991b1b"),
        "为什么值得看": ("#eff6ff", "#3b82f6", "#1e3a8a"),
        "核心方法": ("#ecfdf5", "#10b981", "#065f46"),
        "结果亮点": ("#f5f3ff", "#8b5cf6", "#5b21b6"),
        "对你有什么启发": ("#fdf2f8", "#ec4899", "#9d174d"),
        "背景": ("#f8fafc", "#64748b", "#334155"),
        "动机": ("#f8fafc", "#64748b", "#334155"),
        "方法": ("#f8fafc", "#64748b", "#334155"),
        "结果": ("#f8fafc", "#64748b", "#334155"),
    }
    return palettes.get(label, ("#f8fafc", "#94a3b8", "#334155"))


def _derive_editorial_judgment(summary: dict[str, str]) -> str:
    """
    功能说明：
        执行 `_derive_editorial_judgment` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    explicit = (summary.get("编辑判断") or "").strip()
    if explicit:
        return explicit
    borrow = (
        summary.get("可借鉴之处")
        or summary.get("可借鉴点")
        or summary.get("对你有什么启发")
        or ""
    ).strip()
    risks = (summary.get("局限与边界") or summary.get("风险边界") or "").strip()
    hard_result = (
        summary.get("关键结果")
        or summary.get("最硬结果")
        or summary.get("结果亮点")
        or ""
    ).strip()
    hook = (summary.get("一句话看点") or "").strip()

    if borrow and not risks:
        return "强推荐"
    if hard_result and risks:
        return "结果硬但迁移有限"
    if borrow:
        return "方法值得借鉴"
    if hook:
        return "选题可参考"
    return ""


def _editorial_badge_palette(label: str) -> tuple[str, str, str]:
    """
    功能说明：
        执行 `_editorial_badge_palette` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - label: 业务输入参数。
    返回值：
        返回类型为 `tuple[str, str, str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    palettes = {
        "强推荐": ("#dcfce7", "#166534", "#86efac"),
        "方法值得借鉴": ("#e0e7ff", "#3730a3", "#a5b4fc"),
        "结果硬但迁移有限": ("#fef3c7", "#92400e", "#fcd34d"),
        "选题可参考": ("#e0f2fe", "#075985", "#7dd3fc"),
        "谨慎参考": ("#fee2e2", "#991b1b", "#fca5a5"),
    }
    return palettes.get(label, ("#f1f5f9", "#334155", "#cbd5e1"))


def _editorial_star_count(label: str) -> int:
    """
    功能说明：
        执行 `_editorial_star_count` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - label: 业务输入参数。
    返回值：
        返回类型为 `int`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    mapping = {
        "强推荐": 5,
        "方法值得借鉴": 4,
        "结果硬但迁移有限": 3,
        "选题可参考": 2,
        "谨慎参考": 1,
    }
    return mapping.get((label or "").strip(), 0)


def _editorial_star_text(label: str) -> str:
    """
    功能说明：
        执行 `_editorial_star_text` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - label: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    count = _editorial_star_count(label)
    if count <= 0:
        return ""
    return ("★" * count) + ("☆" * (5 - count))


def _render_editorial_rating_html(summary: dict[str, str]) -> str:
    """
    功能说明：
        渲染 editorial rating html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    label = _derive_editorial_judgment(summary)
    stars = _editorial_star_text(label)
    if not stars:
        return ""
    bg, fg, border = _editorial_badge_palette(label)
    filled = html.escape("★" * _editorial_star_count(label))
    empty = html.escape("☆" * (5 - _editorial_star_count(label)))
    return (
        '<div style="display:inline-block;padding:8px 12px;border-radius:999px;'
        f'background:{bg};border:1px solid {border};">'
        f'<span style="font-size:18px;letter-spacing:0.08em;color:#f59e0b;font-weight:900;">{filled}</span>'
        f'<span style="font-size:18px;letter-spacing:0.08em;color:#cbd5e1;font-weight:900;">{empty}</span>'
        "</div>"
    )


_METRIC_HIGHLIGHT_PATTERN = re.compile(
    r"("
    r"(?:[<>≤≥≈~]?\s*\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?\s*(?:mmHg|%|ms|s|mW|Hz|KB|MB|g|mg|kg|cmH\?O|cmH2O|次|例|人|名|样本|组|帧|秒|分钟|小时|天|周|月|年))"
    r"|(?:n\s*=\s*\d+(?:\.\d+)?)"
    r"|(?:[Rrρ]\s*[²2]?\s*=\s*\d+(?:\.\d+)?)"
    r"|(?:AAMI(?:/ISO)?|BHS|IEEE\s*1708|ISO\s*\d+(?:-\d+)*(?::\d+)?|SP10|Grade\s*[A-C]|Class\s*[A-C])"
    r")"
)


_EMPHASIS_MARK_PATTERN = re.compile(r"【([^【】]{1,80})】")


def _render_metric_pills_html(text: str) -> str:
    """
    功能说明：
        渲染 metric pills html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - text: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    parts: list[str] = []
    last = 0
    for m in _METRIC_HIGHLIGHT_PATTERN.finditer(text):
        start, end = m.span()
        if start > last:
            parts.append(html.escape(text[last:start]))
        token = html.escape(m.group(0).strip())
        parts.append(
            '<span style="display:inline-block;padding:1px 7px;margin:0 2px;border-radius:999px;'
            'background:#ede9fe;color:#5b21b6;border:1px solid #c4b5fd;font-weight:900;">'
            + token
            + "</span>"
        )
        last = end
    if last < len(text):
        parts.append(html.escape(text[last:]))
    return "".join(parts) if parts else html.escape(text)


def _render_highlighted_text_html(
    text: str,
    *,
    fg: str,
    accent: str,
    emphasize_metrics: bool = False,
) -> str:
    """
    功能说明：
        渲染 highlighted text html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - text: 业务输入参数。
        - fg: 业务输入参数。
        - accent: 业务输入参数。
        - emphasize_metrics: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    clean = (text or "").strip()
    if not clean:
        return ""
    parts: list[str] = []
    last = 0
    for m in _EMPHASIS_MARK_PATTERN.finditer(clean):
        start, end = m.span()
        if start > last:
            plain = clean[last:start]
            parts.append(
                _render_metric_pills_html(plain)
                if emphasize_metrics
                else html.escape(plain)
            )
        raw_token = m.group(1).strip()
        token = html.escape(raw_token)
        if emphasize_metrics and _METRIC_HIGHLIGHT_PATTERN.fullmatch(raw_token):
            parts.append(
                '<span style="display:inline-block;padding:1px 7px;margin:0 2px;border-radius:999px;'
                'background:#ede9fe;color:#5b21b6;border:1px solid #c4b5fd;font-weight:900;">'
                + token
                + "</span>"
            )
        else:
            parts.append(
                f'<strong style="font-weight:900;color:{fg};padding:0 1px;border-bottom:2px solid {accent};">'
                + token
                + "</strong>"
            )
        last = end
    if last < len(clean):
        tail = clean[last:]
        parts.append(
            _render_metric_pills_html(tail) if emphasize_metrics else html.escape(tail)
        )
    return "".join(parts) if parts else html.escape(clean)


def _summary_value(summary: dict[str, str], *keys: str) -> str:
    """
    功能说明：
        执行 `_summary_value` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - summary: 业务输入参数。
        - *keys: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    for key in keys:
        value = (summary.get(key) or "").strip()
        if value:
            return value
    return ""


def _render_magazine_card_box_html(
    label: str,
    value: str,
    *,
    bg: str,
    accent: str,
    fg: str,
    emphasize_metrics: bool = False,
    font_size: str = "15px",
    stretch: bool = False,
) -> str:
    """
    功能说明：
        渲染 magazine card box html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - label: 业务输入参数。
        - value: 业务输入参数。
        - bg: 业务输入参数。
        - accent: 业务输入参数。
        - fg: 业务输入参数。
        - emphasize_metrics: 业务输入参数。
        - font_size: 业务输入参数。
        - stretch: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    clean = (value or "").strip()
    if not clean:
        return ""
    body_html = _render_highlighted_text_html(
        clean,
        fg=fg,
        accent=accent,
        emphasize_metrics=emphasize_metrics,
    )
    stretch_css = "height:100%;" if stretch else ""
    return (
        f'<div style="{stretch_css}padding:16px 18px;border-radius:18px;'
        f"background:{bg};border:1px solid rgba(15,23,42,0.06);border-left:5px solid {accent};"
        'box-shadow:0 8px 20px rgba(15,23,42,0.04);box-sizing:border-box;">'
        f'<div style="font-size:13px;font-weight:900;letter-spacing:0.04em;color:{accent};">{html.escape(label)}</div>'
        f'<div style="margin-top:10px;font-size:{font_size};line-height:1.78;color:{fg};">{body_html}</div>'
        "</div>"
    )


def _render_magazine_card_html(
    label: str,
    value: str,
    *,
    bg: str,
    accent: str,
    fg: str,
    emphasize_metrics: bool = False,
    margin_top: int = 14,
    font_size: str = "15px",
) -> str:
    """
    功能说明：
        渲染 magazine card html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - label: 业务输入参数。
        - value: 业务输入参数。
        - bg: 业务输入参数。
        - accent: 业务输入参数。
        - fg: 业务输入参数。
        - emphasize_metrics: 业务输入参数。
        - margin_top: 业务输入参数。
        - font_size: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    return (
        f'<div style="margin-top:{margin_top}px;">'
        + _render_magazine_card_box_html(
            label,
            value,
            bg=bg,
            accent=accent,
            fg=fg,
            emphasize_metrics=emphasize_metrics,
            font_size=font_size,
        )
        + "</div>"
    )


def _render_magazine_card_row_html(
    cards: list[tuple[str, str, str, str, str, bool, str]],
    *,
    margin_top: int = 0,
) -> str:
    """
    功能说明：
        渲染 magazine card row html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - cards: 业务输入参数。
        - margin_top: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not cards:
        return ""
    cells: list[str] = []
    for idx, (label, value, bg, accent, fg, emphasize_metrics, font_size) in enumerate(
        cards
    ):
        if not value:
            continue
        left_pad = "0 6px 0 0" if idx == 0 else "0 0 0 6px"
        cells.append(
            f'<td valign="top" width="50%" style="width:50%;padding:{left_pad};">'
            + _render_magazine_card_box_html(
                label,
                value,
                bg=bg,
                accent=accent,
                fg=fg,
                emphasize_metrics=emphasize_metrics,
                font_size=font_size,
                stretch=True,
            )
            + "</td>"
        )
    if not cells:
        return ""
    return (
        f'<div style="margin-top:{margin_top}px;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" '
        'style="width:100%;border-collapse:separate;table-layout:fixed;">'
        "<tr>" + "".join(cells) + "</tr></table></div>"
    )


def _render_summary_block_html(label: str, value: str) -> str:
    """
    功能说明：
        渲染 summary block html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - label: 业务输入参数。
        - value: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    bg, accent, fg = _summary_block_palette(label)
    body_html = _render_highlighted_text_html(
        value,
        fg=fg,
        accent=accent,
        emphasize_metrics=(label in {"关键结果", "最硬结果", "结果亮点"}),
    )
    return (
        '<div style="margin:12px 0 0;padding:14px 16px;border-radius:14px;'
        f'background:{bg};border-left:5px solid {accent};">'
        f'<div style="font-size:13px;font-weight:900;color:{accent};'
        'letter-spacing:0.04em;margin-bottom:6px;">'
        f"{html.escape(label)}</div>"
        f'<div style="font-size:15px;line-height:1.75;color:{fg};">{body_html}</div>'
        "</div>"
    )


def _is_magazine_summary(summary: dict[str, str]) -> bool:
    """
    功能说明：
        执行 `_is_magazine_summary` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `bool`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not summary:
        return False
    magazine_keys = {
        "科学问题",
        "核心思路",
        "核心idea",
        "关键结果",
        "最硬结果",
        "可借鉴之处",
        "可借鉴点",
        "局限与边界",
        "风险边界",
        "关键问题",
        "问题痛点",
        "方法设计",
        "方法速写",
        "编辑判断",
    }
    return any((summary.get(k) or "").strip() for k in magazine_keys)


def _render_magazine_spotlight_html(summary: dict[str, str]) -> str:
    """
    功能说明：
        渲染 magazine spotlight html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    hook = _summary_value(summary, "一句话看点", "hook", "headline")
    judgment = _summary_value(summary, "编辑判断", "judgment", "tag")
    rating_html = _render_editorial_rating_html(summary)
    if not hook and not judgment and not rating_html:
        return ""
    hook_html = (
        _render_highlighted_text_html(hook, fg="#7c2d12", accent="#f59e0b")
        if hook
        else ""
    )
    parts = [
        '<div style="margin:14px 0 0;padding:18px 18px 16px;border-radius:18px;'
        "background:linear-gradient(135deg,#fff7ed 0%,#ffedd5 100%);"
        'border:1px solid #fdba74;box-shadow:0 10px 24px rgba(249,115,22,0.12);">',
    ]
    if judgment or rating_html:
        parts.append(
            '<div style="font-size:12px;font-weight:900;letter-spacing:0.08em;'
            'color:#9a3412;">推荐指数</div>'
        )
    if rating_html:
        parts.append(f'<div style="margin-top:8px;">{rating_html}</div>')
    if hook:
        parts.append(
            '<div style="margin-top:14px;font-size:12px;font-weight:900;letter-spacing:0.08em;'
            'color:#c2410c;">一句话看点</div>'
        )
        parts.append(
            f'<div style="margin-top:8px;font-size:22px;line-height:1.6;font-weight:900;color:#7c2d12;">{hook_html}</div>'
        )
    parts.append("</div>")
    return "".join(parts)


def _render_magazine_highlights_html(summary: dict[str, str]) -> str:
    """
    功能说明：
        渲染 magazine highlights html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    idea = _summary_value(summary, "核心思路", "核心idea", "核心想法", "idea")
    problem = _summary_value(
        summary, "科学问题", "关键问题", "问题痛点", "why_it_matters", "为什么值得看"
    )
    results = _summary_value(summary, "关键结果", "最硬结果", "结果亮点", "key_results")
    borrow = _summary_value(
        summary,
        "可借鉴之处",
        "可借鉴点",
        "可参考点",
        "对你有什么启发",
        "insight_for_you",
    )

    rendered: list[str] = []
    row_cards = [
        ("核心思路", idea, "#eef2ff", "#6366f1", "#3730a3", False, "16px"),
        ("可借鉴之处", borrow, "#fdf2f8", "#ec4899", "#9d174d", False, "15px"),
    ]
    row_cards = [card for card in row_cards if card[1]]
    if not row_cards and not problem and not results:
        return ""
    if len(row_cards) == 2:
        rendered.append(_render_magazine_card_row_html(row_cards, margin_top=0))
    elif len(row_cards) == 1:
        card = row_cards[0]
        rendered.append(
            _render_magazine_card_html(
                card[0],
                card[1],
                bg=card[2],
                accent=card[3],
                fg=card[4],
                emphasize_metrics=card[5],
                margin_top=0,
                font_size=card[6],
            )
        )
    if problem:
        rendered.append(
            _render_magazine_card_html(
                "科学问题",
                problem,
                bg="#eff6ff",
                accent="#3b82f6",
                fg="#1e3a8a",
                margin_top=12 if rendered else 0,
                font_size="15px",
            )
        )
    if results:
        rendered.append(
            _render_magazine_card_html(
                "关键结果",
                results,
                bg="#f5f3ff",
                accent="#8b5cf6",
                fg="#5b21b6",
                emphasize_metrics=True,
                margin_top=12 if rendered else 0,
                font_size="15px",
            )
        )
    return (
        '<div style="margin:14px 0 0;">'
        '<div style="font-size:12px;font-weight:900;letter-spacing:0.08em;color:#64748b;'
        'margin-bottom:10px;">重点摘要</div>' + "".join(rendered) + "</div>"
    )


def _render_magazine_secondary_cards_html(summary: dict[str, str]) -> str:
    """
    功能说明：
        渲染 magazine secondary cards html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    method = _summary_value(summary, "方法设计", "方法速写", "method", "核心方法")
    cards = [("方法设计", method, "#ecfdf5", "#10b981", "#065f46")]
    rendered: list[str] = []
    for idx, (label, value, bg, accent, fg) in enumerate(cards):
        if not value:
            continue
        rendered.append(
            _render_magazine_card_html(
                label,
                value,
                bg=bg,
                accent=accent,
                fg=fg,
                margin_top=0 if idx == 0 else 12,
            )
        )
    if not rendered:
        return ""
    return '<div style="margin-top:14px;">' + "".join(rendered) + "</div>"


def _render_magazine_boundary_html(summary: dict[str, str]) -> str:
    """
    功能说明：
        渲染 magazine boundary html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    risk = _summary_value(summary, "局限与边界", "风险边界", "limitations", "风险")
    if not risk:
        return ""
    return _render_magazine_card_html(
        "局限与边界",
        risk,
        bg="#fff7ed",
        accent="#f97316",
        fg="#9a3412",
    )


def _render_magazine_summary_html(summary: dict[str, str]) -> str:
    """
    功能说明：
        渲染 magazine summary html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    parts: list[str] = []
    spotlight = _render_magazine_spotlight_html(summary)
    if spotlight:
        parts.append(spotlight)
    highlights = _render_magazine_highlights_html(summary)
    if highlights:
        parts.append(highlights)

    secondary = _render_magazine_secondary_cards_html(summary)
    if secondary:
        parts.append(secondary)

    boundary = _render_magazine_boundary_html(summary)
    if boundary:
        parts.append(boundary)

    extra_blocks: list[str] = []
    handled = {
        "一句话看点",
        "编辑判断",
        "科学问题",
        "关键问题",
        "问题痛点",
        "核心思路",
        "核心idea",
        "方法设计",
        "方法速写",
        "关键结果",
        "最硬结果",
        "可借鉴之处",
        "可借鉴点",
        "局限与边界",
        "风险边界",
    }
    for label in ("为什么值得看", "核心方法", "结果亮点", "对你有什么启发"):
        value = (summary.get(label) or "").strip()
        if value:
            handled.add(label)
            extra_blocks.append(_render_summary_block_html(label, value))
    if extra_blocks:
        parts.extend(extra_blocks)

    for label, value in _ordered_summary_items(summary):
        if label not in handled:
            parts.append(_render_summary_block_html(label, value))

    return "".join(parts)


def _text_summary_items(summary: dict[str, str]) -> list[tuple[str, str]]:
    """
    功能说明：
        执行 `_text_summary_items` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - summary: 业务输入参数。
    返回值：
        返回类型为 `list[tuple[str, str]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    items: list[tuple[str, str]] = []
    for label, value in _ordered_summary_items(summary):
        if label == "编辑判断":
            stars = _editorial_star_text(value or _derive_editorial_judgment(summary))
            if stars:
                items.append(("推荐指数", stars))
                continue
        if label == "关键问题":
            items.append(("科学问题", value))
            continue
        items.append((label, value))
    return items


def _normalize_title(title: str) -> str:
    """
    功能说明：
        规范化输入数据，去除噪声并统一格式，降低后续处理复杂度。
    参数说明：
        - title: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    title = title or ""
    title = re.sub(r"\s+", " ", title).strip().lower()
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", "", title)
    return title


def _normalize_for_match(text: str) -> str:
    """
    功能说明：
        规范化输入数据，去除噪声并统一格式，降低后续处理复杂度。
    参数说明：
        - text: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    text = (text or "").lower()
    # Join common hyphenated biomedical terms
    text = re.sub(r"\bnon[-\s]?invasive\b", "noninvasive", text)
    text = re.sub(r"\bcuff[-\s]?less\b", "cuffless", text)
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _token_set(text: str) -> set[str]:
    """
    功能说明：
        执行 `_token_set` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - text: 业务输入参数。
    返回值：
        返回类型为 `set[str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    norm = _normalize_for_match(text)
    if not norm:
        return set()
    tokens = [t for t in norm.split(" ") if t]
    token_set = {t for t in tokens if len(t) >= 3 or t in {"bp"}}

    # Synonyms / abbreviations
    if any(t.startswith("photoplethysmograph") for t in token_set):
        token_set.add("ppg")
    if {"pulse", "transit", "time"}.issubset(token_set):
        token_set.add("ptt")
    if {"pulse", "arrival", "time"}.issubset(token_set):
        token_set.add("pat")

    return token_set


def _required_token_hits(token_count: int, min_hits: int, min_fraction: float) -> int:
    """
    功能说明：
        执行 `_required_token_hits` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - token_count: 业务输入参数。
        - min_hits: 业务输入参数。
        - min_fraction: 业务输入参数。
    返回值：
        返回类型为 `int`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if token_count <= 0:
        return 0
    min_fraction = float(min_fraction)
    if min_fraction <= 0:
        frac_hits = 1
    else:
        frac_hits = int(math.ceil(token_count * min_fraction))
    required = max(int(min_hits), frac_hits)
    return min(required, token_count)


def _as_clean_str_list(value: Any) -> list[str]:
    """
    功能说明：
        执行 `_as_clean_str_list` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - value: 业务输入参数。
    返回值：
        返回类型为 `list[str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for v in value:
        s = str(v).strip()
        if s:
            cleaned.append(s)
    return cleaned


# 宽泛词库，不重要的词
GENERIC_QUERY_TOKENS: set[str] = set({})

DEFAULT_TOPIC_TARGET_TERMS: tuple[str, ...] = "llm"

DEFAULT_TOPIC_SUPPORT_TERMS: tuple[str, ...] = "llm"

DEFAULT_TOPIC_EXCLUDE_TERMS: tuple[str, ...] = (
    "blockchain",
    "proof of stake",
    "mining strategy",
    "hydrogen storage",
    "taxus",
    "poliovirus",
    "aggregate gradation",
    "quantum subspace",
    "climate change",
)

DEFAULT_LLM_PREFERENCE_PROFILE = (
    "优先推荐使用llm或深度学习医学报告生成相关的论文，"
    "重点关注 多模态、机器学习、深度学习、"
)

SUMMARY_RENDER_ORDER: tuple[str, ...] = (
    "一句话看点",
    "编辑判断",
    "科学问题",
    "关键问题",
    "核心思路",
    "方法设计",
    "关键结果",
    "可借鉴之处",
    "局限与边界",
    "为什么值得看",
    "核心方法",
    "结果亮点",
    "对你有什么启发",
    "背景",
    "动机",
    "方法",
    "结果",
)


def _match_term_in_tokens(term: str, text_tokens: set[str]) -> bool:
    """
    功能说明：
        执行 `_match_term_in_tokens` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - term: 业务输入参数。
        - text_tokens: 业务输入参数。
    返回值：
        返回类型为 `bool`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    term_tokens = _token_set(term)
    if not term_tokens:
        return False
    return term_tokens.issubset(text_tokens)


def _count_term_hits(terms: list[str], text_tokens: set[str]) -> int:
    """
    功能说明：
        执行 `_count_term_hits` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - terms: 业务输入参数。
        - text_tokens: 业务输入参数。
    返回值：
        返回类型为 `int`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not terms or not text_tokens:
        return 0
    return sum(1 for term in terms if _match_term_in_tokens(term, text_tokens))


def _paper_matches_topic_filter(
    paper: Paper,
    topic_filter_cfg: dict[str, Any],
) -> bool:
    """
    功能说明：
        执行 `_paper_matches_topic_filter` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
        - topic_filter_cfg: 配置字典或配置对象。
    返回值：
        返回类型为 `bool`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not bool(topic_filter_cfg.get("enabled", True)):
        return True

    target_terms = _as_clean_str_list(topic_filter_cfg.get("target_terms"))
    if not target_terms:
        target_terms = list(DEFAULT_TOPIC_TARGET_TERMS)

    support_terms = _as_clean_str_list(topic_filter_cfg.get("support_terms"))
    if not support_terms:
        support_terms = list(DEFAULT_TOPIC_SUPPORT_TERMS)

    exclude_terms = _as_clean_str_list(topic_filter_cfg.get("exclude_terms"))
    if not exclude_terms:
        exclude_terms = list(DEFAULT_TOPIC_EXCLUDE_TERMS)

    min_target_hits = int(topic_filter_cfg.get("min_target_hits") or 1)
    min_support_hits = int(topic_filter_cfg.get("min_support_hits") or 1)

    content = _safe_join(
        [paper.title, paper.abstract, paper.venue, paper.publisher], sep=" "
    )
    content_tokens = _token_set(content)
    if not content_tokens:
        return False

    for term in exclude_terms:
        if _match_term_in_tokens(term, content_tokens):
            return False

    required_groups = topic_filter_cfg.get("required_groups") or []
    if isinstance(required_groups, list) and required_groups:
        for g in required_groups:
            if not isinstance(g, dict):
                continue
            g_terms = _as_clean_str_list(g.get("terms"))
            if not g_terms:
                continue
            g_min_hits = int(g.get("min_hits") or 1)
            if _count_term_hits(g_terms, content_tokens) < max(g_min_hits, 0):
                return False

    clinical_guard = topic_filter_cfg.get("clinical_guard") or {}
    if isinstance(clinical_guard, dict) and clinical_guard:
        clinical_terms = _as_clean_str_list(clinical_guard.get("clinical_terms"))
        device_terms = _as_clean_str_list(clinical_guard.get("device_terms"))
        trigger_hits = int(clinical_guard.get("trigger_hits") or 3)
        min_device_hits = int(clinical_guard.get("min_device_hits") or 2)
        clinical_hits = _count_term_hits(clinical_terms, content_tokens)
        device_hits = _count_term_hits(device_terms, content_tokens)
        if clinical_hits >= max(trigger_hits, 0) and device_hits < max(
            min_device_hits, 0
        ):
            return False

    if required_groups:
        return True

    target_hits = sum(
        1 for term in target_terms if _match_term_in_tokens(term, content_tokens)
    )
    support_hits = sum(
        1 for term in support_terms if _match_term_in_tokens(term, content_tokens)
    )

    return target_hits >= max(min_target_hits, 0) and support_hits >= max(
        min_support_hits, 0
    )


def _keyword_similarity_score(keyword: str, text: str) -> float:
    """
    功能说明：
        执行 `_keyword_similarity_score` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - keyword: 关键词或关键词集合。
        - text: 业务输入参数。
    返回值：
        返回类型为 `float`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    query_tokens = _token_set(keyword)
    text_tokens = _token_set(text)
    if not query_tokens or not text_tokens:
        return 0.0

    overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
    distinctive_tokens = query_tokens - GENERIC_QUERY_TOKENS
    if distinctive_tokens:
        distinctive_overlap = len(distinctive_tokens & text_tokens) / max(
            len(distinctive_tokens), 1
        )
    else:
        distinctive_overlap = overlap
    return (0.35 * overlap) + (0.65 * distinctive_overlap)


def _paper_relevance_score(paper: Paper) -> float:
    """
    功能说明：
        执行 `_paper_relevance_score` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
    返回值：
        返回类型为 `float`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    content = _safe_join(
        [paper.title, paper.abstract, paper.venue, paper.publisher], sep=" "
    )
    if not content:
        return 0.0
    if not paper.keywords:
        return 0.0
    return max(
        (_keyword_similarity_score(kw, content) for kw in paper.keywords), default=0.0
    )


_VENUE_IMPACT_HINTS: tuple[tuple[str, float], ...] = (
    ("nature biomedical engineering", 1.00),
    ("nature electronics", 0.98),
    ("nature communications", 0.95),
    ("nature", 0.94),
    ("science translational medicine", 0.96),
    ("science advances", 0.94),
    ("science", 0.93),
    ("lancet", 0.95),
    ("new england journal of medicine", 0.95),
    ("jama", 0.92),
    ("cell reports medicine", 0.90),
    ("cell", 0.90),
    ("advanced materials", 0.88),
    ("advanced functional materials", 0.84),
    ("advanced healthcare materials", 0.82),
    ("acs nano", 0.84),
    ("biosensors & bioelectronics", 0.85),
    ("biosensors and bioelectronics", 0.85),
    ("ieee reviews in biomedical engineering", 0.86),
    ("ieee transactions on biomedical engineering", 0.84),
    ("ieee transactions on", 0.78),
    ("ieee journal", 0.72),
    ("analytical chemistry", 0.78),
    ("talanta", 0.68),
    ("sensors", 0.55),
    ("micromachines", 0.50),
    ("arxiv", 0.30),
)


_PUBLISHER_IMPACT_HINTS: tuple[tuple[str, float], ...] = (
    ("nature portfolio", 0.92),
    ("springer nature", 0.88),
    ("ieee", 0.76),
    ("elsevier", 0.74),
    ("wiley", 0.72),
    ("acs", 0.72),
    ("rsc", 0.70),
    ("mdpi", 0.50),
    ("arxiv", 0.30),
)


def _journal_impact_score(paper: Paper) -> float:
    """
    功能说明：
        执行 `_journal_impact_score` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
    返回值：
        返回类型为 `float`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    venue = (paper.venue or "").strip().lower()
    publisher = (paper.publisher or "").strip().lower()
    source = (paper.source or "").strip().lower()

    if source == "arxiv":
        return 0.30

    best = 0.45
    for token, score in _VENUE_IMPACT_HINTS:
        if token in venue:
            best = max(best, score)
    for token, score in _PUBLISHER_IMPACT_HINTS:
        if token in publisher:
            best = max(best, score)
    return min(best, 1.00)


def _paper_recency_score(paper: Paper, run_date: dt.date) -> float:
    """
    功能说明：
        执行 `_paper_recency_score` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
        - run_date: 时间范围或日期参数。
    返回值：
        返回类型为 `float`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not paper.published_date:
        return 0.15
    delta_days = (run_date - paper.published_date).days
    if delta_days < 0:
        delta_days = 0
    if delta_days <= 7:
        return 1.00
    if delta_days <= 30:
        return 0.85
    if delta_days <= 90:
        return 0.65
    if delta_days <= 180:
        return 0.45
    return 0.25


def _paper_priority_score(
    paper: Paper,
    run_date: dt.date,
    relevance_weight: float,
    impact_weight: float,
    recency_weight: float,
) -> float:
    """
    功能说明：
        执行 `_paper_priority_score` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
        - run_date: 时间范围或日期参数。
        - relevance_weight: 业务输入参数。
        - impact_weight: 业务输入参数。
        - recency_weight: 业务输入参数。
    返回值：
        返回类型为 `float`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    relevance = _paper_relevance_score(paper)
    impact = _journal_impact_score(paper)
    recency = _paper_recency_score(paper, run_date)
    return (
        (relevance_weight * relevance)
        + (impact_weight * impact)
        + (recency_weight * recency)
    )


def _build_arxiv_queries(keyword: str, query_mode: str = "adaptive") -> list[str]:
    """
    功能说明：
        执行 `_build_arxiv_queries` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - keyword: 关键词或关键词集合。
        - query_mode: 业务输入参数。
    返回值：
        返回类型为 `list[str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    raw_keyword = (keyword or "").strip()
    if not raw_keyword:
        return []

    mode = (query_mode or "adaptive").strip().lower()
    phrase_query = f'all:"{raw_keyword}"'

    query_tokens = list(_token_set(raw_keyword))
    distinctive_tokens = [t for t in query_tokens if t not in GENERIC_QUERY_TOKENS]
    core_tokens = distinctive_tokens if len(distinctive_tokens) >= 2 else query_tokens
    core_tokens = core_tokens[:4]

    token_query = ""
    if len(core_tokens) >= 2:
        token_query = " AND ".join([f"all:{t}" for t in core_tokens])
    elif len(core_tokens) == 1:
        token_query = f"all:{core_tokens[0]}"

    queries: list[str] = []
    if mode in ("phrase", "exact"):
        queries.append(phrase_query)
    elif mode in ("tokens", "broad"):
        if token_query:
            queries.append(token_query)
        queries.append(phrase_query)
    else:
        # adaptive: broad token query + exact phrase fallback
        if token_query:
            queries.append(token_query)

        expanded = list(core_tokens)
        if "ppg" in query_tokens and "photoplethysmography" not in expanded:
            expanded.append("photoplethysmography")
        if "photoplethysmography" in query_tokens and "ppg" not in expanded:
            expanded.append("ppg")
        if {"continuous", "glucose", "monitoring"}.issubset(
            set(query_tokens)
        ) and "cgm" not in expanded:
            expanded.append("cgm")
        if {"blood", "pressure"}.issubset(set(query_tokens)) and "bp" not in expanded:
            expanded.append("bp")
        expanded = expanded[:4]
        if len(expanded) >= 2:
            expanded_query = " AND ".join([f"all:{t}" for t in expanded])
            if expanded_query and expanded_query != token_query:
                queries.append(expanded_query)

        queries.append(phrase_query)

    unique_queries: list[str] = []
    seen: set[str] = set()
    for q in queries:
        q = q.strip()
        if not q or q in seen:
            continue
        seen.add(q)
        unique_queries.append(q)
    return unique_queries


def _extract_json_object(text: str) -> dict[str, Any]:
    """
    功能说明：
        执行 `_extract_json_object` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - text: 业务输入参数。
    返回值：
        返回类型为 `dict[str, Any]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not text:
        return {}
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    candidate = text[start : end + 1]
    candidate = candidate.replace("“", '"').replace("”", '"').replace("’", "'")
    try:
        return json.loads(candidate)
    except Exception:
        return {}


def _strip_jats_abstract(abstract: str) -> str:
    """
    功能说明：
        执行 `_strip_jats_abstract` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - abstract: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not abstract:
        return ""
    # Crossref sometimes returns JATS XML, often wrapped in <jats:p>...</jats:p>
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = html.unescape(abstract)
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return abstract


def _env_get(name: str) -> str:
    """
    功能说明：
        执行 `_env_get` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - name: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    value = os.getenv(name, "").strip()
    if value:
        return value

    # On Windows, env vars set via `setx` may exist in registry but not in
    # the current process environment. Fallback to User/Machine scopes.
    if os.name == "nt":
        try:
            import winreg  # type: ignore

            registry_paths = (
                (winreg.HKEY_CURRENT_USER, r"Environment"),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                ),
            )
            for hive, subkey in registry_paths:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        raw, _ = winreg.QueryValueEx(key, name)
                    candidate = os.path.expandvars(str(raw)).strip()
                    if candidate:
                        return candidate
                except Exception:
                    continue
        except Exception:
            pass
    return ""


def _log(msg: str) -> None:
    """
    功能说明：
        执行 `_log` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - msg: 业务输入参数。
    返回值：
        返回类型为 `None`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = str(msg).encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        )
        print(safe, flush=True)


def _http_get_with_retry(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout_s: int = 30,
    max_retries: int = 3,
    backoff_s: float = 1.2,
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Response:
    """
    功能说明：
        执行 `_http_get_with_retry` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - url: 业务输入参数。
        - params: 业务输入参数。
        - headers: 业务输入参数。
        - timeout_s: 超时时间（秒）。
        - max_retries: 业务输入参数。
        - backoff_s: 业务输入参数。
        - retry_statuses: 业务输入参数。
    返回值：
        返回类型为 `requests.Response`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    last_exc: Optional[Exception] = None
    retries = max(1, int(max_retries))
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout_s)
            if resp.status_code in retry_statuses and attempt < retries - 1:
                time.sleep(backoff_s * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt >= retries - 1:
                raise
            time.sleep(backoff_s * (attempt + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError("Unreachable retry path")


def _load_json(path: str) -> dict[str, Any]:
    """
    功能说明：
        加载外部数据并返回可直接使用的 Python 对象。
    参数说明：
        - path: 文件或路径参数。
    返回值：
        返回类型为 `dict[str, Any]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _save_json(path: str, data: dict[str, Any]) -> None:
    """
    功能说明：
        将运行中产生的数据持久化到目标存储位置。
    参数说明：
        - path: 文件或路径参数。
        - data: 业务输入参数。
    返回值：
        返回类型为 `None`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_config(path: str) -> dict[str, Any]:
    """加载配置并补齐一级键，避免后续链式访问缺键。"""
    config = _load_json(path)
    config.setdefault("search", {})
    config.setdefault("sources", {})
    config.setdefault("email", {})
    config.setdefault("llm", {})
    config.setdefault("state", {})
    config.setdefault("schedule", {})
    return config


def load_state(path: str) -> dict[str, Any]:
    """
    读取状态文件（历史模式）。

    平台模式下通常通过 `state_override` 传入数据库状态，
    本函数主要用于兼容脚本独立运行。
    """
    if not os.path.exists(path):
        return {"seen": {}, "last_run": ""}
    try:
        return _load_json(path)
    except Exception:
        return {"seen": {}, "last_run": ""}


def prune_state(state: dict[str, Any], keep_days: int) -> dict[str, Any]:
    """裁剪去重状态，只保留最近 `keep_days` 的记录。"""

    def _prune_seen_map(raw_seen: Any) -> dict[str, str]:
        seen_map = raw_seen if isinstance(raw_seen, dict) else {}
        pruned: dict[str, str] = {}
        for key, value in seen_map.items():
            d = _parse_date(str(value or "").strip())
            if d and d >= cutoff:
                pruned[str(key)] = str(value)
        return pruned

    if not keep_days or keep_days <= 0:
        return state
    cutoff = _today_local() - dt.timedelta(days=keep_days)
    state["seen"] = _prune_seen_map(state.get("seen"))
    state["seen_scheduled"] = _prune_seen_map(state.get("seen_scheduled"))
    return state


def _to_int(v: Any, default: int) -> int:
    """
    功能说明：
        执行 `_to_int` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - v: 业务输入参数。
        - default: 业务输入参数。
    返回值：
        返回类型为 `int`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    try:
        return int(v)
    except Exception:
        return default


def _to_weekday(value: Any, default: int) -> int:
    """
    功能说明：
        执行 `_to_weekday` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - value: 业务输入参数。
        - default: 业务输入参数。
    返回值：
        返回类型为 `int`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    day = _to_int(value, default)
    if day < 1 or day > 7:
        return default
    return day


def _weekday_label(day: int) -> str:
    """
    功能说明：
        执行 `_weekday_label` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - day: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    return _WEEKDAY_LABELS.get(day, f"day-{day}")


def _latest_scheduled_weekday(run_date: dt.date, weekday: int) -> dt.date:
    """
    功能说明：
        执行 `_latest_scheduled_weekday` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - run_date: 时间范围或日期参数。
        - weekday: 业务输入参数。
    返回值：
        返回类型为 `dt.date`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    delta = (run_date.isoweekday() - weekday) % 7
    return run_date - dt.timedelta(days=delta)


def _coerce_weekday_set(raw: Any, default_days: set[int]) -> set[int]:
    """
    功能说明：
        将输入值强制转换到目标类型，并在异常情况下回退到默认值。
    参数说明：
        - raw: 业务输入参数。
        - default_days: 业务输入参数。
    返回值：
        返回类型为 `set[int]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if raw is None:
        return set(default_days)
    days: set[int] = set()
    values: list[Any] = []
    if isinstance(raw, str):
        values = [p.strip() for p in raw.split(",") if p and p.strip()]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = [raw]
    for v in values:
        day = _to_weekday(v, -1)
        if 1 <= day <= 7:
            days.add(day)
    if not days:
        return set(default_days)
    return days


def _normalize_keywords(raw: Any) -> list[str]:
    """
    功能说明：
        规范化输入数据，去除噪声并统一格式，降低后续处理复杂度。
    参数说明：
        - raw: 业务输入参数。
    返回值：
        返回类型为 `list[str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return _unique_clean_list(raw)


def _history_keep_days(state_cfg: dict[str, Any], keep_days: int) -> int:
    """
    功能说明：
        执行 `_history_keep_days` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - state_cfg: 配置字典或配置对象。
        - keep_days: 业务输入参数。
    返回值：
        返回类型为 `int`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    raw = state_cfg.get("history_keep_days")
    if raw is None:
        # By default, keep the same retention policy as dedupe state.keep_days.
        # 0 or negative means keep full history permanently.
        return keep_days
    return _to_int(raw, keep_days)


def _prune_push_history(
    history: Any,
    keep_days: int,
    today: Optional[dt.date] = None,
) -> list[dict[str, Any]]:
    """
    功能说明：
        执行 `_prune_push_history` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - history: 业务输入参数。
        - keep_days: 业务输入参数。
        - today: 业务输入参数。
    返回值：
        返回类型为 `list[dict[str, Any]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not isinstance(history, list):
        return []
    keep = _to_int(keep_days, 0)
    use_cutoff = keep > 0
    base = today or _today_local()
    cutoff = base - dt.timedelta(days=keep) if use_cutoff else None

    result: list[dict[str, Any]] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        push_raw = str(row.get("push_date") or "").strip()
        push_date = _parse_date(push_raw)
        if not push_date:
            continue
        if cutoff and push_date < cutoff:
            continue

        published_raw = str(row.get("published_date") or "").strip()
        published_date = _parse_date(published_raw) if published_raw else None

        categories = row.get("keyword_categories") or []
        if isinstance(categories, str):
            categories = [categories]
        if not isinstance(categories, list):
            categories = []

        record = {
            "uid": str(row.get("uid") or "").strip(),
            "push_date": push_date.isoformat(),
            "title": str(row.get("title") or "").strip(),
            "url": str(row.get("url") or "").strip(),
            "venue": str(row.get("venue") or "").strip(),
            "publisher": str(row.get("publisher") or "").strip(),
            "source": str(row.get("source") or "").strip(),
            "published_date": published_date.isoformat() if published_date else "",
            "keywords": _normalize_keywords(row.get("keywords")),
            "keyword_categories": _unique_clean_list(categories),
        }
        result.append(record)

    result.sort(
        key=lambda r: (r.get("push_date") or "", r.get("title") or ""),
        reverse=True,
    )
    return result


def _paper_uid(p: Paper) -> str:
    """
    功能说明：
        执行 `_paper_uid` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - p: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if p.doi:
        return f"doi:{p.doi.lower()}"
    if p.arxiv_id:
        return f"arxiv:{p.arxiv_id.lower()}"
    return f"title:{_normalize_title(p.title)}"


# 导出当前模块全部符号（包含下划线前缀符号，供分层模块通过 * 复用）。
__all__ = [
    name
    for name in globals().keys()
    if name
    not in {
        "__builtins__",
        "__cached__",
        "__doc__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
        "__all__",
    }
]
