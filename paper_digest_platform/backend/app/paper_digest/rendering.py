from __future__ import annotations

"""邮件正文与周报渲染实现。"""
import html
import datetime as dt
from app.paper_digest.core_utils import *
from app.paper_digest.sources_and_llm import *


def build_email(
    run_date: dt.date,
    papers: list[Paper],
    summaries: dict[str, dict[str, str]],
) -> tuple[str, str, str]:
    """
    功能说明：
        构建 email 相关内容，用于邮件展示、摘要输出或主流程编排。
    参数说明：
        - run_date: 时间范围或日期参数。
        - papers: 待处理的数据集合。
        - summaries: 业务输入参数。
    返回值：
        返回类型为 `tuple[str, str, str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    subject = f"每日论文推送 {run_date.isoformat()}（{len(papers)}篇）"

    text_lines: list[str] = [subject, ""]
    html_lines: list[str] = [
        "<html>",
        (
            '<body style="margin:0;padding:0;background:#eef2f7;color:#0f172a;'
            "font-family:'Segoe UI',Arial,'PingFang SC','Microsoft YaHei',sans-serif;\">"
        ),
        (
            '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" '
            'style="width:100%;border-collapse:collapse;background:#eef2f7;">'
        ),
        '<tr><td align="center" style="padding:28px 14px;">',
        (
            '<table role="presentation" cellspacing="0" cellpadding="0" width="920" '
            'style="width:920px;max-width:920px;border-collapse:separate;background:#ffffff;'
            'border:1px solid #d7e0ea;border-radius:24px;overflow:hidden;">'
        ),
        (
            '<tr><td style="padding:28px 32px;background:#0f172a;">'
            '<div style="font-size:12px;font-weight:800;letter-spacing:0.14em;'
            'text-transform:uppercase;color:#93c5fd;">Paper Digest</div>'
            f'<div style="margin-top:10px;font-size:30px;line-height:1.2;font-weight:900;color:#f8fafc;">{html.escape(subject)}</div>'
            '<div style="margin-top:18px;">'
            + _html_badge(
                f"{len(papers)} 篇精选", bg="#dbeafe", fg="#1d4ed8", border="#93c5fd"
            )
            + _html_badge(
                run_date.isoformat(), bg="#dcfce7", fg="#166534", border="#86efac"
            )
            + "</div>"
            "</td></tr>"
        ),
        '<tr><td style="padding:24px 24px 30px;background:#ffffff;">',
    ]

    for idx, p in enumerate(papers, start=1):
        uid = _paper_uid(p)
        s = summaries.get(uid) or {}
        title = html.escape(p.title)
        url = html.escape(p.url)
        venue = html.escape(p.venue or "")
        pub = html.escape(p.published_date.isoformat() if p.published_date else "")
        publisher = html.escape(p.publisher or "")
        source_name = html.escape(_source_display_name(p.source))
        authors = html.escape(_safe_join(p.authors))
        intro = _paper_intro(p, s, max_len=420)

        html_lines.append(
            '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" '
            'style="width:100%;border-collapse:separate;margin:0 0 26px 0;background:#ffffff;'
            "border:1px solid #cbd5e1;border-top:6px solid #0f3d91;border-radius:22px;"
            'overflow:hidden;box-shadow:0 12px 28px rgba(15,23,42,0.08);">'
        )
        html_lines.append('<tr><td style="padding:22px 22px 18px;">')
        html_lines.append(
            '<div style="margin-bottom:10px;">'
            f"{_html_badge(f'Paper {idx:02d}', bg='#dbeafe', fg='#0f3d91', border='#93c5fd')}"
            "</div>"
        )
        html_lines.append(
            f'<div style="margin-top:8px;font-size:24px;line-height:1.35;font-weight:900;color:#0f172a;">'
            f'<a href="{url}" style="color:#0f3d91;text-decoration:none;">{title}</a></div>'
        )
        html_lines.append(
            '<div style="margin-top:12px;">' + _render_meta_badges_html(p) + "</div>"
        )
        meta_text_parts = [f"<b>期刊/会议：</b>{venue}"]
        if publisher:
            meta_text_parts.append(f"<b>出版商：</b>{publisher}")
        if source_name:
            meta_text_parts.append(f"<b>检索来源：</b>{source_name}")
        meta_text_parts.append(f"<b>发表日期：</b>{pub}")
        html_lines.append(
            '<div style="margin-top:8px;font-size:14px;line-height:1.7;color:#475569;">'
            + " &nbsp; ".join(meta_text_parts)
            + "</div>"
        )
        if authors:
            html_lines.append(
                '<div style="margin-top:10px;font-size:14px;line-height:1.7;color:#475569;">'
                f'<b style="color:#334155;">作者：</b>{authors}</div>'
            )
        keyword_html = _render_keyword_badges_html(p.keywords)
        if keyword_html:
            html_lines.append(keyword_html)
        if intro:
            html_lines.append(
                '<div style="margin-top:14px;padding:14px 16px;border-radius:14px;'
                'background:#f8fafc;border:1px solid #e2e8f0;">'
                '<div style="font-size:12px;font-weight:900;color:#64748b;'
                'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:7px;">快速预览</div>'
                f'<div style="font-size:15px;line-height:1.75;color:#334155;">{html.escape(intro)}</div>'
                "</div>"
            )
        if s:
            if _is_magazine_summary(s):
                html_lines.append(_render_magazine_summary_html(s))
            else:
                for k, v in _ordered_summary_items(s):
                    html_lines.append(_render_summary_block_html(k, v))
        html_lines.append("</td></tr></table>")

        text_lines.append(f"{idx}. {p.title}")
        text_lines.append(f"   链接: {p.url}")
        text_pub = p.published_date.isoformat() if p.published_date else ""
        text_meta_parts = [f"期刊/会议: {p.venue}"]
        if p.publisher:
            text_meta_parts.append(f"出版商: {p.publisher}")
        if p.source:
            text_meta_parts.append(f"检索来源: {_source_display_name(p.source)}")
        text_meta_parts.append(f"日期: {text_pub}")
        text_lines.append("   " + " | ".join(text_meta_parts))
        if p.keywords:
            text_lines.append(f"   关键词命中: {_safe_join(p.keywords)}")
        if intro:
            text_lines.append(f"   简介: {intro}")
        if s:
            for k, v in _text_summary_items(s):
                text_lines.append(f"   {k}: {v}")
        text_lines.append("")

    html_lines.extend(
        [
            "</td></tr>",
            "</table>",
            "</td></tr>",
            "</table>",
            "</body>",
            "</html>",
        ]
    )
    return subject, "\n".join(text_lines), "\n".join(html_lines)


def _keyword_categories(keywords: list[str]) -> list[str]:
    """
    功能说明：
        执行 `_keyword_categories` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - keywords: 关键词或关键词集合。
    返回值：
        返回类型为 `list[str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    haystack = " ".join(k.lower() for k in keywords if k).strip()
    if not haystack:
        return ["其他"]
    matched: list[str] = []
    for label, terms in _WEEKLY_CATEGORY_RULES:
        if any(t in haystack for t in terms):
            matched.append(label)
    if not matched:
        return ["其他"]
    return matched


def _paper_history_record(
    p: Paper,
    push_date: dt.date,
    *,
    run_type: str = "",
) -> dict[str, Any]:
    """
    功能说明：
        执行 `_paper_history_record` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - p: 业务输入参数。
        - push_date: 时间范围或日期参数。
    返回值：
        返回类型为 `dict[str, Any]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    keywords = _normalize_keywords(p.keywords)
    return {
        "uid": _paper_uid(p),
        "push_date": push_date.isoformat(),
        "run_type": str(run_type or "").strip(),
        "title": p.title.strip(),
        "url": p.url.strip(),
        "venue": (p.venue or "").strip(),
        "publisher": (p.publisher or "").strip(),
        "source": (p.source or "").strip(),
        "published_date": p.published_date.isoformat() if p.published_date else "",
        "keywords": keywords,
        "keyword_categories": _keyword_categories(keywords),
    }


