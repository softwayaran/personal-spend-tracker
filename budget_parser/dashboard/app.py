#!/usr/bin/env python3
"""
Budget Dashboard -- interactive visualization and management of categorized transactions.

Usage:
  streamlit run dashboard.py
"""

import re
from typing import Dict, List, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from budget_parser.database.db import (
    add_category,
    add_regex_rule,
    bulk_update_transactions,
    delete_category,
    delete_regex_rule,
    delete_transaction,
    get_available_years,
    get_categories,
    get_regex_rules,
    get_transactions,
    update_category,
    update_regex_rule,
    upsert_transactions,
)

# -- Page config ---------------------------------------------------------------
st.set_page_config(page_title="Budget Dashboard", layout="wide", page_icon="$")

PALETTE = px.colors.qualitative.Plotly
DEFAULT_DB_PATH = "budget.db"


# -- Cache invalidation --------------------------------------------------------
if "db_version" not in st.session_state:
    st.session_state["db_version"] = 0


def _bump_db_version() -> None:
    st.session_state["db_version"] += 1
    st.cache_data.clear()


# -- Data loading from DB ------------------------------------------------------

@st.cache_data
def load_data_from_db(db_path: str, year: int, cache_version: int) -> pd.DataFrame:
    """Load transactions for charts  fills empty category/sub_category/merchant for display."""
    rows = get_transactions(db_path, year)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[df["date"].dt.year == int(year)]
    if df.empty:
        return pd.DataFrame()
    df["month_key"] = df["date"].dt.to_period("M").astype(str)
    df["month"] = df["date"].dt.strftime("%b %Y")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").abs()
    df["category"] = df["category"].fillna("").replace("", "Uncategorized")
    df["sub_category"] = df["sub_category"].fillna("").replace("", "-")
    df["merchant"] = df["merchant"].fillna("").replace("", "-")
    return df.sort_values("date")


@st.cache_data
def load_raw_transactions(db_path: str, year: int, cache_version: int) -> pd.DataFrame:
    """Load transactions for the editor  keeps empty strings so users can fill them in."""
    rows = get_transactions(db_path, year)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[df["date"].dt.year == int(year)]
    if df.empty:
        return pd.DataFrame()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").abs()
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data
def load_data_for_years(db_path: str, years: Tuple[int, ...], cache_version: int) -> pd.DataFrame:
    """Load chart data for multiple years."""
    frames = [load_data_from_db(db_path, year, cache_version) for year in years]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df[df["date"].dt.year.isin(years)].sort_values("date")


@st.cache_data
def load_raw_transactions_for_years(
    db_path: str, years: Tuple[int, ...], cache_version: int
) -> pd.DataFrame:
    """Load editable transactions for multiple years."""
    frames = [load_raw_transactions(db_path, year, cache_version) for year in years]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df[df["date"].dt.year.isin(years)].sort_values("date").reset_index(drop=True)


@st.cache_data
def load_all_categories(db_path: str, cache_version: int) -> List[Dict]:
    return get_categories(db_path)


@st.cache_data
def load_all_rules(db_path: str, cache_version: int) -> List[Dict]:
    return get_regex_rules(db_path)


# -- Chart helpers -------------------------------------------------------------

def month_order(df: pd.DataFrame) -> list:
    """Return month labels sorted chronologically."""
    return (
        df[["month_key", "month"]]
        .drop_duplicates()
        .sort_values("month_key")["month"]
        .tolist()
    )


