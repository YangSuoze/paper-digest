from __future__ import annotations

import datetime as dt

from app.paper_digest.windowing import compute_search_window


def test_scheduled_window_uses_base_days_without_history() -> None:
    window = compute_search_window(
        run_date=dt.date(2026, 5, 28),
        days_back=7,
        state={},
        dispatch_run_type="scheduled",
    )

    assert window.since == dt.date(2026, 5, 21)
    assert window.until == dt.date(2026, 5, 28)
    assert window.recovery_reason == "normal"


def test_scheduled_window_recovers_missed_interval_with_bound() -> None:
    window = compute_search_window(
        run_date=dt.date(2026, 5, 28),
        days_back=7,
        state={"last_successful_scheduled_search_date": "2026-04-01"},
        dispatch_run_type="scheduled",
        max_catchup_days=21,
    )

    assert window.since == dt.date(2026, 5, 7)
    assert window.until == dt.date(2026, 5, 28)
    assert window.recovery_reason == "missed_run"


def test_manual_window_is_extended_but_bounded() -> None:
    window = compute_search_window(
        run_date=dt.date(2026, 5, 28),
        days_back=120,
        state={"last_successful_scheduled_search_date": "2026-05-27"},
        dispatch_run_type="manual_digest",
        max_manual_days=90,
    )

    assert window.since == dt.date(2026, 2, 27)
    assert window.recovery_reason == "manual_extended"