def _sorted_counts(values: Iterable[str]) -> list[tuple[str, int]]:
    """
    功能说明：
        执行 `_sorted_counts` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - values: 业务输入参数。
    返回值：
        返回类型为 `list[tuple[str, int]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    counts: dict[str, int] = {}
    for v in values:
        key = (v or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))


def _format_top_counts(
    items: list[tuple[str, int]],
    *,
    top_n: int = 8,
    key_transform: Optional[Callable[[str], str]] = None,
) -> str:
    """
    功能说明：
        执行 `_format_top_counts` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - items: 待处理的数据集合。
        - top_n: 业务输入参数。
        - key_transform: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not items:
        return "无"
    parts: list[str] = []
    for key, cnt in items[:top_n]:
        label = key_transform(key) if key_transform else key
        parts.append(f"{label}={cnt}")
    return ", ".join(parts)


def _render_count_chart_html(
    title: str,
    items: list[tuple[str, int]],
    *,
    top_n: int = 8,
    color: str = "#1f7a8c",
) -> str:
    """
    功能说明：
        渲染 count chart html 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - title: 业务输入参数。
        - items: 待处理的数据集合。
        - top_n: 业务输入参数。
        - color: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    picked = items[: max(0, int(top_n))]
    if not picked:
        return f'<h3 style="margin:0 0 10px 0;font-size:16px;line-height:1.4;color:#0f172a;">{html.escape(title)}</h3><p>无数据</p>'

    max_count = max(cnt for _, cnt in picked) if picked else 0
    max_count = max(1, max_count)

    rows: list[str] = [
        f'<h3 style="margin:0 0 10px 0;font-size:16px;line-height:1.4;color:#0f172a;">{html.escape(title)}</h3>',
        '<table role="presentation" cellspacing="0" cellpadding="0" '
        'style="border-collapse:collapse;width:100%;max-width:840px;">',
    ]
    for label, cnt in picked:
        ratio = float(cnt) / float(max_count)
        pct = max(4, int(round(ratio * 100)))
        rows.extend(
            [
                "<tr>",
                f'<td style="padding:5px 10px 5px 0;font-size:12px;white-space:nowrap;">{html.escape(label)}</td>',
                '<td style="padding:5px 10px;width:100%;">'
                '<table role="presentation" cellspacing="0" cellpadding="0" '
                'style="border-collapse:collapse;width:100%;background:#e9ecef;">'
                f'<tr><td style="height:12px;width:{pct}%;background:{color};"></td>'
                "<td></td></tr></table>"
                "</td>",
                f'<td style="padding:5px 0 5px 0;font-size:12px;text-align:right;white-space:nowrap;">{cnt}</td>',
                "</tr>",
            ]
        )
    rows.append("</table>")
    return "\n".join(rows)


def _matplotlib_pyplot():
    """
    功能说明：
        执行 `_matplotlib_pyplot` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - 无。
    返回值：
        按函数实现返回相应结果（详见类型提示或调用方约定）。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore

        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei",
            "SimHei",
            "Arial Unicode MS",
            "DejaVu Sans",
        ]
        return plt
    except Exception:
        return None