def stacked_bar(df: pd.DataFrame, group_col: str, title: str) -> go.Figure:
    """Stacked bar: months on X, spend on Y, stacked by group_col."""
    months = month_order(df)
    groups = sorted(df[group_col].dropna().unique())

    pivot = (
        df.groupby(["month", group_col])["amount"]
        .sum()
        .unstack(fill_value=0)
        .reindex(months, fill_value=0)
    )

    fig = go.Figure()
    for i, grp in enumerate(groups):
        y = pivot[grp].tolist() if grp in pivot.columns else [0] * len(months)
        fig.add_trace(go.Bar(
            name=str(grp),
            x=months,
            y=y,
            marker_color=PALETTE[i % len(PALETTE)],
            hovertemplate=f"<b>{grp}</b><br>%{{x}}: $%{{y:,.2f}}<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        barmode="stack",
        xaxis_title="Month",
        yaxis_title="Amount ($)",
        legend_title=group_col.replace("_", " ").title(),
        hovermode="x unified",
        height=430,
        margin=dict(t=50, b=40),
    )
    return fig


# -- Transaction table (read-only, used in chart tabs) -------------------------

def show_transactions(df: pd.DataFrame, label: str = ""):
    if df.empty:
        st.caption("No transactions.")
        return
    total = df["amount"].sum()
    st.caption(
        f"{len(df)} transactions  |  **${total:,.2f}**"
        + (f"  |  {label}" if label else "")
    )
    disp = df[["date", "description", "amount", "category", "sub_category", "merchant"]].copy()
    disp["date"] = disp["date"].dt.strftime("%Y-%m-%d")
    disp["amount"] = disp["amount"].map("${:,.2f}".format)
    st.dataframe(disp.sort_values("date"), width="stretch", hide_index=True)


# -- Session state -------------------------------------------------------------
_SEL_DEFAULTS = {
    "ov_cat": "(all)",
    "ov_month": "(all)",
    "ov_sub": "(all)",
}

for _k, _v in _SEL_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# -- Sidebar: year picker from DB ----------------------------------------------
st.sidebar.title("Budget Dashboard")

available_years = get_available_years(DEFAULT_DB_PATH)

if not available_years:
    st.error(
        "No data in budget.db.  \n"
        "Run `python -m budget_parser extract --year <YYYY>` and `categorize` first, then refresh."
    )
    st.stop()

selected_years = st.sidebar.multiselect(
    "Years",
    available_years,
    default=[available_years[0]],
)
if not selected_years:
    st.warning("Select at least one year.")
    st.stop()

selected_years = sorted(selected_years)
selected_years_label = ", ".join(str(y) for y in selected_years)

df = load_data_for_years(
    DEFAULT_DB_PATH,
    tuple(selected_years),
    st.session_state["db_version"],
)

if df.empty:
    st.error(f"No transactions found for selected year(s): {selected_years_label}.")
    st.stop()

sorted_cats = sorted(df["category"].unique())

tab_overview, tab_mom, tab_txns, tab_cats, tab_rules = st.tabs([
    "Monthly Overview", "Month-over-Month",
    "Transactions", "Categories", "Regex Rules",
])


# =============================================================================
# TAB 1 -- MONTHLY OVERVIEW
# =============================================================================
with tab_overview:
    st.subheader("Monthly Overview")
    st.caption(f"Showing year(s): {selected_years_label}")
    st.plotly_chart(
        stacked_bar(df, "category", "Monthly Spend by Category"),
        key="overview_chart_main",
        width="stretch",
    )
    st.markdown("#### Category Spend")
    month_cols = month_order(df)
    category_monthly = (
        df.groupby(["category", "month"])["amount"]
        .sum()
        .reset_index()
    )
    if category_monthly.empty:
        st.caption("No data to display.")
    else:
        category_table = (
            category_monthly.pivot_table(
                index="category",
                columns="month",
                values="amount",
                aggfunc="sum",
                fill_value=0.0,
            )
            .reindex(columns=month_cols, fill_value=0.0)
        )
        category_table["Total ($)"] = category_table.sum(axis=1)
        category_table = (
            category_table.sort_values("Total ($)", ascending=False)
            .reset_index()
            .rename(columns={"category": "Category"})
        )

        money_cols = month_cols + ["Total ($)"]

        totals_row = {"Category": "Total"}
        for col in money_cols:
            totals_row[col] = category_table[col].sum()
        category_table = pd.concat(
            [category_table, pd.DataFrame([totals_row])], ignore_index=True
        )

        category_display = category_table.copy()
        for col in money_cols:
            category_display[col] = category_display[col].map("${:,.2f}".format)
        st.dataframe(category_display, width="stretch", hide_index=True)

        drill_category = st.selectbox(
            "Drill into sub-categories for",
            ["(none)"] + category_table["Category"].tolist(),
            key="overview_drill_category",
        )

        if drill_category != "(none)":
            sub_monthly = (
                df[df["category"] == drill_category]
                .groupby(["sub_category", "month"])["amount"]
                .sum()
                .reset_index()
            )
            if sub_monthly.empty:
                st.caption("No sub-category data to display.")
            else:
                sub_table = (
                    sub_monthly.pivot_table(
                        index="sub_category",
                        columns="month",
                        values="amount",
                        aggfunc="sum",
                        fill_value=0.0,
                    )
                    .reindex(columns=month_cols, fill_value=0.0)
                )
                sub_table["Total ($)"] = sub_table.sum(axis=1)
                sub_table = (
                    sub_table.sort_values("Total ($)", ascending=False)
                    .reset_index()
                    .rename(columns={"sub_category": "Sub-Category"})
                )

                sub_totals_row = {"Sub-Category": "Total"}
                for col in money_cols:
                    sub_totals_row[col] = sub_table[col].sum()
                sub_table = pd.concat(
                    [sub_table, pd.DataFrame([sub_totals_row])], ignore_index=True
                )

                sub_display = sub_table.copy()
                for col in money_cols:
                    sub_display[col] = sub_display[col].map("${:,.2f}".format)
                st.markdown(f"##### Sub-categories: {drill_category}")
                st.dataframe(sub_display, width="stretch", hide_index=True)


# =============================================================================
# TAB 2 -- MONTH-OVER-MONTH COMPARISON
# =============================================================================
with tab_mom:
    st.subheader("Month-over-Month Drill-down")
    st.caption(
        "Use the filters to drill down from category to sub-category and merchants."
    )

    st.markdown("**Filter / Drill-down**")
    fc1, fc2, fc3 = st.columns([3, 3, 1])

    prev_cat = st.session_state["ov_cat"]

    with fc1:
        chosen_cat = st.selectbox(
            "Category",
            ["(all)"] + sorted_cats,
            index=(["(all)"] + sorted_cats).index(st.session_state["ov_cat"])
            if st.session_state["ov_cat"] in sorted_cats else 0,
            key="ov_cat",
        )

    if chosen_cat != prev_cat:
        st.session_state["ov_sub"] = "(all)"

    month_opts = ["(all)"] + month_order(df)
    with fc2:
        chosen_month = st.selectbox(
            "Month",
            month_opts,
            index=month_opts.index(st.session_state["ov_month"])
            if st.session_state["ov_month"] in month_opts else 0,
            key="ov_month",
        )

    with fc3:
        st.write("")
        st.write("")
        if st.button("Clear", key="mom_btn_clear", use_container_width=True):
            for k, v in _SEL_DEFAULTS.items():
                st.session_state[k] = v
            st.rerun()

    eff_cat = chosen_cat if chosen_cat != "(all)" else None
    eff_month = chosen_month if chosen_month != "(all)" else None

    st.divider()

    if eff_cat:
        cat_df = df[df["category"] == eff_cat]
        month_df = cat_df[cat_df["month"] == eff_month] if eff_month else cat_df

        heading = f"### {eff_cat}"
        if eff_month:
            heading += f" -- {eff_month}"
        st.markdown(heading)

        col_sub_chart, col_txn = st.columns([3, 2])

        with col_sub_chart:
            fig_sub = stacked_bar(cat_df, "sub_category", f"{eff_cat} -- Sub-categories")
            st.plotly_chart(fig_sub, key="mom_chart_sub", width="stretch")

            sub_opts = ["(all)"] + sorted(cat_df["sub_category"].unique())
            chosen_sub = st.selectbox(
                "Sub-category",
                sub_opts,
                index=sub_opts.index(st.session_state["ov_sub"])
                if st.session_state["ov_sub"] in sub_opts else 0,
                key="ov_sub",
            )

        eff_sub = chosen_sub if chosen_sub != "(all)" else None

        with col_txn:
            if eff_sub:
                txn_df = month_df[month_df["sub_category"] == eff_sub]
                ctx = f"{eff_cat} / {eff_sub}"
            else:
                txn_df = month_df
                ctx = eff_cat
            if eff_month:
                ctx += f" | {eff_month}"
            show_transactions(txn_df, ctx)

        if eff_sub:
            sub_df = cat_df[cat_df["sub_category"] == eff_sub]
            st.markdown(f"#### {eff_cat} / {eff_sub} -- Merchants")
            fig_merch = stacked_bar(sub_df, "merchant", f"Merchants in {eff_sub}")
            st.plotly_chart(fig_merch, key="mom_chart_merch", width="stretch")
    else:
        scope_df = df[df["month"] == eff_month] if eff_month else df
        label = eff_month or f"All selected years ({selected_years_label})"
        show_transactions(scope_df, label)


# =============================================================================
# TAB 3 -- TRANSACTIONS (editable)
# =============================================================================
with tab_txns:
    st.subheader("Transactions")
    st.caption(
        "Use one grid to edit, add, and delete transactions, then click Save Grid Changes."
    )

    raw_df = load_raw_transactions_for_years(
        DEFAULT_DB_PATH,
        tuple(selected_years),
        st.session_state["db_version"],
    )

    db_cats = load_all_categories(DEFAULT_DB_PATH, st.session_state["db_version"])
    cat_map: Dict[str, List[str]] = {}
    for _c in db_cats:
        cat_map.setdefault(_c["category"], []).append(_c["sub_category"])
    cat_options = [""] + sorted(cat_map.keys())
    sub_options = [""] + sorted({sub for subs in cat_map.values() for sub in subs})

    grid_cols = ["id", "date", "description", "amount", "category", "sub_category", "merchant"]
    if raw_df.empty:
        editor_df = pd.DataFrame(columns=grid_cols)
    else:
        editor_df = raw_df[grid_cols].copy()
        editor_df["date"] = editor_df["date"].dt.date
        editor_df["amount"] = pd.to_numeric(editor_df["amount"], errors="coerce")
    for text_col in ["description", "category", "sub_category", "merchant"]:
        if text_col in editor_df.columns:
            editor_df[text_col] = editor_df[text_col].fillna("").astype(str)

    # -- Filter & Sort controls ------------------------------------------------
    st.markdown("**Filter & Sort**")
    fc1, fc2, fc3, fc4 = st.columns(4)

    with fc1:
        filter_cat = st.selectbox(
            "Category",
            ["(all)"] + sorted(editor_df["category"].unique()) if not editor_df.empty else ["(all)"],
            key="txn_flt_cat",
        )
    with fc2:
        if filter_cat != "(all)" and not editor_df.empty:
            avail_subs = sorted(editor_df[editor_df["category"] == filter_cat]["sub_category"].unique())
        else:
            avail_subs = sorted(editor_df["sub_category"].unique()) if not editor_df.empty else []
        filter_sub = st.selectbox(
            "Sub-Category",
            ["(all)"] + avail_subs,
            key="txn_flt_sub",
        )
    with fc3:
        filter_merchant = st.text_input("Merchant (contains)", key="txn_flt_merch")
    with fc4:
        filter_desc = st.text_input("Description (contains)", key="txn_flt_desc")

    sc1, sc2, sc3 = st.columns([2, 2, 1])
    with sc1:
        sort_col = st.selectbox(
            "Sort by",
            ["date", "amount", "category", "sub_category", "merchant", "description"],
            key="txn_sort_col",
        )
    with sc2:
        sort_dir = st.radio("Direction", ["Ascending", "Descending"], horizontal=True, key="txn_sort_dir")
    with sc3:
        st.write("")
        st.write("")
        if st.button("Clear filters", key="txn_flt_clear", use_container_width=True):
            for k in ["txn_flt_cat", "txn_flt_sub", "txn_flt_merch", "txn_flt_desc"]:
                st.session_state[k] = "(all)" if k in ("txn_flt_cat", "txn_flt_sub") else ""
            st.rerun()

    # Apply filters to build display df; keep full editor_df for save logic
    display_mask = pd.Series(True, index=editor_df.index)
    if filter_cat != "(all)":
        display_mask &= editor_df["category"] == filter_cat
    if filter_sub != "(all)":
        display_mask &= editor_df["sub_category"] == filter_sub
    if filter_merchant.strip():
        display_mask &= editor_df["merchant"].str.contains(filter_merchant.strip(), case=False, na=False)
    if filter_desc.strip():
        display_mask &= editor_df["description"].str.contains(filter_desc.strip(), case=False, na=False)

    display_df = editor_df[display_mask].copy()
    display_df = display_df.sort_values(sort_col, ascending=(sort_dir == "Ascending"))

    st.caption(f"Showing {len(display_df)} of {len(editor_df)} transactions")

    edited_df = st.data_editor(
        display_df,
        key="txn_grid_editor",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True, step=1),
            "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
            "description": st.column_config.TextColumn("Description", required=True),
            "amount": st.column_config.NumberColumn("Amount ($)", min_value=0.01, step=0.01, required=True),
            "category": st.column_config.SelectboxColumn("Category", options=cat_options, required=False),
            "sub_category": st.column_config.SelectboxColumn("Sub-Category", options=sub_options, required=False),
            "merchant": st.column_config.TextColumn("Merchant", required=False),
        },
    )

    if st.button("Save Grid Changes", type="primary", use_container_width=True, key="txn_grid_save"):
        work = edited_df.copy()
        for col in grid_cols:
            if col not in work.columns:
                work[col] = pd.NA

        work["id"] = pd.to_numeric(work["id"], errors="coerce")
        work["date"] = pd.to_datetime(work["date"], errors="coerce")
        work["amount"] = pd.to_numeric(work["amount"], errors="coerce")
        for text_col in ["description", "category", "sub_category", "merchant"]:
            work[text_col] = work[text_col].fillna("").astype(str).str.strip()

        blank_rows = (
            work["id"].isna()
            & work["date"].isna()
            & work["amount"].isna()
            & (work["description"] == "")
            & (work["category"] == "")
            & (work["sub_category"] == "")
            & (work["merchant"] == "")
        )
        work = work[~blank_rows].copy()

        invalid_core = work[
            work["date"].isna()
            | work["amount"].isna()
            | (work["amount"] <= 0)
            | (work["description"] == "")
        ]
        if not invalid_core.empty:
            st.error("Each row must have a valid Date, Description, and Amount (> 0).")
        else:
            work["year"] = work["date"].dt.year.astype(int)
            invalid_years = sorted(set(work.loc[~work["year"].isin(selected_years), "year"].tolist()))
            if invalid_years:
                st.error(
                    "Grid contains dates outside selected years. "
                    f"Select these years first or adjust dates: {invalid_years}"
                )
            else:
                existing = work[work["id"].notna()].copy()
                if not existing.empty:
                    existing["id"] = existing["id"].astype(int)
                new_rows = work[work["id"].isna()].copy()

                # Only consider IDs that were displayed (after filters) as candidates for deletion
                displayed_ids = set(display_df["id"].dropna().astype(int).tolist()) if not display_df.empty else set()
                current_ids = set(existing["id"].tolist()) if not existing.empty else set()
                delete_ids = sorted(displayed_ids - current_ids)

                updates: List[Dict] = []
                if not existing.empty:
                    original_map = raw_df.set_index("id")
                    for row in existing.itertuples(index=False):
                        old = original_map.loc[int(row.id)]
                        old_date = pd.to_datetime(old["date"], errors="coerce")
                        changed = (
                            old_date != row.date
                            or str(old["description"]) != row.description
                            or float(old["amount"]) != float(row.amount)
                            or str(old["category"]) != row.category
                            or str(old["sub_category"]) != row.sub_category
                            or str(old["merchant"]) != row.merchant
                        )
                        if changed:
                            updates.append({
                                "id": int(row.id),
                                "year": int(row.year),
                                "date": row.date.strftime("%Y-%m-%d"),
                                "description": row.description,
                                "amount": float(row.amount),
                                "category": row.category,
                                "sub_category": row.sub_category,
                                "merchant": row.merchant,
                            })

                inserts_by_year: Dict[int, List[Dict]] = {}
                if not new_rows.empty:
                    for row in new_rows.itertuples(index=False):
                        inserts_by_year.setdefault(int(row.year), []).append({
                            "date": row.date.strftime("%Y-%m-%d"),
                            "description": row.description,
                            "amount": float(row.amount),
                            "category": row.category,
                            "sub_category": row.sub_category,
                            "merchant": row.merchant,
                        })

                try:
                    updated_count = bulk_update_transactions(DEFAULT_DB_PATH, updates) if updates else 0
                    inserted_count = 0
                    skipped_count = 0
                    for ins_year, txns in inserts_by_year.items():
                        stats = upsert_transactions(DEFAULT_DB_PATH, ins_year, txns)
                        inserted_count += int(stats.get("inserted", 0))
                        skipped_count += int(stats.get("skipped", 0))
                    for tx_id in delete_ids:
                        delete_transaction(DEFAULT_DB_PATH, int(tx_id))
                except Exception as e:
                    st.error(f"Failed to save grid changes: {e}")
                else:
                    if updated_count or inserted_count or skipped_count or delete_ids:
                        _bump_db_version()
                        st.success(
                            f"Saved. Updated: {updated_count}, Added: {inserted_count}, "
                            f"Skipped duplicates: {skipped_count}, Deleted: {len(delete_ids)}."
                        )
                        st.rerun()
                    else:
                        st.info("No changes to save.")


