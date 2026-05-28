from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchWindow:
    since: dt.date
    until: dt.date
    recovery_reason: str = "normal"


def _parse_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except Exception:
            continue
    return None


def compute_search_window(
    *,
    run_date: dt.date,
    days_back: int,
    state: dict[str, Any] | None,
    dispatch_run_type: str,
    max_catchup_days: int = 21,
    max_manual_days: int = 90,
) -> SearchWindow:
    state = state if isinstance(state, dict) else {}
    run_kind = str(dispatch_run_type or "").strip().lower()
    base_days = max(1, int(days_back or 1))

    if run_kind != "scheduled":
        manual_days = min(max_manual_days, max(1, base_days))
        return SearchWindow(
            since=run_date - dt.timedelta(days=manual_days),
            until=run_date,
            recovery_reason="manual_extended",
        )

    base_since = run_date - dt.timedelta(days=base_days)
    last_success = (
        _parse_date(state.get("last_successful_scheduled_search_date"))
        or _parse_date(state.get("last_successful_search_date"))
        or _parse_date(state.get("last_scheduled_email_date"))
        or _parse_date(state.get("last_email_date"))
    )

    if not last_success:
        return SearchWindow(since=base_since, until=run_date, recovery_reason="normal")

    catchup_floor = run_date - dt.timedelta(days=max(1, max_catchup_days))
    recovery_since = max(catchup_floor, last_success)
    since = min(base_since, recovery_since)

    recovery_reason = "normal"
    if state.get("last_search_failed_at"):
        recovery_reason = "previous_failure"
    elif last_success < base_since:
        recovery_reason = "missed_run"

    return SearchWindow(since=since, until=run_date, recovery_reason=recovery_reason)
