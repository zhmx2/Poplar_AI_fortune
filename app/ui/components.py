from __future__ import annotations

from datetime import date

import streamlit as st


def date_range_inputs(
    min_date: date,
    max_date: date,
    *,
    key_prefix: str,
    start_label: str = "Start date / 开始日期",
    end_label: str = "End date / 结束日期",
) -> tuple[date, date]:
    """Render two validated date inputs and return an inclusive range."""
    start_key = f"{key_prefix}_start"
    end_key = f"{key_prefix}_end"

    saved_start = st.session_state.get(start_key, min_date)
    saved_end = st.session_state.get(end_key, max_date)
    if not isinstance(saved_start, date) or not min_date <= saved_start <= max_date:
        saved_start = min_date
        st.session_state[start_key] = saved_start
    if not isinstance(saved_end, date) or not min_date <= saved_end <= max_date:
        saved_end = max_date
        st.session_state[end_key] = saved_end
    if saved_end < saved_start:
        saved_end = saved_start
        st.session_state[end_key] = saved_end

    start_col, end_col = st.columns(2)
    with start_col:
        start_date = st.date_input(
            start_label,
            value=saved_start,
            min_value=min_date,
            max_value=max_date,
            key=start_key,
        )
    if st.session_state.get(end_key, max_date) < start_date:
        st.session_state[end_key] = start_date
    with end_col:
        end_date = st.date_input(
            end_label,
            value=st.session_state.get(end_key, max_date),
            min_value=start_date,
            max_value=max_date,
            key=end_key,
        )
    return start_date, end_date
