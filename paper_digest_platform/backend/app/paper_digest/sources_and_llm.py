from __future__ import annotations
from typing import List

"""检索源与 LLM 相关实现。"""

from app.paper_digest.core_utils import *


def _parse_date(s: str) -> Optional[dt.date]:
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


def search_arxiv(
    keywords_list: List[List[str]],
    since: dt.date,
    max_results: int = 50,
    timeout_s: int = 30,
) -> list[Paper]:
    """
    功能说明：
        按给定条件从 arxiv 数据源检索论文，并返回统一结构的数据列表。
    参数说明：
        - keyword: 关键词或关键词集合。
        - max_results: 业务输入参数。
        - since: 时间范围或日期参数。
        - timeout_s: 超时时间（秒）。
    返回值：
        返回类型为 `list[Paper]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    url = "https://export.arxiv.org/api/query"
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    queries = []
    for keywords in keywords_list:
        query_str = " AND ".join([f'all:"{t}"' for t in keywords])
        queries.append(query_str)

    headers = {"User-Agent": USER_AGENT}
    per_query_limit = max(20, max_results * 2)

    ranked: dict[str, tuple[float, Paper]] = {}
    for query in queries:
        params = {
            "search_query": query,
            "start": 0,
            "max_results": per_query_limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        _log(f"[DEBUG] arXiv query params: {params}")
        try:
            r = _http_get_with_retry(
                url,
                params=params,
                headers=headers,
                timeout_s=timeout_s,
                max_retries=3,
                backoff_s=1.2,
                retry_statuses=(429, 500, 502, 503, 504),
            )
        except Exception as e:
            _log(f"[WARN] arXiv 请求失败 ({query}): {e}")
            continue
        root = ET.fromstring(r.text)

        for entry in root.findall("atom:entry", ns):
            title = (
                entry.findtext("atom:title", default="", namespaces=ns) or ""
            ).strip()
            title = re.sub(r"\s+", " ", title)
            abstract = (
                entry.findtext("atom:summary", default="", namespaces=ns) or ""
            ).strip()
            abstract = re.sub(r"\s+", " ", abstract)
            published_raw = entry.findtext("atom:published", default="", namespaces=ns)
            published_date = _parse_date(published_raw)
            if published_date and published_date < since:
                continue
            paper_url = entry.findtext("atom:id", default="", namespaces=ns) or ""
            arxiv_id = paper_url.rsplit("/", 1)[-1]

            authors = []
            for a in entry.findall("atom:author", ns):
                name = (
                    a.findtext("atom:name", default="", namespaces=ns) or ""
                ).strip()
                if name:
                    authors.append(name)

            pdf_url = ""
            for link in entry.findall("atom:link", ns):
                if (link.get("title") or "").lower() == "pdf":
                    pdf_url = link.get("href") or ""
                    break
            venue = "arXiv"
            primary_cat = entry.find("arxiv:primary_category", ns)
            if primary_cat is not None and primary_cat.get("term"):
                venue = f"arXiv ({primary_cat.get('term')})"

            paper = Paper(
                source="arxiv",
                title=title,
                url=paper_url,
                venue=venue,
                published_date=published_date,
                authors=authors,
                abstract=abstract,
                publisher="arXiv",
                doi="",
                arxiv_id=arxiv_id,
                pdf_url=pdf_url,
                keywords=["".join(keywords)],
            )
            ranked[paper.url] = (0.0, paper)
    papers = [p for _, p in ranked.values()]
    return papers


def _crossref_pick_date(item: dict[str, Any]) -> Optional[dt.date]:
    """
    功能说明：
        执行 `_crossref_pick_date` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - item: 业务输入参数。
    返回值：
        返回类型为 `Optional[dt.date]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    candidates = [
        item.get("published-online"),
        item.get("published-print"),
        item.get("issued"),
        item.get("created"),
    ]
    for c in candidates:
        if not isinstance(c, dict):
            continue
        parts = (c.get("date-parts") or [[None]])[0]
        if not parts or not parts[0]:
            continue
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
        try:
            return dt.date(year, month, day)
        except Exception:
            continue
    return None


def search_crossref(
    keywords_list: list[list[str]],  # 接收二维列表
    rows: int,
    since: dt.date,
    mailto: str,
    publisher_substrings: list[str],
    types: list[str],
    timeout_s: int = 30,
) -> list[Paper]:
    """
    功能说明：
        按照精确组合条件从 Crossref 检索论文。
        外层列表代表 OR（满足其一即可），内层列表代表 AND（必须同时包含且为完整短语）。
    参数说明：
        - keyword: 关键词或关键词集合。
        - rows: 待处理的数据集合。
        - since: 时间范围或日期参数。
        - until: 时间范围或日期参数。
        - mailto: 业务输入参数。
        - publisher_substrings: 业务输入参数。
        - types: 业务输入参数。
        - query_field: 业务输入参数。
        - min_similarity: 业务输入参数。
        - timeout_s: 超时时间（秒）。
    返回值：
        返回类型为 `list[Paper]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    url = "https://api.crossref.org/works"
    filters = [
        f"from-created-date:{since.isoformat()}",
    ]
    if types:
        for t in types:
            if t:
                filters.append(f"type:{t}")
    filter_str = ",".join(filters)
    headers = {"User-Agent": USER_AGENT}
    if mailto:
        headers["User-Agent"] = f"{USER_AGENT} (mailto:{mailto})"
    publisher_filters = [p.lower() for p in (publisher_substrings or []) if p]
    # 用于全局去重，防止不同组合条件搜到同一篇论文
    merged_papers: dict[str, Paper] = {}
    # ========================================================
    # 2. 遍历外层列表 (实现 OR 逻辑)
    # ========================================================
    for keyword_group in keywords_list:
        if not keyword_group:
            continue
        # 构造 Crossref 接口查询字符串：给每个短语加上双引号
        # 例如：'"report generation" "llm"'
        query_str = " ".join([f'"{kw}"' for kw in keyword_group])

        # 接口经常返回模糊数据，我们稍微多取一点（例如2倍），留给本地做严密剔除
        fetch_rows = max(50, rows * 2)
        if fetch_rows > 1000:
            fetch_rows = 1000  # Crossref API 的硬性限制
        params = {
            "filter": filter_str,
            "rows": fetch_rows,
            "sort": "published",
            "order": "desc",
            "query": query_str,  # 对全文、摘要、标题进行联合查询
        }
        _log(f"[DEBUG] Crossref query group: {query_str}")
        r = None
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=timeout_s)
                if r.status_code == 200:
                    break
                time.sleep(1.5 * (attempt + 1))  # 遵守 API 礼貌停顿
            except Exception:
                continue
        if r is None or r.status_code != 200:
            continue

        data = r.json()
        items = ((data or {}).get("message") or {}).get("items") or []
        for item in items:
            # 过滤出版商
            publisher = (item.get("publisher") or "").strip()
            if publisher_filters:
                lp = publisher.lower()
                if not any(sub in lp for sub in publisher_filters):
                    continue
            # 提取标题和摘要
            title_list = item.get("title") or []
            title = (title_list[0] if title_list else "") or ""
            title = re.sub(r"\s+", " ", title).strip()
            # print("title", title)
            abstract = _strip_jats_abstract((item.get("abstract") or "").strip())
            # ========================================================
            # 3. 本地 Python 终极硬核校验 (实现 AND 及连贯短语逻辑)
            # ========================================================
            content_lower = f"{title} {abstract}".lower()
            is_match = True
            for kw in keyword_group:
                # 必须作为完整的子字符串出现
                if kw.lower() not in content_lower:
                    is_match = False
                    break

            if not is_match:
                continue  # 哪怕只差一个短语，直接无情淘汰

            doi = (item.get("DOI") or "").strip()
            work_url = (item.get("URL") or "").strip()
            container = item.get("container-title") or []
            venue = (container[0] if container else "") or "Crossref"
            published_date = _crossref_pick_date(item)

            authors = []
            for a in item.get("author") or []:
                given = (a.get("given") or "").strip()
                family = (a.get("family") or "").strip()
                name = _safe_join([given, family], sep=" ").strip()
                if name:
                    authors.append(name)
            pdf_url = ""
            for link in item.get("link") or []:
                if (link.get("content-type") or "").lower() == "application/pdf":
                    pdf_url = (link.get("URL") or "").strip()
                    break

            # 将满足的条件记录下来，方便排查
            group_display_name = " + ".join(keyword_group)

            # 使用 DOI 作为去重主键，如果没有 DOI 则用小写标题
            uid = f"doi:{doi}" if doi else f"title:{title.lower()}"
            if uid not in merged_papers:
                merged_papers[uid] = Paper(
                    source="crossref",
                    title=title,
                    url=work_url or (f"https://doi.org/{doi}" if doi else ""),
                    venue=venue,
                    published_date=published_date,
                    authors=authors,
                    abstract=abstract,
                    publisher=publisher,
                    doi=doi,
                    arxiv_id="",
                    pdf_url=pdf_url,
                    keywords=[group_display_name],
                )
            else:
                # 如果这篇神仙论文同时命中了多个条件组，把命中的条件合并
                existing = merged_papers[uid]
                if group_display_name not in existing.keywords:
                    existing.keywords.append(group_display_name)
    # 4. 提取最终结果并按时间排序
    final_papers = list(merged_papers.values())
    final_papers.sort(
        key=lambda p: (p.published_date or dt.date(1900, 1, 1), p.title),
        reverse=True,
    )
    return final_papers