def _render_pie_chart_png(
    title: str,
    items: list[tuple[str, int]],
    *,
    top_n: int = 6,
) -> Optional[bytes]:
    """
    功能说明：
        渲染 pie chart png 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - title: 业务输入参数。
        - items: 待处理的数据集合。
        - top_n: 业务输入参数。
    返回值：
        返回类型为 `Optional[bytes]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    picked = items[: max(1, int(top_n))]
    if not picked:
        return None
    rest = items[max(1, int(top_n)) :]
    rest_sum = sum(cnt for _, cnt in rest)
    if rest_sum > 0:
        picked = picked + [("Other", rest_sum)]

    labels = [k for k, _ in picked]
    values = [v for _, v in picked]
    if not any(values):
        return None

    plt = _matplotlib_pyplot()
    if plt is None:
        return None

    fig, ax = plt.subplots(figsize=(7.2, 4.8), dpi=160)
    ax.pie(
        values,
        labels=labels,
        autopct=lambda p: f"{p:.1f}%",
        startangle=140,
        textprops={"fontsize": 9},
    )
    ax.axis("equal")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _render_bar_chart_png(
    title: str,
    items: list[tuple[str, int]],
    *,
    top_n: int = 10,
    color: str = "#1d4ed8",
) -> Optional[bytes]:
    """
    功能说明：
        渲染 bar chart png 内容，输出 HTML 或文本片段供模板拼装。
    参数说明：
        - title: 业务输入参数。
        - items: 待处理的数据集合。
        - top_n: 业务输入参数。
        - color: 业务输入参数。
    返回值：
        返回类型为 `Optional[bytes]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    picked = items[: max(1, int(top_n))]
    if not picked:
        return None

    labels = [k for k, _ in picked][::-1]
    values = [v for _, v in picked][::-1]
    if not any(values):
        return None

    plt = _matplotlib_pyplot()
    if plt is None:
        return None

    fig_h = max(3.4, min(7.8, 2.0 + 0.32 * len(labels)))
    fig, ax = plt.subplots(figsize=(8.2, fig_h), dpi=160)
    bars = ax.barh(range(len(labels)), values, color=color, alpha=0.9)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.grid(axis="x", alpha=0.22, linestyle="--")
    ax.set_axisbelow(True)
    max_v = max(values)
    ax.set_xlim(0, max_v * 1.18 if max_v > 0 else 1)

    for bar, v in zip(bars, values):
        ax.text(
            bar.get_width() + max_v * 0.02,
            bar.get_y() + bar.get_height() / 2.0,
            str(v),
            va="center",
            fontsize=9,
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _cn_join(parts: Iterable[str], *, max_items: int = 3) -> str:
    """
    功能说明：
        执行 `_cn_join` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - parts: 业务输入参数。
        - max_items: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    values = [str(p).strip() for p in parts if str(p).strip()]
    if max_items > 0:
        values = values[:max_items]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]}和{values[1]}"
    return "、".join(values[:-1]) + f"和{values[-1]}"


def _weekly_category_priority(name: str) -> int:
    """
    功能说明：
        执行 `_weekly_category_priority` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - name: 业务输入参数。
    返回值：
        返回类型为 `int`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    priorities = {
        "血压监测": 0,
        "葡萄糖监测": 0,
        "可穿戴形态": 1,
        "柔性/电子器件": 2,
        "传感机制": 3,
        "其他": 9,
    }
    return priorities.get((name or "").strip(), 5)


def _weekly_focus_categories(
    category_counts: list[tuple[str, int]],
    *,
    max_items: int = 2,
) -> list[tuple[str, int]]:
    """
    功能说明：
        执行 `_weekly_focus_categories` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - category_counts: 业务输入参数。
        - max_items: 业务输入参数。
    返回值：
        返回类型为 `list[tuple[str, int]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not category_counts:
        return []
    ordered = sorted(
        category_counts,
        key=lambda item: (_weekly_category_priority(item[0]), -item[1], item[0]),
    )
    return ordered[:max_items]


def _weekly_chart_category_name(name: str) -> str:
    """
    功能说明：
        执行 `_weekly_chart_category_name` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - name: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    mapping = {
        "血压监测": "Blood Pressure",
        "葡萄糖监测": "Glucose",
        "可穿戴形态": "Wearable Form",
        "柔性/电子器件": "Flexible Electronics",
        "传感机制": "Sensing Mechanism",
        "其他": "Other",
    }
    return mapping.get((name or "").strip(), (name or "").strip() or "Other")


def _weekly_primary_category(
    row: dict[str, Any], category_order: dict[str, int]
) -> str:
    """
    功能说明：
        执行 `_weekly_primary_category` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - row: 待处理的数据集合。
        - category_order: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    keyword_categories = _keyword_categories(_normalize_keywords(row.get("keywords")))
    categories = keyword_categories or row.get("keyword_categories") or []
    if isinstance(categories, str):
        categories = [categories]
    if not isinstance(categories, list):
        return "其他"
    cleaned = _unique_clean_list(categories)
    if not cleaned:
        return "其他"
    ranked = [
        (
            _weekly_category_priority(category),
            idx,
            category_order.get(category, 999),
            category,
        )
        for idx, category in enumerate(cleaned)
    ]
    return min(ranked)[-1]


def _weekly_editor_note(
    total: int,
    category_counts: list[tuple[str, int]],
    keyword_counts: list[tuple[str, int]],
    source_counts: list[tuple[str, int]],
    *,
    recent_count: int,
) -> str:
    """
    功能说明：
        执行 `_weekly_editor_note` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - total: 业务输入参数。
        - category_counts: 业务输入参数。
        - keyword_counts: 关键词或关键词集合。
        - source_counts: 业务输入参数。
        - recent_count: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if total <= 0:
        return "本周没有新增推送，适合把时间留给前面几周已经筛出的重点论文。"
    cat_text = _cn_join(
        [name for name, _ in _weekly_focus_categories(category_counts, max_items=2)],
        max_items=2,
    )
    keyword_text = _cn_join([name for name, _ in keyword_counts[:3]], max_items=3)
    source_name = source_counts[0][0] if source_counts else "多源"
    parts: list[str] = []
    if cat_text:
        parts.append(f"本周推送重心落在{cat_text}")
    if keyword_text:
        parts.append(f"高频关键词集中在{keyword_text}")
    if recent_count > 0:
        parts.append(f"其中有{recent_count}篇是近30天发表的新论文")
    if source_name:
        parts.append(f"{source_name}是本周最主要的检索来源")
    return "；".join(parts) + "。"


def _weekly_metric_card_html(
    label: str,
    value: str,
    note: str,
    *,
    bg: str,
    accent: str,
    fg: str,
) -> str:
    """
    功能说明：
        执行 `_weekly_metric_card_html` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - label: 业务输入参数。
        - value: 业务输入参数。
        - note: 业务输入参数。
        - bg: 业务输入参数。
        - accent: 业务输入参数。
        - fg: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    return (
        '<td valign="top" width="25%" style="width:25%;padding:0 8px 0 0;">'
        '<div style="height:100%;padding:16px 16px 14px;border-radius:18px;'
        f'background:{bg};border:1px solid rgba(15,23,42,0.06);border-top:4px solid {accent};">'
        f'<div style="font-size:12px;font-weight:900;letter-spacing:0.08em;color:{accent};">{html.escape(label)}</div>'
        f'<div style="margin-top:10px;font-size:28px;line-height:1.15;font-weight:900;color:{fg};">{html.escape(value)}</div>'
        f'<div style="margin-top:8px;font-size:13px;line-height:1.6;color:{fg};opacity:0.88;">{html.escape(note)}</div>'
        "</div></td>"
    )


def _weekly_record_score(
    row: dict[str, Any],
    *,
    end_date: dt.date,
    category_counts_map: dict[str, int],
) -> float:
    """
    功能说明：
        执行 `_weekly_record_score` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - row: 待处理的数据集合。
        - end_date: 时间范围或日期参数。
        - category_counts_map: 业务输入参数。
    返回值：
        返回类型为 `float`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    push_date = _parse_date(str(row.get("push_date") or "").strip()) or end_date
    published_date = (
        _parse_date(str(row.get("published_date") or "").strip()) or push_date
    )
    primary = _weekly_primary_category(row, {})
    category_bonus = float(category_counts_map.get(primary, 0)) * 2.5
    source_bonus = {
        "pubmed": 4.0,
        "crossref": 3.0,
        "arxiv": 2.5,
        "ieee": 2.5,
        "semantic_scholar": 1.0,
    }.get(str(row.get("source") or "").strip().lower(), 0.0)
    push_bonus = max(0.0, 10.0 - float((end_date - push_date).days))
    pub_bonus = max(0.0, 12.0 - float((end_date - published_date).days) / 7.0)
    return category_bonus + source_bonus + push_bonus + pub_bonus


def _weekly_spotlight_rows(
    rows: list[dict[str, Any]],
    *,
    end_date: dt.date,
    category_counts: list[tuple[str, int]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """
    功能说明：
        执行 `_weekly_spotlight_rows` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - rows: 待处理的数据集合。
        - end_date: 时间范围或日期参数。
        - category_counts: 业务输入参数。
        - limit: 业务输入参数。
    返回值：
        返回类型为 `list[dict[str, Any]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not rows:
        return []
    category_order = {name: idx for idx, (name, _) in enumerate(category_counts)}
    category_counts_map = {name: count for name, count in category_counts}
    ranked = sorted(
        rows,
        key=lambda row: (
            _weekly_record_score(
                row, end_date=end_date, category_counts_map=category_counts_map
            ),
            str(row.get("push_date") or ""),
            str(row.get("title") or ""),
        ),
        reverse=True,
    )
    picks: list[dict[str, Any]] = []
    used_categories: set[str] = set()
    target = min(limit, len(ranked))
    for row in ranked:
        primary = _weekly_primary_category(row, category_order)
        if primary in used_categories and len(ranked) > target:
            continue
        picks.append(row)
        used_categories.add(primary)
        if len(picks) >= target:
            return picks
    for row in ranked:
        uid = str(row.get("uid") or "").strip()
        if any(str(existing.get("uid") or "").strip() == uid for existing in picks):
            continue
        picks.append(row)
        if len(picks) >= target:
            break
    return picks


def _weekly_spotlight_reason(
    row: dict[str, Any],
    *,
    end_date: dt.date,
    category_order: dict[str, int],
) -> str:
    """
    功能说明：
        执行 `_weekly_spotlight_reason` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - row: 待处理的数据集合。
        - end_date: 时间范围或日期参数。
        - category_order: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    primary = _weekly_primary_category(row, category_order)
    source_name = _source_display_name(str(row.get("source") or "").strip())
    published_date = _parse_date(str(row.get("published_date") or "").strip())
    keywords = row.get("keywords") or []
    keyword_text = _cn_join(keywords, max_items=2)
    if primary != "其他" and published_date and (end_date - published_date).days <= 30:
        return f"这篇能代表本周{primary}方向，而且发表时间较新。"
    if primary != "其他" and keyword_text:
        return f"这篇可以当作本周{primary}方向的入口，关键词集中在{keyword_text}。"
    if source_name and keyword_text:
        return f"{source_name}命中的代表项之一，适合从{keyword_text}这条线索切进去。"
    if primary != "其他":
        return f"这篇是本周{primary}方向里更值得优先回看的代表项。"
    return "这篇适合作为本周回看列表里的优先入口。"


def _weekly_signal_items(
    *,
    total: int,
    avg_per_day: float,
    source_counts: list[tuple[str, int]],
    category_counts: list[tuple[str, int]],
    keyword_counts: list[tuple[str, int]],
    pub_dates: list[dt.date],
    end_date: dt.date,
) -> list[tuple[str, str, str, str, str]]:
    """
    功能说明：
        执行 `_weekly_signal_items` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - total: 业务输入参数。
        - avg_per_day: 业务输入参数。
        - source_counts: 业务输入参数。
        - category_counts: 业务输入参数。
        - keyword_counts: 关键词或关键词集合。
        - pub_dates: 时间范围或日期参数。
        - end_date: 时间范围或日期参数。
    返回值：
        返回类型为 `list[tuple[str, str, str, str, str]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    signals: list[tuple[str, str, str, str, str]] = []
    focus_categories = _weekly_focus_categories(category_counts, max_items=1)
    if focus_categories:
        top_category, top_count = focus_categories[0]
        signals.append(
            (
                "主题重心",
                f"{top_category}是本周最集中的主主题，共有 {top_count}/{max(total, 1)} 篇论文落在这一方向，说明本周热点仍明显围绕这条线展开。",
                "#eff6ff",
                "#3b82f6",
                "#1e3a8a",
            )
        )
    if keyword_counts:
        keyword_text = _cn_join([name for name, _ in keyword_counts[:3]], max_items=3)
        signals.append(
            (
                "关键词脉冲",
                f"{keyword_text}在本周重复出现得最多，适合拿来判断最近几天筛选结果背后的技术重心。",
                "#f5f3ff",
                "#8b5cf6",
                "#5b21b6",
            )
        )
    if source_counts:
        source_name, source_count = source_counts[0]
        signals.append(
            (
                "检索结构",
                f"{source_name}贡献了最多推送结果（{source_count}篇），说明本周主要增量仍来自这一数据库覆盖到的文献面。",
                "#ecfeff",
                "#0891b2",
                "#164e63",
            )
        )
    if pub_dates:
        recent_count = sum(1 for d in pub_dates if (end_date - d).days <= 30)
        signals.append(
            (
                "发表新鲜度",
                f"本周覆盖的论文发表日期跨度为 {min(pub_dates).isoformat()} 到 {max(pub_dates).isoformat()}；其中近30天发表的有 {recent_count} 篇。",
                "#ecfdf5",
                "#10b981",
                "#065f46",
            )
        )
    if total > 0:
        signals.append(
            (
                "推送节奏",
                f"这周平均每个推送日约 {avg_per_day:.2f} 篇，适合把周报当作回看入口，而不是逐篇从头翻日报。",
                "#fff7ed",
                "#f59e0b",
                "#9a3412",
            )
        )
    return signals[:4]


def _weekly_signal_card_html(
    title: str,
    body: str,
    *,
    bg: str,
    accent: str,
    fg: str,
) -> str:
    """
    功能说明：
        执行 `_weekly_signal_card_html` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - title: 业务输入参数。
        - body: 业务输入参数。
        - bg: 业务输入参数。
        - accent: 业务输入参数。
        - fg: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    return (
        '<div style="margin-top:12px;padding:16px 18px;border-radius:18px;'
        f'background:{bg};border-left:5px solid {accent};box-shadow:0 8px 20px rgba(15,23,42,0.04);">'
        f'<div style="font-size:12px;font-weight:900;letter-spacing:0.08em;color:{accent};">{html.escape(title)}</div>'
        f'<div style="margin-top:10px;font-size:15px;line-height:1.76;color:{fg};">{html.escape(body)}</div>'
        "</div>"
    )


def _weekly_spotlight_card_html(
    row: dict[str, Any],
    *,
    reason: str,
    category_order: dict[str, int],
) -> str:
    """
    功能说明：
        执行 `_weekly_spotlight_card_html` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - row: 待处理的数据集合。
        - reason: 业务输入参数。
        - category_order: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    title = html.escape(str(row.get("title") or "(无标题)").strip())
    url = html.escape(str(row.get("url") or "").strip())
    venue = html.escape(str(row.get("venue") or "未标注").strip())
    push_date = html.escape(str(row.get("push_date") or "").strip())
    published_date = html.escape(str(row.get("published_date") or "").strip())
    source_name = _source_display_name(str(row.get("source") or "").strip())
    theme = _weekly_primary_category(row, category_order)
    title_html = (
        f'<a href="{url}" style="color:#0f3d91;text-decoration:none;">{title}</a>'
        if url
        else title
    )
    badges: list[str] = []
    if theme and theme != "其他":
        badges.append(_html_badge(theme, bg="#f5f3ff", fg="#6d28d9", border="#c4b5fd"))
    if source_name:
        badges.append(
            _html_badge(source_name, bg="#ecfdf5", fg="#166534", border="#86efac")
        )
    if push_date:
        badges.append(
            _html_badge(
                f"推送 {push_date}", bg="#fff7ed", fg="#c2410c", border="#fdba74"
            )
        )
    meta_parts = [venue]
    if published_date:
        meta_parts.append(f"发表 {published_date}")
    return (
        '<div style="margin-top:12px;padding:18px;border-radius:20px;background:#ffffff;'
        'border:1px solid #dbe3ee;box-shadow:0 10px 24px rgba(15,23,42,0.05);">'
        f"<div>{''.join(badges)}</div>"
        f'<div style="margin-top:12px;font-size:19px;line-height:1.55;font-weight:900;color:#0f172a;">{title_html}</div>'
        f"<div style=\"margin-top:10px;font-size:13px;line-height:1.7;color:#475569;\">{' &nbsp; '.join(html.escape(p) for p in meta_parts if p)}</div>"
        '<div style="margin-top:12px;padding:12px 14px;border-radius:14px;background:#f8fafc;border-left:4px solid #3b82f6;">'
        '<div style="font-size:12px;font-weight:900;letter-spacing:0.08em;color:#1d4ed8;">为什么优先回看</div>'
        f'<div style="margin-top:8px;font-size:15px;line-height:1.75;color:#334155;">{html.escape(reason)}</div>'
        "</div></div>"
    )


def _weekly_appendix_table_html(
    rows: list[dict[str, Any]], *, category_order: dict[str, int]
) -> str:
    """
    功能说明：
        执行 `_weekly_appendix_table_html` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - rows: 待处理的数据集合。
        - category_order: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not rows:
        return ""
    parts = [
        '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" '
        'style="width:100%;border-collapse:collapse;background:#ffffff;border:1px solid #dbe3ee;border-radius:16px;overflow:hidden;">',
        "<colgroup>"
        '<col style="width:48px;">'
        '<col style="width:112px;">'
        "<col>"
        '<col style="width:136px;">'
        '<col style="width:220px;">'
        "</colgroup>",
        '<tr style="background:#f8fafc;">'
        '<td style="padding:12px 10px;font-size:12px;font-weight:900;color:#475569;">#</td>'
        '<td style="padding:12px 10px;font-size:12px;font-weight:900;color:#475569;">推送日</td>'
        '<td style="padding:12px 10px;font-size:12px;font-weight:900;color:#475569;">论文</td>'
        '<td style="padding:12px 10px;font-size:12px;font-weight:900;color:#475569;">主题</td>'
        '<td style="padding:12px 10px;font-size:12px;font-weight:900;color:#475569;">期刊</td>'
        "</tr>",
    ]
    for idx, row in enumerate(rows, start=1):
        title = html.escape(str(row.get("title") or "(无标题)").strip())
        url = html.escape(str(row.get("url") or "").strip())
        push_date = html.escape(str(row.get("push_date") or "").strip())
        theme = html.escape(_weekly_primary_category(row, category_order))
        venue = html.escape(str(row.get("venue") or "未标注").strip())
        title_html = (
            f'<a href="{url}" style="color:#0f3d91;text-decoration:none;">{title}</a>'
            if url
            else title
        )
        bg = "#ffffff" if idx % 2 else "#fbfdff"
        parts.append(
            f'<tr style="background:{bg};">'
            f'<td style="padding:12px 10px;font-size:13px;color:#334155;border-top:1px solid #e2e8f0;">{idx}</td>'
            f'<td style="padding:12px 10px;font-size:13px;color:#334155;border-top:1px solid #e2e8f0;white-space:nowrap;">{push_date}</td>'
            f'<td style="padding:12px 10px;font-size:14px;line-height:1.6;color:#0f172a;border-top:1px solid #e2e8f0;">{title_html}</td>'
            f'<td style="padding:12px 10px;font-size:13px;color:#334155;border-top:1px solid #e2e8f0;white-space:nowrap;">{theme}</td>'
            f'<td style="padding:12px 10px;font-size:13px;color:#334155;border-top:1px solid #e2e8f0;">{venue}</td>'
            "</tr>"
        )
    parts.append("</table>")
    return "".join(parts)


def build_weekly_summary_email(
    run_date: dt.date,
    history_records: list[dict[str, Any]],
    *,
    lookback_days: int = 7,
    max_items: int = 120,
) -> tuple[str, str, str, list[tuple[str, bytes, str]]]:
    """
    功能说明：
        构建 weekly summary email 相关内容，用于邮件展示、摘要输出或主流程编排。
    参数说明：
        - run_date: 时间范围或日期参数。
        - history_records: 业务输入参数。
        - lookback_days: 业务输入参数。
        - max_items: 业务输入参数。
    返回值：
        返回类型为 `tuple[str, str, str, list[tuple[str, bytes, str]]]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    days = max(1, int(lookback_days))
    start_date = run_date - dt.timedelta(days=days - 1)
    end_date = run_date

    weekly: list[dict[str, Any]] = []
    for row in history_records:
        push_date = _parse_date(str(row.get("push_date") or "").strip())
        if not push_date:
            continue
        if push_date < start_date or push_date > end_date:
            continue
        keywords = _normalize_keywords(row.get("keywords"))
        categories = row.get("keyword_categories") or []
        if isinstance(categories, str):
            categories = [categories]
        if not isinstance(categories, list):
            categories = []
        normalized_categories = _unique_clean_list(categories)
        if not normalized_categories:
            normalized_categories = _keyword_categories(keywords)

        weekly.append(
            {
                "uid": str(row.get("uid") or "").strip(),
                "push_date": push_date.isoformat(),
                "title": str(row.get("title") or "").strip(),
                "url": str(row.get("url") or "").strip(),
                "venue": str(row.get("venue") or "").strip(),
                "publisher": str(row.get("publisher") or "").strip(),
                "source": str(row.get("source") or "").strip(),
                "published_date": str(row.get("published_date") or "").strip(),
                "keywords": keywords,
                "keyword_categories": normalized_categories,
            }
        )

    weekly.sort(
        key=lambda row: (row.get("push_date") or "", row.get("title") or ""),
        reverse=True,
    )
    total = len(weekly)
    shown_total = min(total, max(1, int(max_items)))
    listed = weekly[:shown_total]

    subject = (
        f"每周论文总结 {start_date.isoformat()} ~ {end_date.isoformat()}（{total}篇）"
    )
    inline_images: list[tuple[str, bytes, str]] = []

    push_days = sorted(set(row["push_date"] for row in weekly))
    source_counts = _sorted_counts(
        _source_display_name(row.get("source") or "") for row in weekly
    )
    venue_counts = _sorted_counts((row.get("venue") or "未标注") for row in weekly)
    keyword_counts = _sorted_counts(
        k for row in weekly for k in (row.get("keywords") or [])
    )
    primary_categories = [_weekly_primary_category(row, {}) for row in weekly]
    category_counts = _sorted_counts(primary_categories)
    category_chart_counts = [
        (_weekly_chart_category_name(name), count) for name, count in category_counts
    ]

    pub_dates: list[dt.date] = []
    for row in weekly:
        d = _parse_date(str(row.get("published_date") or "").strip())
        if d:
            pub_dates.append(d)

    avg_per_day = 0.0 if not push_days else (total / len(push_days))
    recent_pub_count = sum(1 for d in pub_dates if (end_date - d).days <= 30)
    category_order = {name: idx for idx, (name, _) in enumerate(category_counts)}
    lead = _weekly_editor_note(
        total,
        category_counts,
        keyword_counts,
        source_counts,
        recent_count=recent_pub_count,
    )
    focus_categories = _weekly_focus_categories(category_counts, max_items=1)
    top_category = focus_categories[0] if focus_categories else ("暂无明显热点", 0)
    metric_specs = [
        (
            "本周推送",
            str(total),
            f"覆盖 {len(push_days)} 个推送日",
            "#eff6ff",
            "#3b82f6",
            "#1e3a8a",
        ),
        (
            "平均节奏",
            f"{avg_per_day:.2f}",
            "每个推送日平均篇数",
            "#ecfeff",
            "#0891b2",
            "#164e63",
        ),
        (
            "主热点",
            top_category[0],
            f"{top_category[1]} 篇论文",
            "#f5f3ff",
            "#8b5cf6",
            "#5b21b6",
        ),
        (
            "新鲜论文",
            str(recent_pub_count),
            "近 30 天发表",
            "#ecfdf5",
            "#10b981",
            "#065f46",
        ),
    ]
    spotlight_rows = _weekly_spotlight_rows(
        listed,
        end_date=end_date,
        category_counts=category_counts,
        limit=3,
    )
    signals = _weekly_signal_items(
        total=total,
        avg_per_day=avg_per_day,
        source_counts=source_counts,
        category_counts=category_counts,
        keyword_counts=keyword_counts,
        pub_dates=pub_dates,
        end_date=end_date,
    )
    text_lines: list[str] = [subject, "", lead, ""]
    text_lines.append("关键数字：")
    for label, value, note, *_ in metric_specs:
        text_lines.append(f"- {label}: {value}（{note}）")
    text_lines.append("")
    if spotlight_rows:
        text_lines.append("本周优先回看：")
        for idx, row in enumerate(spotlight_rows, start=1):
            reason = _weekly_spotlight_reason(
                row,
                end_date=end_date,
                category_order=category_order,
            )
            text_lines.append(f"{idx}. {row.get('title') or '(无标题)'}")
            text_lines.append(f"   理由: {reason}")
        text_lines.append("")
    if signals:
        text_lines.append("本周可借鉴信号：")
        for title, body, *_ in signals:
            text_lines.append(f"- {title}: {body}")
        text_lines.append("")
    if total == 0:
        text_lines.append("本周没有新的推送论文。")
    else:
        if shown_total < total:
            text_lines.append(
                f"完整论文清单仅展示前 {shown_total} 篇（其余 {total - shown_total} 篇已省略）。"
            )
            text_lines.append("")
        text_lines.append("完整论文清单：")
        for idx, row in enumerate(listed, start=1):
            theme = _weekly_primary_category(row, category_order)
            text_lines.append(
                f"{idx}. [{row.get('push_date') or ''}] {row.get('title') or '(无标题)'}"
            )
            text_lines.append(
                f"   主题: {theme} | 期刊: {row.get('venue') or '未标注'}"
            )
            if row.get("url"):
                text_lines.append(f"   链接: {row.get('url')}")
            text_lines.append("")

    chart_specs: list[tuple[str, str, list[tuple[str, int]], str, int, str]] = [
        ("weekly_source_pie", "Source Mix", source_counts, "pie", 8, "#1d4ed8"),
        (
            "weekly_category_pie",
            "Topic Mix",
            category_chart_counts,
            "pie",
            8,
            "#2b8a3e",
        ),
        (
            "weekly_keyword_bar",
            "Frequent Keywords",
            keyword_counts,
            "bar",
            12,
            "#9c36b5",
        ),
        ("weekly_venue_bar", "Frequent Venues", venue_counts, "bar", 10, "#e67700"),
    ]
    chart_explanations = {
        "Source Mix": "展示本周候选论文主要来自哪些检索来源。",
        "Topic Mix": "展示本周论文主主题分布，方便快速判断关注重心。",
        "Frequent Keywords": "展示本周反复出现最多的关键词，帮助把握近期技术热点。",
        "Frequent Venues": "展示本周最常出现的期刊或会议，方便判断常见发表出口。",
    }
    chart_cards: list[str] = []
    for cid, chart_title, items, kind, top_n, color in chart_specs:
        png_bytes: Optional[bytes] = None
        if kind == "pie":
            png_bytes = _render_pie_chart_png(chart_title, items, top_n=top_n)
        else:
            png_bytes = _render_bar_chart_png(
                chart_title, items, top_n=top_n, color=color
            )

        if png_bytes:
            inline_images.append((cid, png_bytes, "png"))
            cell_html = (
                '<table role="presentation" cellspacing="0" cellpadding="0" '
                'style="border-collapse:collapse;width:100%;border:1px solid #e5e7eb;border-radius:6px;">'
                f'<tr><td style="padding:8px 10px 4px 10px;"><b>{html.escape(chart_title)}</b></td></tr>'
                f'<tr><td style="padding:4px 10px 10px 10px;"><img src="cid:{cid}" alt="{html.escape(chart_title)}" '
                'style="display:block;width:100%;height:auto;border:1px solid #d9d9d9;border-radius:6px;" /></td></tr>'
                "</table>"
            )
        else:
            cell_html = _render_count_chart_html(
                chart_title, items, top_n=top_n, color=color
            )
        chart_cards.append(
            '<div style="padding:16px;border-radius:18px;background:#ffffff;border:1px solid #dbe3ee;'
            'box-shadow:0 8px 20px rgba(15,23,42,0.04);height:100%;">'
            + cell_html
            + f"<div style=\"margin-top:10px;font-size:13px;line-height:1.65;color:#475569;\">{html.escape(chart_explanations.get(chart_title, ''))}</div>"
            + "</div>"
        )

    keyword_badges = "".join(
        _html_badge(name, bg="#dbeafe", fg="#1d4ed8", border="#93c5fd")
        for name, _ in keyword_counts[:5]
    )
    html_lines: list[str] = [
        "<html>",
        "<body style=\"margin:0;padding:0;background:#eef2f7;color:#0f172a;font-family:'Segoe UI',Arial,'PingFang SC','Microsoft YaHei',sans-serif;\">",
        '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="width:100%;border-collapse:collapse;background:#eef2f7;">',
        '<tr><td align="center" style="padding:28px 14px;">',
        '<table role="presentation" cellspacing="0" cellpadding="0" width="960" style="width:960px;max-width:960px;border-collapse:separate;background:#ffffff;border:1px solid #d7e0ea;border-radius:24px;overflow:hidden;">',
        '<tr><td bgcolor="#f8fafc" style="padding:30px 32px;background-color:#f8fafc;background:#f8fafc;background-image:linear-gradient(135deg,#f8fafc 0%,#dbeafe 100%);border-bottom:1px solid #dbe3ee;">',
        '<div style="font-size:12px;font-weight:900;letter-spacing:0.14em;text-transform:uppercase;color:#1d4ed8;">Weekly Review</div>',
        f'<div style="margin-top:10px;font-size:30px;line-height:1.2;font-weight:900;color:#0f172a;">{html.escape(subject)}</div>',
        f'<div style="margin-top:12px;font-size:16px;line-height:1.75;color:#334155;">{html.escape(lead)}</div>',
        '<div style="margin-top:18px;">'
        + _html_badge(
            f"{total} 篇周内推送", bg="#dbeafe", fg="#1d4ed8", border="#93c5fd"
        )
        + _html_badge(
            f"{start_date.isoformat()} ~ {end_date.isoformat()}",
            bg="#dcfce7",
            fg="#166534",
            border="#86efac",
        )
        + _html_badge(
            f"{len(push_days)} 个推送日", bg="#fff7ed", fg="#c2410c", border="#fdba74"
        )
        + "</div>",
        (
            f'<div style="margin-top:14px;">{keyword_badges}</div>'
            if keyword_badges
            else ""
        ),
        "</td></tr>",
        '<tr><td style="padding:24px 24px 30px;background:#ffffff;">',
        '<div style="font-size:22px;line-height:1.35;font-weight:900;color:#0f172a;">本周核心数字</div>',
        '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="width:100%;border-collapse:separate;margin-top:12px;table-layout:fixed;">',
        "<tr>",
        "".join(
            _weekly_metric_card_html(label, value, note, bg=bg, accent=accent, fg=fg)
            for label, value, note, bg, accent, fg in metric_specs
        ),
        "</tr></table>",
    ]

    if total <= 0:
        html_lines.extend(
            [
                '<div style="margin-top:18px;padding:22px;border-radius:18px;background:#f8fafc;border:1px solid #dbe3ee;">',
                '<div style="font-size:18px;font-weight:900;color:#0f172a;">本周没有新的推送论文</div>',
                '<div style="margin-top:8px;font-size:15px;line-height:1.75;color:#475569;">这封周报先保留了版式骨架；一旦周内有累计推送，就会自动填充热点、图表统计和完整论文清单。</div>',
                "</div>",
            ]
        )
    else:
        html_lines.extend(
            [
                '<div style="margin-top:22px;font-size:22px;line-height:1.35;font-weight:900;color:#0f172a;">本周优先回看</div>',
            ]
        )
        for row in spotlight_rows:
            html_lines.append(
                _weekly_spotlight_card_html(
                    row,
                    reason=_weekly_spotlight_reason(
                        row,
                        end_date=end_date,
                        category_order=category_order,
                    ),
                    category_order=category_order,
                )
            )

        html_lines.extend(
            [
                '<div style="margin-top:24px;font-size:22px;line-height:1.35;font-weight:900;color:#0f172a;">图表统计</div>',
                '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="width:100%;border-collapse:separate;table-layout:fixed;margin-top:12px;">',
            ]
        )
        for i in range(0, len(chart_cards), 2):
            html_lines.append("<tr>")
            for j in range(2):
                if i + j < len(chart_cards):
                    pad = "0 6px 0 0" if j == 0 else "0 0 0 6px"
                    html_lines.append(
                        f'<td valign="top" width="50%" style="width:50%;padding:{pad};">{chart_cards[i + j]}</td>'
                    )
                else:
                    html_lines.append(
                        '<td width="50%" style="width:50%;padding:0 0 0 6px;"></td>'
                    )
            html_lines.append("</tr>")
            if i + 2 < len(chart_cards):
                html_lines.append(
                    '<tr><td colspan="2" style="height:12px;font-size:0;line-height:0;">&nbsp;</td></tr>'
                )
        html_lines.append("</table>")

        html_lines.extend(
            [
                '<div style="margin-top:24px;font-size:22px;line-height:1.35;font-weight:900;color:#0f172a;">本周可借鉴信号</div>',
            ]
        )
        for title, body, bg, accent, fg in signals:
            html_lines.append(
                _weekly_signal_card_html(
                    title,
                    body,
                    bg=bg,
                    accent=accent,
                    fg=fg,
                )
            )

        html_lines.extend(
            [
                '<div style="margin-top:24px;font-size:22px;line-height:1.35;font-weight:900;color:#0f172a;">完整论文清单</div>',
            ]
        )
        if shown_total < total:
            html_lines.append(
                f'<div style="margin-top:10px;font-size:13px;line-height:1.7;color:#64748b;">当前完整论文清单只展示前 {shown_total} 篇，其余 {total - shown_total} 篇已省略。</div>'
            )
        html_lines.append(
            f'<div style="margin-top:12px;">{_weekly_appendix_table_html(listed, category_order=category_order)}</div>'
        )

    html_lines.extend(
        [
            "</td></tr>",
            "</table>",
            "</td></tr>",
            "</table>",
            "</body>",
            "</html>",
        ]
    )
    return subject, "\n".join(text_lines), "\n".join(html_lines), inline_images


def send_email(
    email_cfg: dict[str, Any],
    subject: str,
    text_body: str,
    html_body: str,
    inline_images: Optional[list[tuple[str, bytes, str]]] = None,
) -> None:
    """
    功能说明：
        按 SMTP 配置发送邮件，支持文本和 HTML 内容。
    参数说明：
        - email_cfg: 配置字典或配置对象。
        - subject: 业务输入参数。
        - text_body: 业务输入参数。
        - html_body: 业务输入参数。
        - inline_images: 业务输入参数。
    返回值：
        返回类型为 `None`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    smtp_host = (email_cfg.get("smtp_host") or "").strip()
    smtp_port = int(email_cfg.get("smtp_port") or 587)
    smtp_user = (email_cfg.get("username") or "").strip()

    password = (email_cfg.get("password") or "").strip()
    if not password:
        password_env = (email_cfg.get("password_env") or "").strip()
        if password_env:
            password = _env_get(password_env)

    from_addr = (email_cfg.get("from") or smtp_user).strip()
    to_addrs = email_cfg.get("to") or []
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    to_addrs = [a.strip() for a in to_addrs if a and a.strip()]

    if not smtp_host or not from_addr or not to_addrs:
        raise ValueError("email閰嶇疆涓嶅畬鏁达細鑷冲皯闇€瑕?smtp_host銆乫rom銆乼o")

    use_tls = bool(email_cfg.get("use_tls", True))
    use_ssl = bool(email_cfg.get("use_ssl", False))
    smtp_timeout_s = int(email_cfg.get("smtp_timeout_s") or 60)
    smtp_max_retries = int(
        email_cfg.get("max_retries") or email_cfg.get("smtp_max_retries") or 3
    )
    smtp_retry_backoff_s = float(
        email_cfg.get("retry_backoff_s") or email_cfg.get("smtp_retry_backoff_s") or 5
    )

    smtp_timeout_s = max(5, smtp_timeout_s)
    smtp_max_retries = max(1, smtp_max_retries)
    smtp_retry_backoff_s = max(0.0, smtp_retry_backoff_s)

    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = Header(subject, "utf-8").encode()
    msg_root["From"] = from_addr
    msg_root["To"] = ", ".join(to_addrs)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg_root.attach(alt)

    for item in inline_images or []:
        if not isinstance(item, tuple) or len(item) != 3:
            continue
        cid, payload, subtype = item
        if not cid or not payload:
            continue
        st = (subtype or "png").strip().lower()
        image_part = MIMEImage(payload, _subtype=st)
        image_part.add_header("Content-ID", f"<{cid}>")
        image_part.add_header("Content-Disposition", "inline", filename=f"{cid}.{st}")
        msg_root.attach(image_part)

    last_exc: Optional[Exception] = None
    for attempt in range(1, smtp_max_retries + 1):
        try:
            mode = "SSL" if use_ssl else ("STARTTLS" if use_tls else "PLAIN")
            _log(
                f"[INFO] SMTP send attempt {attempt}/{smtp_max_retries}: {smtp_host}:{smtp_port} ({mode})"
            )
            smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
            with smtp_cls(smtp_host, smtp_port, timeout=smtp_timeout_s) as server:
                server.ehlo()
                if use_tls and not use_ssl:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if smtp_user:
                    server.login(smtp_user, password)
                server.sendmail(from_addr, to_addrs, msg_root.as_string())
            return
        except Exception as e:
            last_exc = e
            retryable = False
            if isinstance(
                e, (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError)
            ):
                retryable = False
            elif isinstance(e, smtplib.SMTPResponseException):
                code = int(getattr(e, "smtp_code", 0) or 0)
                retryable = 400 <= code < 500
            elif isinstance(
                e,
                (
                    TimeoutError,
                    OSError,
                    smtplib.SMTPConnectError,
                    smtplib.SMTPServerDisconnected,
                ),
            ):
                retryable = True
            elif isinstance(e, smtplib.SMTPException):
                retryable = True

            _log(
                f"[WARN] SMTP send failed ({attempt}/{smtp_max_retries}): {type(e).__name__}: {e}"
            )

            if (not retryable) or attempt >= smtp_max_retries:
                break

            sleep_s = smtp_retry_backoff_s * attempt
            if sleep_s > 0:
                _log(f"[INFO] Retrying SMTP send in {sleep_s:.1f}s ...")
                time.sleep(sleep_s)

    if last_exc is not None:
        raise RuntimeError(
            f"SMTP send failed after {smtp_max_retries} attempts ({smtp_host}:{smtp_port})"
        ) from last_exc


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