# =============================================================================
# TAB 4 -- CATEGORIES (CRUD + cascade rename)
# =============================================================================
with tab_cats:
    st.subheader("Manage Categories")
    st.caption(
        "Renaming a category or sub-category automatically updates all transactions "
        "that were classified under it."
    )

    all_cats = load_all_categories(DEFAULT_DB_PATH, st.session_state["db_version"])

    if all_cats:
        for cat in all_cats:
            label = f"{cat['category']} / {cat['sub_category']}"
            with st.expander(label):
                with st.form(key=f"edit_cat_{cat['id']}"):
                    ec1, ec2 = st.columns(2)
                    new_cat_val = ec1.text_input("Category", value=cat["category"])
                    new_sub_val = ec2.text_input("Sub-Category", value=cat["sub_category"])

                    eb1, eb2 = st.columns(2)
                    with eb1:
                        save_cat = st.form_submit_button("Save", type="primary")
                    with eb2:
                        del_cat = st.form_submit_button("Delete", type="secondary")

                    if save_cat:
                        if new_cat_val.strip() and new_sub_val.strip():
                            n = update_category(
                                DEFAULT_DB_PATH,
                                cat["id"],
                                new_cat_val.strip(),
                                new_sub_val.strip(),
                            )
                            _bump_db_version()
                            if n > 0:
                                st.success(f"Saved  {n} transaction(s) reclassified.")
                            else:
                                st.success("Saved.")
                            st.rerun()
                        else:
                            st.warning("Both fields are required.")

                    if del_cat:
                        delete_category(DEFAULT_DB_PATH, cat["id"])
                        _bump_db_version()
                        st.rerun()
    else:
        st.info("No categories defined yet.")

    st.divider()
    st.subheader("Add Category")
    with st.form("add_category_form"):
        ac1, ac2 = st.columns(2)
        new_cat_name = ac1.text_input("Category")
        new_sub_name = ac2.text_input("Sub-Category")
        if st.form_submit_button("Add"):
            if new_cat_name.strip() and new_sub_name.strip():
                try:
                    add_category(DEFAULT_DB_PATH, new_cat_name.strip(), new_sub_name.strip())
                    _bump_db_version()
                    st.success(f"Added: {new_cat_name.strip()} / {new_sub_name.strip()}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding category: {e}")
            else:
                st.warning("Both Category and Sub-Category are required.")