def _extract_doi(articleids: Any) -> str:
    """
    功能说明：
        执行 `_extract_doi` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - articleids: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not isinstance(articleids, list):
        return ""
    for x in articleids:
        if not isinstance(x, dict):
            continue
        idtype = str(x.get("idtype") or "").strip().lower()
        value = str(x.get("value") or "").strip()
        if idtype == "doi" and value:
            return value
    return ""


def _pubmed_fetch_abstracts(
    pmids: list[str],
    timeout_s: int,
    api_key: str = "",
    email: str = "",
) -> dict[str, str]:
    """
    功能说明：
        执行 `_pubmed_fetch_abstracts` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - pmids: 业务输入参数。
        - timeout_s: 超时时间（秒）。
        - api_key: 业务输入参数。
        - email: 邮件或 SMTP 相关参数。
    返回值：
        返回类型为 `dict[str, str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not pmids:
        return {}
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    try:
        r = _http_get_with_retry(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout_s=timeout_s,
            max_retries=3,
        )
    except Exception:
        return {}

    root = ET.fromstring(r.text)
    out: dict[str, str] = {}
    for art in root.findall(".//PubmedArticle"):
        pmid = (
            art.findtext("./MedlineCitation/PMID") or art.findtext(".//PMID") or ""
        ).strip()
        if not pmid:
            continue
        parts: list[str] = []
        for node in art.findall(".//Article/Abstract/AbstractText"):
            txt = " ".join("".join(node.itertext()).split()).strip()
            if not txt:
                continue
            label = (node.attrib.get("Label") or "").strip()
            if label:
                parts.append(f"{label}: {txt}")
            else:
                parts.append(txt)
        if parts:
            out[pmid] = " ".join(parts)
    return out


def _to_float(v: Any, default: float) -> float:
    """
    功能说明：
        执行 `_to_float` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - v: 业务输入参数。
        - default: 业务输入参数。
    返回值：
        返回类型为 `float`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    try:
        return float(v)
    except Exception:
        return default


def _to_bool(v: Any, default: bool) -> bool:
    """
    功能说明：
        执行 `_to_bool` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - v: 业务输入参数。
        - default: 业务输入参数。
    返回值：
        返回类型为 `bool`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v or "").strip().lower()
    if s in {"1", "true", "yes", "y", "on", "keep", "保留", "是"}:
        return True
    if s in {"0", "false", "no", "n", "off", "drop", "reject", "否"}:
        return False
    return default


def search_pubmed(
    keywords_list: list[list[str]],  # 接收二维列表
    since: dt.date,
    rows: int = 20,
    until: dt.date = dt.date.today(),
    timeout_s: int = 30,
    api_key: str = "",
    email: str = "",
) -> list[Paper]:
    """
    功能说明：
        按照精确组合条件从 PubMed 数据源检索论文。
        外层列表代表 OR，内层列表代表 AND（必须同时包含且为完整短语）。
    返回值：
        返回类型为 `list[Paper]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    headers = {"User-Agent": USER_AGENT}
    # 收集所有的目标论文 ID (PMID)，用于一次性获取摘要
    all_pmids = []
    seen_pmids = set()
    # ========================================================
    # 1. 遍历外层列表，调用 esearch 获取所有符合条件的 PMID
    # ========================================================
    for keyword_group in keywords_list:
        if not keyword_group:
            continue
        # 构造 PubMed 查询语法：给每个短语加双引号防扩展，并用 AND 连接
        # 例如: "report generation" AND "llm"
        query_str = " AND ".join([f'"{kw}"' for kw in keyword_group])
        search_params = {
            "db": "pubmed",
            "term": query_str,
            "retmode": "json",
            "retmax": max(50, rows * 2),  # 多取一些，留给本地严格过滤
            "sort": "pub_date",
            "datetype": "pdat",
            "mindate": since.isoformat(),
            "maxdate": until.isoformat(),
        }
        if api_key:
            search_params["api_key"] = api_key
        if email:
            search_params["email"] = email
        _log(f"[DEBUG] PubMed query group: {query_str}")
        try:
            r = _http_get_with_retry(
                f"{base}/esearch.fcgi",
                params=search_params,
                headers=headers,
                timeout_s=timeout_s,
                max_retries=3,
            )
            id_list = ((r.json() or {}).get("esearchresult") or {}).get("idlist") or []

            for pmid in id_list:
                pmid_str = str(pmid).strip()
                if pmid_str and pmid_str not in seen_pmids:
                    seen_pmids.add(pmid_str)
                    all_pmids.append(pmid_str)
        except Exception as e:
            _log(f"[WARN] PubMed esearch 失败 ({query_str}): {e}")
            continue
        time.sleep(2)  # PubMed 接口要求停顿，无 key 最多 3次/秒
    if not all_pmids:
        return []
    # 为了防止请求 URI 过长导致报错，限制最大批量请求数 (PubMed GET 建议不要超过 200-300个)
    all_pmids = all_pmids[:300]
    # ========================================================
    # 2. 批量调用 esummary 获取元数据 (标题、作者、日期)
    # ========================================================
    summary_params = {
        "db": "pubmed",
        "id": ",".join(all_pmids),
        "retmode": "json",
    }
    if api_key:
        summary_params["api_key"] = api_key
    if email:
        summary_params["email"] = email
    try:
        s = _http_get_with_retry(
            f"{base}/esummary.fcgi",
            params=summary_params,
            headers=headers,
            timeout_s=timeout_s,
            max_retries=3,
        )
        summary_json = (s.json() or {}).get("result") or {}
    except Exception as e:
        _log(f"[WARN] PubMed esummary 失败: {e}")
        summary_json = {}
    time.sleep(0.34)

    # ========================================================
    # 3. 批量调用 efetch 获取所有摘要
    # ========================================================
    abstracts = _pubmed_fetch_abstracts(
        all_pmids, timeout_s=timeout_s, api_key=api_key, email=email
    )

    papers: list[Paper] = []
    # ========================================================
    # 4. 组装 Paper 并执行本地 Python 的终极硬核校验
    # ========================================================
    for pmid in all_pmids:
        item = summary_json.get(pmid) or {}
        title = re.sub(r"\s+", " ", str(item.get("title") or "").strip())
        if not title:
            continue

        abstract = abstracts.get(pmid, "")
        # --- 本地严格子字符串包含校验 ---
        content_lower = f"{title} {abstract}".lower()
        matched_groups = []

        for keyword_group in keywords_list:
            is_match = True
            for kw in keyword_group:
                if kw.lower() not in content_lower:
                    is_match = False
                    break
            if is_match:
                # 记录它具体命中了哪几个组
                matched_groups.append(" + ".join(keyword_group))

        if not matched_groups:
            continue  # 没有任何组严格匹配（说明被 PubMed 的模糊映射给忽悠了），淘汰！
        # -----------------------------
        published_date = _pubmed_pick_date(item)
        if published_date:
            if published_date < since or published_date > until:
                continue
        authors = []
        for a in item.get("authors") or []:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "").strip()
            if name:
                authors.append(name)
        venue = str(item.get("fulljournalname") or item.get("source") or "").strip()
        if not venue:
            venue = "PubMed indexed article"

        publisher = str(item.get("publisher") or "").strip()
        if publisher.lower() == "pubmed":
            publisher = ""

        doi = _extract_doi(item.get("articleids"))
        papers.append(
            Paper(
                source="pubmed",
                title=title,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                venue=venue,
                published_date=published_date,
                authors=authors,
                abstract=abstract,
                publisher=publisher,
                doi=doi,
                arxiv_id="",
                pdf_url="",
                keywords=matched_groups,  # 这里会记录它命中的所有严格条件
            )
        )
    # 5. 排序：按发表日期降序，如果日期一样按标题排
    papers.sort(
        key=lambda p: (p.published_date or dt.date(1900, 1, 1), p.title),
        reverse=True,
    )
    return papers[:rows]


def _ieee_authors(raw: Any) -> list[str]:
    """
    功能说明：
        执行 `_ieee_authors` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - raw: 业务输入参数。
    返回值：
        返回类型为 `list[str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if isinstance(raw, dict):
        raw = raw.get("authors")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for a in raw:
        if isinstance(a, dict):
            name = str(a.get("full_name") or a.get("name") or "").strip()
        else:
            name = str(a).strip()
        if name:
            out.append(name)
    return out


def search_ieee_xplore(
    keyword: str,
    rows: int,
    since: dt.date,
    until: dt.date,
    timeout_s: int,
    api_key: str,
) -> list[Paper]:
    """
    功能说明：
        按给定条件从 ieee xplore 数据源检索论文，并返回统一结构的数据列表。
    参数说明：
        - keyword: 关键词或关键词集合。
        - rows: 待处理的数据集合。
        - since: 时间范围或日期参数。
        - until: 时间范围或日期参数。
        - timeout_s: 超时时间（秒）。
        - api_key: 业务输入参数。
        - min_title_token_matches: 业务输入参数。
        - min_title_token_fraction: 业务输入参数。
        - min_similarity: 业务输入参数。
    返回值：
        返回类型为 `list[Paper]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not api_key:
        return []
    url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
    params = {
        "apikey": api_key,
        "format": "json",
        "querytext": keyword,
        "max_records": max(1, min(int(rows), 200)),
        "start_record": 1,
        "sort_order": "desc",
        "sort_field": "publication_year",
    }
    r = requests.get(
        url, params=params, timeout=timeout_s, headers={"User-Agent": USER_AGENT}
    )
    r.raise_for_status()
    items = (r.json() or {}).get("articles") or []

    papers: list[Paper] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = re.sub(r"\s+", " ", str(item.get("title") or "").strip())
        if not title:
            continue
        abstract = re.sub(r"\s+", " ", str(item.get("abstract") or "").strip())

        date_raw = str(
            item.get("publication_date") or item.get("publication_year") or ""
        ).strip()
        published_date = _parse_date_fuzzy(date_raw)
        if published_date:
            if published_date < since or published_date > until:
                continue

        doi = str(item.get("doi") or "").strip()
        html_url = str(item.get("html_url") or "").strip()
        paper_url = html_url or (f"https://doi.org/{doi}" if doi else "")
        venue = str(item.get("publication_title") or "IEEE Xplore").strip()
        publisher = str(item.get("publisher") or "IEEE").strip()
        pdf_url = str(item.get("pdf_url") or "").strip()

        papers.append(
            Paper(
                source="ieee",
                title=title,
                url=paper_url,
                venue=venue,
                published_date=published_date,
                authors=_ieee_authors(item.get("authors")),
                abstract=abstract,
                publisher=publisher,
                doi=doi,
                arxiv_id="",
                pdf_url=pdf_url,
                keywords=[keyword],
            )
        )
    return papers


def semantic_scholar_enrich(
    paper: Paper,
    api_key: str,
    timeout_s: int,
) -> Paper:
    """
    功能说明：
        执行 `semantic_scholar_enrich` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
        - api_key: 业务输入参数。
        - timeout_s: 超时时间（秒）。
    返回值：
        返回类型为 `Paper`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if paper.abstract and paper.venue and paper.published_date and paper.url:
        return paper

    external_id = ""
    if paper.doi:
        external_id = f"DOI:{paper.doi}"
    elif paper.arxiv_id:
        arxiv_id = paper.arxiv_id.split("v", 1)[0]
        external_id = f"ARXIV:{arxiv_id}"
    else:
        return paper

    fields = "title,abstract,venue,publicationDate,url,authors,externalIds"
    url = f"https://api.semanticscholar.org/graph/v1/paper/{external_id}"
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["x-api-key"] = api_key
    r = requests.get(url, params={"fields": fields}, headers=headers, timeout=timeout_s)
    if r.status_code != 200:
        return paper
    data = r.json() or {}

    abstract = paper.abstract or (data.get("abstract") or "").strip()
    venue = paper.venue or (data.get("venue") or "").strip()
    published_date = paper.published_date
    if not published_date:
        published_date = _parse_date((data.get("publicationDate") or "").strip())
    paper_url = paper.url or (data.get("url") or "").strip()

    authors = paper.authors
    if not authors and data.get("authors"):
        authors = [
            a.get("name", "").strip() for a in data.get("authors") if a.get("name")
        ]

    doi = paper.doi
    arxiv_id = paper.arxiv_id
    external_ids = data.get("externalIds") or {}
    if not doi:
        doi = (external_ids.get("DOI") or "").strip()
    if not arxiv_id:
        arxiv_id = (external_ids.get("ArXiv") or "").strip()

    return dataclasses.replace(
        paper,
        abstract=abstract,
        venue=venue or paper.venue,
        published_date=published_date,
        url=paper_url or paper.url,
        authors=authors,
        doi=doi,
        arxiv_id=arxiv_id,
    )


def _paper_preference_payload(index: int, paper: Paper) -> str:
    """
    功能说明：
        执行 `_paper_preference_payload` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - index: 业务输入参数。
        - paper: 业务输入参数。
    返回值：
        返回类型为 `str`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    abstract = _truncate_text(_strip_jats_abstract(paper.abstract), max_len=900)
    authors = _safe_join(paper.authors[:6])
    published = paper.published_date.isoformat() if paper.published_date else ""
    keywords = _safe_join(paper.keywords)
    venue = paper.venue or ""
    publisher = paper.publisher or ""
    source_name = _source_display_name(paper.source)
    lines = [
        f"[{index}] 标题：{paper.title}",
        f"来源：{source_name}",
        f"期刊/会议：{venue}",
        f"出版商：{publisher}",
        f"日期：{published}",
        f"作者：{authors}",
        f"关键词命中：{keywords}",
        f"摘要：{abstract}",
    ]
    return "\n".join(lines)


def llm_preference_rerank(
    papers: list[Paper],
    profile: str,
) -> tuple[list[Paper], dict[str, Any]]:
    """
    llm根据用户搜索需求进行评分重排
    """
    if not papers:
        return papers, {"enabled": True, "applied": False, "reason": "no_candidates"}
    if LLMClient is None:
        return papers, {"enabled": True, "applied": False, "reason": "llm_unavailable"}
    profile = str(profile or "").strip()
    if not profile:
        return papers, {"enabled": True, "applied": False, "reason": "empty_profile"}
    prompt_items = "\n\n".join(
        _paper_preference_payload(idx, p) for idx, p in enumerate(papers)
    )

    system_message = (
        "你是论文偏好筛选助手。请严格输出 JSON 对象，不要输出任何 JSON 以外的内容。"
    )
    prompt = f"""请根据用户的搜索需求，对候选论文做二次筛选和重排。

用户搜索需求：
{profile}

**评分标准：**

1. **85-100 分：高度相关，优质期刊**
2. **60-84 分：基本相关**
3. **其他的不相关的论文就不输出了**

请输出 JSON 对象，格式严格如下：
{{
  "results": [
    {{"index": 0, "score": 0, "reason": "不超过20字"}}
  ]
}}

候选论文：
{prompt_items}
"""

    try:
        resp = LLMClient().query(
            query=prompt,
            model_name="qwen3-max",
            system_message=system_message,
            json_mode=True,
        )
        obj = json.loads(resp)
    except Exception as exc:
        return papers, {
            "enabled": True,
            "applied": False,
            "reason": "llm_query_failed",
            "error": str(exc)[:200],
        }
    raw_results = obj.get("results")
    if not isinstance(raw_results, list):
        return papers, {"enabled": True, "applied": False, "reason": "invalid_json"}

    decisions: dict[int, tuple[float, bool]] = {}
    min_score = 100

    for row in raw_results:
        idx_raw = row.get("index")
        try:
            idx = int(idx_raw)
        except Exception:
            continue
        if idx < 0 or idx >= len(papers):
            continue
        score = max(0.0, min(100.0, _to_float(row.get("score"), 50.0)))
        if score < min_score:
            min_score = score
        decisions[idx] = (score, True)

    if not decisions:
        return papers, {"enabled": True, "applied": False, "reason": "no_decisions"}

    kept: list[tuple[float, Paper]] = []
    for idx, paper in enumerate(papers):
        score, _ = decisions.get(idx, (50.0, False))
        if score >= 60:
            kept.append((score, paper))

    kept.sort(key=lambda item: item[0], reverse=True)

    reranked = [paper for _, paper in kept]
    if not reranked:
        fallback_count = min(len(papers), 10)
        return papers[:fallback_count], {
            "enabled": True,
            "applied": True,
            "evaluated": len(papers),
            "kept": 0,
            "fallback": fallback_count,
            "reason": "all_below_threshold",
        }
    return reranked, {
        "enabled": True,
        "applied": True,
        "evaluated": len(papers),
        "kept": len(kept),
        "min_score": min_score,
    }


def llm_summarize_zh(
    paper: Paper,
    llm_config: dict[str, Any],
    user_search_intent: str = "",
) -> dict[str, str]:
    """
    功能说明：
        执行 `llm_summarize_zh` 对应的辅助业务逻辑，为论文检索与推送流程提供支撑。
    参数说明：
        - paper: 业务输入参数。
        - llm_config: 配置字典或配置对象。
    返回值：
        返回类型为 `dict[str, str]`。
    异常：
        - 按实现可能抛出运行时异常；调用方应根据业务场景处理。
    """
    if not paper.abstract:
        return {}
    if LLMClient is None:
        return {}

    model = (llm_config.get("model") or "qwen-plus").strip()
    deployment = (llm_config.get("deployment") or "ali").strip()
    temperature = float(llm_config.get("temperature") or 0.2)
    summary_style = str(llm_config.get("summary_style") or "magazine").strip().lower()
    if summary_style == "classic":
        system_message = (
            "你是论文解读助手。请严格输出 JSON 对象，键必须是：背景、动机、方法、结果。"
        )
        prompt = f"""请阅读下面的论文信息，并用中文输出一个 JSON 对象，只包含四个键：背景、动机、方法、结果。

要求：
1) 每个字段 2-5 句，尽量具体；如果摘要中有数值、数据集、对比方法，请写进结果。
2) 不要输出 JSON 以外的任何文字。

标题：{paper.title}
期刊/会议：{paper.venue}
发表日期：{paper.published_date or ""}
作者：{_safe_join(paper.authors)}
摘要：{paper.abstract}
链接：{paper.url}
"""
    elif summary_style == "magazine":
        system_message = (
            "你是学术导读编辑。请严格输出 JSON 对象，不要输出任何 JSON 以外的内容。"
        )
        prompt = f"""请把下面论文改写成适合“个人日报 / 组会导读 / 类微信公众号”的中文学术卡片。

请严格输出 JSON 对象，只包含八个键：
一句话看点、编辑判断、科学问题、核心思路、方法设计、关键结果、可借鉴之处、局限与边界

写作要求：
1) `一句话看点`：1-2句，要像封面导语，直接说“这篇最值不值得看”，允许有判断，但不能夸张。
2) `编辑判断`：只能从这五个短标签里选一个：强推荐、方法值得借鉴、结果硬但迁移有限、选题可参考、谨慎参考。
3) `科学问题`：2-4句，写清楚旧方法卡在哪里，为什么这个科学问题值得盯。
4) `核心思路`：1-3句，只提最巧、最值得记住的一招，不要泛泛复述。
5) `方法设计`：2-4句，讲清方法/模型等中最关键的组合。
6) `关键结果`：2-4句，必须尽量写数字、数据集、样本规模、对比基线、标准；这是最该突出关注的部分。
7) `可借鉴之处`：1-3句，明确说对“{user_search_intent}”方向最能借鉴什么。
8) `局限与边界`：1-3句，直接指出局限、适用条件、样本问题、泛化风险，不能回避。

额外要求：
1) 不要写空话，不要写“具有重要意义”“值得关注”这类泛化套话，除非后面紧跟具体原因。
2) 风格可以更像成熟科技公众号或组会导读，但必须建立在摘要事实上，不得编造。
3) `核心思路`、`关键结果`、`可借鉴之处` 三个键里的内容要足够短而硬，便于做卡片高亮。
4) 每个字段请用 `【】` 标出 2-4 个最值得读者一眼扫到的关键词或短语，例如方法、模型、数据集、指标、标准、关键结论；不要把整句都放进 `【】`。

标题：{paper.title}
期刊/会议：{paper.venue}
发表日期：{paper.published_date or ""}
作者：{_safe_join(paper.authors)}
摘要：{paper.abstract}
链接：{paper.url}
"""
    else:
        system_message = (
            "你是论文导读编辑。请严格输出 JSON 对象，不要输出 JSON 以外的任何文字。"
        )
        prompt = f"""请把下面论文整理成更吸引人阅读、但仍然专业扎实的中文导读。

请严格输出 JSON 对象，只包含五个键：
一句话看点、为什么值得看、核心方法、结果亮点、对你有什么启发

写作要求：
1) `一句话看点`：1-2 句，像日报导语，要有抓手，但不能夸张失真。
2) `为什么值得看`：2-4 句，说明它解决了什么关键痛点，为什么这个问题重要。
3) `核心方法`：2-4 句，讲清楚类似于硬件/信号/模型/方法/实验设计等相关最关键的招数。
4) `结果亮点`：2-4 句，尽量写具体数字、数据集、对比基线、标准或实验规模。
5) `对你有什么启发`：1-3 句，结合“{user_search_intent}”的方向，点出这篇论文最值得借鉴的地方；如果关联较弱，也要直说弱在哪里。
6) 允许写得生动一些，但不要使用空话、套话、营销语，不要编造摘要里没有的信息。

标题：{paper.title}
期刊/会议：{paper.venue}
发表日期：{paper.published_date or ""}
作者：{_safe_join(paper.authors)}
摘要：{paper.abstract}
链接：{paper.url}
"""

    client = LLMClient()
    resp = client.query(
        query=prompt,
        model_name=model,
        deployment=deployment,
        temperature=temperature,
        system_message=system_message,
        json_mode=True,
    )
    obj = _extract_json_object(resp)
    if summary_style == "classic":
        mapped = {
            "背景": (obj.get("背景") or obj.get("background") or "").strip(),
            "动机": (obj.get("动机") or obj.get("motivation") or "").strip(),
            "方法": (obj.get("方法") or obj.get("method") or "").strip(),
            "结果": (obj.get("结果") or obj.get("results") or "").strip(),
        }
    elif summary_style == "magazine":
        mapped = {
            "一句话看点": (
                obj.get("一句话看点") or obj.get("hook") or obj.get("headline") or ""
            ).strip(),
            "编辑判断": (
                obj.get("编辑判断") or obj.get("judgment") or obj.get("tag") or ""
            ).strip(),
            "科学问题": (
                obj.get("科学问题")
                or obj.get("关键问题")
                or obj.get("问题痛点")
                or obj.get("why_it_matters")
                or obj.get("为什么值得看")
                or ""
            ).strip(),
            "核心思路": (
                obj.get("核心思路")
                or obj.get("核心idea")
                or obj.get("核心想法")
                or obj.get("idea")
                or ""
            ).strip(),
            "方法设计": (
                obj.get("方法设计")
                or obj.get("方法速写")
                or obj.get("method")
                or obj.get("核心方法")
                or ""
            ).strip(),
            "关键结果": (
                obj.get("关键结果")
                or obj.get("最硬结果")
                or obj.get("key_results")
                or obj.get("结果亮点")
                or ""
            ).strip(),
            "可借鉴之处": (
                obj.get("可借鉴之处")
                or obj.get("可借鉴点")
                or obj.get("可参考点")
                or obj.get("对你有什么启发")
                or obj.get("insight_for_you")
                or ""
            ).strip(),
            "局限与边界": (
                obj.get("局限与边界")
                or obj.get("风险边界")
                or obj.get("limitations")
                or obj.get("风险")
                or ""
            ).strip(),
        }
    else:
        mapped = {
            "一句话看点": (
                obj.get("一句话看点") or obj.get("hook") or obj.get("headline") or ""
            ).strip(),
            "为什么值得看": (
                obj.get("为什么值得看") or obj.get("why_it_matters") or ""
            ).strip(),
            "核心方法": (
                obj.get("核心方法") or obj.get("method") or obj.get("core_method") or ""
            ).strip(),
            "结果亮点": (
                obj.get("结果亮点")
                or obj.get("results")
                or obj.get("key_results")
                or ""
            ).strip(),
            "对你有什么启发": (
                obj.get("对你有什么启发")
                or obj.get("启发")
                or obj.get("insight_for_you")
                or ""
            ).strip(),
        }
    return {k: v for k, v in mapped.items() if v}


# 导出当前模块全部符号（包含下划线前缀符号，供分层模块通过 * 复用）。
__all__ = [
    "search_arxiv",
    "search_crossref",
    "search_pubmed",
    "search_ieee_xplore",
    "semantic_scholar_enrich",
    "llm_preference_rerank",
    "llm_summarize_zh",
]


if __name__ == "__main__":
    # res = search_arxiv(
    #     keywords_list=[
    #         ["report generation", "llm"],
    #         ["medical report generation"],
    #         ["radiology report generation"],
    #         ["report generation", "VLM"],
    #     ],
    #     since=dt.date(2025, 12, 1),
    #     max_results=100,
    # )

    # res = search_crossref(
    #     keywords_list=[
    #         ["report generation"],
    #         # ["llm", "generation"],
    #         # ["medicine", "agent"],
    #     ],
    #     rows=50,
    #     since=dt.date(2025, 1, 1),
    #     mailto="jieyang.std@gmail.com",
    #     publisher_substrings=[],
    #     types=[],
    # )

    res = search_pubmed(
        keywords_list=[
            ["report generation"],
            ["llm", "report generation"],
            ["medicine", "agent"],
        ],
        since=dt.date(2025, 1, 1),
        rows=50,
    )
    print(f"Found {len(res)} papers.")
    for item in res:
        print(item.title)