# =============================================================================
# TAB 5 -- REGEX RULES (CRUD)
# =============================================================================
with tab_rules:
    st.subheader("Manage Regex Rules")
    st.caption("Rules are evaluated in priority order (lower number = higher priority). First match wins.")

    all_rules = load_all_rules(DEFAULT_DB_PATH, st.session_state["db_version"])

    if all_rules:
        for rule in all_rules:
            status = "" if rule["enabled"] else "  DISABLED"
            label = f"[{rule['priority']}] `{rule['pattern']}`  {rule['category']} / {rule['sub_category']}{status}"
            with st.expander(label):
                with st.form(key=f"edit_rule_{rule['id']}"):
                    er1, er2 = st.columns(2)
                    new_pattern = er1.text_input("Pattern", value=rule["pattern"])
                    new_priority = er2.number_input("Priority", value=int(rule["priority"]), step=1)

                    er3, er4 = st.columns(2)
                    new_rule_cat = er3.text_input("Category", value=rule["category"])
                    new_rule_sub = er4.text_input("Sub-Category", value=rule["sub_category"])

                    er5, er6 = st.columns(2)
                    new_merchant = er5.text_input("Merchant", value=rule["merchant"])
                    new_enabled = er6.checkbox("Enabled", value=bool(rule["enabled"]))

                    btn1, btn2 = st.columns(2)
                    with btn1:
                        save_clicked = st.form_submit_button("Save", type="primary")
                    with btn2:
                        delete_clicked = st.form_submit_button("Delete", type="secondary")

                    if save_clicked:
                        try:
                            re.compile(new_pattern)
                            update_regex_rule(
                                DEFAULT_DB_PATH,
                                rule["id"],
                                pattern=new_pattern,
                                category=new_rule_cat,
                                sub_category=new_rule_sub,
                                merchant=new_merchant,
                                priority=int(new_priority),
                                enabled=new_enabled,
                            )
                            _bump_db_version()
                            st.success("Rule saved.")
                            st.rerun()
                        except re.error as e:
                            st.error(f"Invalid regex pattern: {e}")

                    if delete_clicked:
                        delete_regex_rule(DEFAULT_DB_PATH, rule["id"])
                        _bump_db_version()
                        st.rerun()
    else:
        st.info("No regex rules defined yet.")

    st.divider()
    st.subheader("Add New Rule")
    with st.form("add_rule_form"):
        ar1, ar2 = st.columns(2)
        r_pattern = ar1.text_input("Pattern (regex)")
        r_priority = ar2.number_input("Priority", value=0, step=1)

        ar3, ar4 = st.columns(2)
        r_cat = ar3.text_input("Category")
        r_sub = ar4.text_input("Sub-Category")

        ar5, ar6 = st.columns(2)
        r_merch = ar5.text_input("Merchant")
        r_enabled = ar6.checkbox("Enabled", value=True)

        if st.form_submit_button("Add Rule"):
            if r_pattern.strip() and r_cat.strip() and r_sub.strip():
                try:
                    re.compile(r_pattern.strip())
                    add_regex_rule(
                        DEFAULT_DB_PATH,
                        r_pattern.strip(),
                        r_cat.strip(),
                        r_sub.strip(),
                        r_merch.strip(),
                        int(r_priority),
                        r_enabled,
                    )
                    _bump_db_version()
                    st.success(f"Added rule for `{r_pattern.strip()}`.")
                    st.rerun()
                except re.error as e:
                    st.error(f"Invalid regex pattern: {e}")
            else:
                st.warning("Pattern, Category, and Sub-Category are required.")
