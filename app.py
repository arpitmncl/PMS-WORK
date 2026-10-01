#### Changes from app6.py : New Logic For Client Wise Split in Case of Same Analyst, Same Stock, Same Date
#### Changes from app7.py : Formatting of Page, Colors, Background (Frontend Changes)
#### Changes from app8.py : Further one more layer of split quantities in same client for different analysts, same stock, same date
#### Changes from app10.py : Nuvama Input File Format Changed


import io
import re
from datetime import datetime
from typing import Dict, Tuple

import pandas as pd
import requests
import urllib.parse
import os
import streamlit as st
import yfinance as yf


VALID_TRANSACTION_TYPES = {"BUY", "SELL"}
VALID_TRANSACTION_TAGS = {"Dhruv", "Shaukat", "Gaurav"}

OUTPUT_COLUMNS = [
    "Acc number",
    "UCC",
    "Transaction Description",
    "Tran Date",
    "Settlement Date",
    "Security",
    "ISIN",
    "Quantity",
    "Rate",
    "Brokerage",
    "STT",
    "Tran Amount",
    "Transaction Rate",
    "Orignal Pur Date",
    "Transaction Tagging"
]

PORTFOLIO_COLUMNS = [
    "Client UCC",
    "Category",
    "Company",
    "ISIN",
    "Units",
    "Wt Avg Cost",
    "Current Price",
    "Market Value",
    "Realised P&L",
    "Unrealised P&L",
]

ISIN_TICKER_MAPPING_FILE = "ISIN-TICKER-MAPPING.csv"


def parse_monarch_transactions(raw: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    skipped_rows = []

    n = len(raw)
    i = 0

    while i < n:
        first_cell = str(raw.iloc[i, 0]).strip()

        if first_cell == "MONARCH NETWORTH CAPITAL LIMITED":
            account_line = None
            header_row = None
            shares_row = None

            for k in range(i, min(i + 20, n)):
                value = str(raw.iloc[k, 0]).strip()
                if value.startswith("Account :"):
                    account_line = value
                    break

            if account_line is None:
                skipped_rows.append({"Row": i, "Reason": "Account line not found"})
                i += 1
                continue

            acc_match = re.search(r'Account\s*:\s*(\d{8})', account_line)
            if not acc_match:
                skipped_rows.append({"Row": i, "Reason": f"Invalid Account Line: {account_line}"})
                i += 1
                continue

            acc_number = acc_match.group(1)
            if not re.fullmatch(r"\d{8}", acc_number):
                skipped_rows.append({"Row": i, "Reason": f"Invalid Account Number: {acc_number}"})
                i += 1
                continue

            ucc_match = re.search(r'\b(MWCF[A-Z0-9]+)\b', account_line, flags=re.IGNORECASE)
            if not ucc_match:
                skipped_rows.append({"Row": i, "Reason": f"Invalid UCC in line: {account_line}"})
                i += 1
                continue

            ucc = ucc_match.group(1).upper()

            for k in range(i, min(i + 30, n)):
                value = str(raw.iloc[k, 0]).strip()
                if value == "Transaction Description":
                    header_row = k
                    break

            if header_row is None:
                skipped_rows.append({"Row": i, "Reason": "Transaction Header not found"})
                i += 1
                continue

            required_transaction_columns = [
                "Transaction Description",
                "Tran Date",
                "Settlement Date",
                "Security",
                "ISIN",
                "Quantity",
                "Rate",
                "Brokerage",
                "STT",
                "Tran Amount",
                "Transaction Rate",
                "Orignal Pur Date",
            ]
            header_indexes = {
                str(raw.iloc[header_row, column]).strip(): column
                for column in range(raw.shape[1])
                if str(raw.iloc[header_row, column]).strip()
            }
            missing_columns = [
                column for column in required_transaction_columns
                if column not in header_indexes
            ]
            if missing_columns:
                skipped_rows.append({
                    "Row": header_row,
                    "Reason": f"Transaction Header missing columns: {', '.join(missing_columns)}",
                })
                i = header_row + 1
                continue

            for k in range(header_row, min(header_row + 15, n)):
                value = str(raw.iloc[k, 0]).strip()
                if value.startswith("Shares - "):
                    shares_row = k
                    break

            if shares_row is None:
                skipped_rows.append({"Row": i, "Reason": "Shares - Listed row not found"})
                i += 1
                continue

            start_row = shares_row + 1
            j = start_row

            while j < n:
                current_first_cell = str(raw.iloc[j, 0]).strip()
                if current_first_cell == "MONARCH NETWORTH CAPITAL LIMITED":
                    break

                row = raw.iloc[j]
                if row.isna().all():
                    j += 1
                    continue

                if any(header_indexes[column] >= len(row) for column in required_transaction_columns):
                    skipped_rows.append({"Row": j, "Reason": "Transaction row has fewer columns than its header"})
                    j += 1
                    continue

                transaction_values = {
                    column: str(row.iloc[header_indexes[column]]).strip()
                    for column in required_transaction_columns
                }
                transaction_desc = transaction_values["Transaction Description"].upper()
                if transaction_desc not in VALID_TRANSACTION_TYPES:
                    j += 1
                    continue

                quantity = transaction_values["Quantity"]
                if transaction_desc == "SELL" and quantity:
                    quantity = f"-{quantity.lstrip('-')}"

                records.append({
                    "Acc number": acc_number,
                    "UCC": ucc,
                    "Transaction Description": transaction_values["Transaction Description"],
                    "Tran Date": transaction_values["Tran Date"],
                    "Settlement Date": transaction_values["Settlement Date"],
                    "Security": transaction_values["Security"],
                    "ISIN": transaction_values["ISIN"],
                    "Quantity": quantity,
                    "Rate": transaction_values["Rate"],
                    "Brokerage": transaction_values["Brokerage"],
                    "STT": transaction_values["STT"],
                    "Tran Amount": transaction_values["Tran Amount"],
                    "Transaction Rate": transaction_values["Transaction Rate"],
                    "Orignal Pur Date": transaction_values["Orignal Pur Date"],
                    "Transaction Tagging": ""
                })

                j += 1

            i = j
        else:
            i += 1

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), pd.DataFrame(skipped_rows)

    for col in df.columns:
        if df[col].dtype == "object" or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].astype(str).str.strip()

    normalized_tran_dates = df["Tran Date"].str.replace("/", "-", regex=False)
    df["Tran Date"] = pd.to_datetime(
        normalized_tran_dates,
        format="%d-%m-%Y",
        errors="coerce",
    )

    required_columns = ["Tran Date", "UCC", "Security", "Quantity"]
    df = df.dropna(subset=required_columns)
    df = df[df["Security"].str.strip() != ""]
    df = df[df["Quantity"].str.strip() != ""]
    df = df[df["UCC"].str.strip() != ""]

    df["Tran Date"] = df["Tran Date"].dt.strftime("%d-%m-%Y")
    df = df[OUTPUT_COLUMNS]

    return df, pd.DataFrame(skipped_rows)


def _normalize_tagging_dataframe(tagging_raw: pd.DataFrame) -> pd.DataFrame:
    required_columns = ["ISIN", "Transaction", "Date", "Transaction Tagging"]
    missing_columns = [col for col in required_columns if col not in tagging_raw.columns]
    if missing_columns:
        raise ValueError(f"Tagging file is missing columns: {', '.join(missing_columns)}")

    tagging_df = tagging_raw.copy()
    for col in ["ISIN", "Transaction", "Transaction Tagging", "Security", "Client UCC", "Quantity", "Date"]:
        if col in tagging_df.columns:
            tagging_df[col] = tagging_df[col].astype(str).str.strip()
        else:
            tagging_df[col] = ""

    parsed_dates = pd.to_datetime(tagging_df["Date"], errors="coerce")
    missing_dates = parsed_dates.isna()
    if missing_dates.any():
        parsed_dates.loc[missing_dates] = pd.to_datetime(
            tagging_df.loc[missing_dates, "Date"].astype(str).str.strip(),
            dayfirst=True,
            errors="coerce"
        )

    tagging_df["Tran Date"] = parsed_dates.dt.strftime("%d-%m-%Y")
    tagging_df["ISIN"] = tagging_df["ISIN"].str.upper()
    tagging_df["Transaction Description"] = tagging_df["Transaction"].str.upper()
    tagging_df["Tag Key"] = tagging_df["Transaction Tagging"].astype(str).str.strip()
    tagging_df["Client UCC"] = tagging_df["Client UCC"].astype(str).str.strip().str.upper()
    tagging_df["Quantity Numeric"] = parse_amount_series(tagging_df["Quantity"])
    tagging_df["Quantity Abs"] = tagging_df["Quantity Numeric"].abs()

    tagging_df = tagging_df[
        tagging_df["Tran Date"].notna()
        & tagging_df["ISIN"].ne("")
        & tagging_df["Transaction Description"].isin(VALID_TRANSACTION_TYPES)
        & tagging_df["Tag Key"].isin(VALID_TRANSACTION_TAGS)
    ]

    return tagging_df


def _expand_transactions_for_client_split(result_df: pd.DataFrame, tagging_df: pd.DataFrame) -> pd.DataFrame:
    if result_df.empty or tagging_df.empty:
        return result_df.copy()

    normalized = result_df.copy()
    normalized["Tran Date"] = normalized["Tran Date"].astype(str).str.strip()
    normalized["Tag Match ISIN"] = normalized["ISIN"].astype(str).str.strip().str.upper()
    normalized["Tag Match Transaction Description"] = (
        normalized["Transaction Description"].astype(str).str.strip().str.upper()
    )
    normalized["Tag Match Client UCC"] = normalized["UCC"].astype(str).str.strip().str.upper()
    normalized["Quantity Numeric"] = parse_amount_series(normalized["Quantity"])
    normalized["Tag Match Quantity Abs"] = normalized["Quantity Numeric"].abs()

    grouping_stats = (
        tagging_df.groupby(
            ["Tran Date", "ISIN", "Transaction Description", "Client UCC"],
            dropna=False,
        )
        .agg(
            TaggedQuantitySum=("Quantity Abs", "sum"),
            TagEntryCount=("Tag Key", "count"),
        )
        .reset_index()
    )

    merged = normalized.merge(
        grouping_stats,
        left_on=["Tran Date", "Tag Match ISIN", "Tag Match Transaction Description", "Tag Match Client UCC"],
        right_on=["Tran Date", "ISIN", "Transaction Description", "Client UCC"],
        how="left",
        suffixes=("", "_taggroup"),
    )

    if merged["TagEntryCount"].fillna(0).astype(int).sum() == 0:
        return result_df.copy()

    expand_mask = (
        (merged["TagEntryCount"].fillna(0).astype(int) > 1)
        & (merged["TaggedQuantitySum"].fillna(0) == merged["Tag Match Quantity Abs"])
    )

    original_columns = result_df.columns.tolist()
    normal_rows = merged.loc[~expand_mask, original_columns].copy()
    rows_to_expand = merged.loc[expand_mask].copy()
    if rows_to_expand.empty:
        return result_df.copy()

    rows_to_expand = rows_to_expand.merge(
        tagging_df[["Tran Date", "ISIN", "Transaction Description", "Client UCC", "Quantity Abs", "Tag Key"]],
        left_on=["Tran Date", "Tag Match ISIN", "Tag Match Transaction Description", "Tag Match Client UCC"],
        right_on=["Tran Date", "ISIN", "Transaction Description", "Client UCC"],
        how="left",
        suffixes=("", "_tag"),
    )

    def _row_quantity_with_sign(row):
        sign = 1 if row["Quantity Numeric"] >= 0 else -1
        return str(int(row["Quantity Abs"] * sign))

    rows_to_expand["Quantity"] = rows_to_expand.apply(_row_quantity_with_sign, axis=1)
    rows_to_expand["Transaction Tagging"] = rows_to_expand["Tag Key"].fillna("")
    expanded_rows = rows_to_expand[original_columns].copy()

    return pd.concat([normal_rows, expanded_rows], ignore_index=True, sort=False)


def add_transaction_tagging(result_df: pd.DataFrame, tagging_raw: pd.DataFrame) -> pd.DataFrame:
    tagging_df = _normalize_tagging_dataframe(tagging_raw)
    result_df = _expand_transactions_for_client_split(result_df, tagging_df)

    tagged_result = result_df.copy()
    tagged_result["Tag Match ISIN"] = tagged_result["ISIN"].astype(str).str.strip().str.upper()
    tagged_result["Tag Match Transaction Description"] = (
        tagged_result["Transaction Description"].astype(str).str.strip().str.upper()
    )
    tagged_result["Tag Match Client UCC"] = tagged_result["UCC"].astype(str).str.strip().str.upper()
    tagged_result["Tag Match Quantity Abs"] = parse_amount_series(tagged_result["Quantity"]).abs()

    exact_lookup = tagging_df.rename(
        columns={
            "ISIN": "Tag Match ISIN",
            "Transaction Description": "Tag Match Transaction Description",
            "Client UCC": "Tag Match Client UCC",
            "Quantity Abs": "Tag Match Quantity Abs",
            "Transaction Tagging": "Exact Transaction Tagging",
        }
    )[
        [
            "Tran Date",
            "Tag Match ISIN",
            "Tag Match Transaction Description",
            "Tag Match Client UCC",
            "Tag Match Quantity Abs",
            "Exact Transaction Tagging",
        ]
    ].drop_duplicates(
        subset=[
            "Tran Date",
            "Tag Match ISIN",
            "Tag Match Transaction Description",
            "Tag Match Client UCC",
            "Tag Match Quantity Abs",
        ],
        keep="last"
    )

    tagged_result = tagged_result.merge(
        exact_lookup,
        how="left",
        on=[
            "Tran Date",
            "Tag Match ISIN",
            "Tag Match Transaction Description",
            "Tag Match Client UCC",
            "Tag Match Quantity Abs",
        ],
    )

    grouped_tags = (
        tagging_df.groupby(["Tran Date", "ISIN", "Transaction Description"], dropna=False)["Tag Key"]
        .nunique()
        .reset_index(name="TagCount")
    )
    single_tag_groups = grouped_tags[grouped_tags["TagCount"] == 1]
    fallback_lookup = pd.merge(
        single_tag_groups,
        tagging_df[["Tran Date", "ISIN", "Transaction Description", "Tag Key"]].drop_duplicates(),
        on=["Tran Date", "ISIN", "Transaction Description"],
        how="left",
    ).rename(columns={"Tag Key": "Fallback Transaction Tagging"})[
        ["Tran Date", "ISIN", "Transaction Description", "Fallback Transaction Tagging"]
    ]

    tagged_result = tagged_result.merge(
        fallback_lookup,
        how="left",
        left_on=["Tran Date", "Tag Match ISIN", "Tag Match Transaction Description"],
        right_on=["Tran Date", "ISIN", "Transaction Description"],
    )

    tagged_result["Transaction Tagging"] = tagged_result["Exact Transaction Tagging"].fillna(
        tagged_result["Fallback Transaction Tagging"]
    ).fillna("")

    tagged_result = tagged_result.drop(
        columns=[
            "Tag Match ISIN",
            "Tag Match Transaction Description",
            "Tag Match Client UCC",
            "Tag Match Quantity Abs",
            "Exact Transaction Tagging",
            "Fallback Transaction Tagging",
            "ISIN",
            "Transaction Description",
        ],
        errors="ignore",
    )

    tagged_result["ISIN"] = result_df["ISIN"].astype(str).str.strip()
    tagged_result["Transaction Description"] = result_df["Transaction Description"].astype(str).str.strip()

    return tagged_result[OUTPUT_COLUMNS]


def compute_transaction_quantity_mismatch(
    result_df: pd.DataFrame,
    tagging_raw: pd.DataFrame,
) -> pd.DataFrame:
    tagging_df = _normalize_tagging_dataframe(tagging_raw)
    # Group parsed quantities and capture a representative Security value from result_df
    result_grouped = (
        result_df.assign(
            Tran_Date=result_df["Tran Date"].astype(str).str.strip(),
            ISIN_Key=result_df["ISIN"].astype(str).str.strip().str.upper(),
            Transaction_Type=result_df["Transaction Description"].astype(str).str.strip().str.upper(),
            Quantity_Abs=parse_amount_series(result_df["Quantity"]).abs(),
            Security=result_df.get("Security", ""),
        )
        [["Tran_Date", "ISIN_Key", "Transaction_Type", "Quantity_Abs", "Security"]]
        .groupby(["Tran_Date", "ISIN_Key", "Transaction_Type"], dropna=False)
        .agg({"Quantity_Abs": "sum", "Security": "first"})
        .reset_index()
        .rename(
            columns={
                "Tran_Date": "Tran Date",
                "ISIN_Key": "ISIN",
                "Transaction_Type": "Transaction Description",
                "Quantity_Abs": "Parsed Quantity",
                "Security": "Security",
            }
        )
    )

    tagging_grouped = (
        tagging_df.groupby(["Tran Date", "ISIN", "Transaction Description"], dropna=False)["Quantity Abs"]
        .sum()
        .reset_index()
        .rename(columns={"Quantity Abs": "Tagged Quantity"})
    )

    mismatch = pd.merge(
        result_grouped,
        tagging_grouped,
        on=["Tran Date", "ISIN", "Transaction Description"],
        how="outer",
    ).fillna(0)
    mismatch = mismatch[mismatch["Parsed Quantity"] != mismatch["Tagged Quantity"]].copy()
    if mismatch.empty:
        return mismatch

    mismatch["Parsed Quantity"] = mismatch["Parsed Quantity"].astype(float)
    mismatch["Tagged Quantity"] = mismatch["Tagged Quantity"].astype(float)
    # Ensure Security appears before ISIN in summary
    cols_order = [
        "Tran Date",
        "Security",
        "ISIN",
        "Transaction Description",
        "Parsed Quantity",
        "Tagged Quantity",
    ]
    existing_cols = [c for c in cols_order if c in mismatch.columns]
    other_cols = [c for c in mismatch.columns if c not in existing_cols]
    return mismatch[existing_cols + other_cols].sort_values(["Tran Date", "ISIN", "Transaction Description"]).reset_index(drop=True)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def dataframes_to_excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


def parse_amount_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("\u20b9", "", regex=False)
        .str.replace("Rs.", "", regex=False)
        .str.replace("Rs", "", regex=False)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


@st.cache_data(ttl=60 * 15)
def get_current_prices(symbols: Tuple[str, ...]) -> Dict[str, float]:
    clean_symbols = sorted({
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip()
    })
    if not clean_symbols:
        return {}

    ticker_symbols = [f"{symbol}.NS" for symbol in clean_symbols]
    prices = {symbol: float("nan") for symbol in clean_symbols}

    try:
        history = yf.download(
            tickers=ticker_symbols,
            period="1d",
            group_by="ticker",
            progress=False,
            threads=True,
            auto_adjust=False,
        )
        if len(ticker_symbols) == 1:
            close_series = history["Close"].dropna()
            if not close_series.empty:
                prices[clean_symbols[0]] = float(close_series.iloc[-1])
        else:
            ticker_level = history.columns.get_level_values(0)
            for symbol, ticker_symbol in zip(clean_symbols, ticker_symbols):
                if ticker_symbol in ticker_level:
                    close_series = history[ticker_symbol]["Close"].dropna()
                    if not close_series.empty:
                        prices[symbol] = float(close_series.iloc[-1])
    except Exception:
        pass

    missing_symbols = [symbol for symbol, price in prices.items() if pd.isna(price)]
    for symbol in missing_symbols:
        ticker_symbol = f"{symbol}.NS"
        ticker = yf.Ticker(ticker_symbol)

        try:
            fast_info_price = ticker.fast_info.get("last_price")
            if fast_info_price is not None:
                prices[symbol] = float(fast_info_price)
                continue
        except Exception:
            pass

        try:
            history = ticker.history(period="1d")
            if not history.empty:
                close_series = history["Close"].dropna()
                if not close_series.empty:
                    prices[symbol] = float(close_series.iloc[-1])
        except Exception:
            pass

    return prices


def load_isin_symbol_map(mapping_path: str = ISIN_TICKER_MAPPING_FILE) -> Dict[str, str]:
    mapping_df = pd.read_csv(mapping_path, dtype=str, keep_default_na=False)
    required_columns = ["ISIN", "SYMBOL"]
    missing_columns = [col for col in required_columns if col not in mapping_df.columns]
    if missing_columns:
        raise ValueError(f"ISIN ticker mapping file is missing columns: {', '.join(missing_columns)}")

    mapping_df = mapping_df[required_columns].copy()
    mapping_df["ISIN"] = mapping_df["ISIN"].astype(str).str.strip().str.upper()
    mapping_df["SYMBOL"] = mapping_df["SYMBOL"].astype(str).str.strip().str.upper()
    mapping_df = mapping_df[mapping_df["ISIN"].ne("") & mapping_df["SYMBOL"].ne("")]

    return mapping_df.drop_duplicates(subset=["ISIN"], keep="last").set_index("ISIN")["SYMBOL"].to_dict()


def build_portfolio_summary(
    result_df: pd.DataFrame,
    isin_symbol_map: Dict[str, str],
    fetch_live_prices: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    if result_df.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS), pd.DataFrame(), "Not fetched"

    working_df = result_df.copy()
    working_df["Quantity Numeric"] = parse_amount_series(working_df["Quantity"])
    working_df["Rate Numeric"] = parse_amount_series(working_df["Rate"])
    working_df["Tran Amount Numeric"] = parse_amount_series(working_df["Tran Amount"])
    working_df["Client UCC"] = working_df["UCC"].astype(str).str.strip()
    working_df["Category"] = working_df["Transaction Tagging"].astype(str).str.strip()
    working_df["Company"] = working_df["Security"].astype(str).str.strip()
    working_df["ISIN Key"] = working_df["ISIN"].astype(str).str.strip().str.upper()
    working_df["Transaction Type"] = working_df["Transaction Description"].astype(str).str.strip().str.upper()
    working_df["Tran Date Parsed"] = pd.to_datetime(
        working_df["Tran Date"], format="%d-%m-%Y", errors="coerce"
    )

    working_df["Ticker Symbol"] = working_df["ISIN Key"].map(isin_symbol_map).fillna("")
    price_diagnostics = []
    unmapped_df = working_df[working_df["ISIN Key"].ne("") & working_df["Ticker Symbol"].eq("")]
    if not unmapped_df.empty:
        price_diagnostics.extend(
            unmapped_df[["Client UCC", "Category", "Company", "ISIN Key"]]
            .drop_duplicates()
            .rename(columns={"ISIN Key": "ISIN"})
            .assign(Symbol="", Issue="ISIN not found in ticker mapping")
            .to_dict("records")
        )

    price_fetch_timestamp = "Not fetched"
    price_by_symbol = {}
    if fetch_live_prices:
        symbols = tuple(working_df["Ticker Symbol"].dropna().unique())
        price_by_symbol = get_current_prices(symbols)
        price_fetch_timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        missing_price_symbols = {
            symbol for symbol, price in price_by_symbol.items()
            if pd.isna(price)
        }
        missing_price_df = working_df[working_df["Ticker Symbol"].isin(missing_price_symbols)]
        if not missing_price_df.empty:
            price_diagnostics.extend(
                missing_price_df[["Client UCC", "Category", "Company", "ISIN Key", "Ticker Symbol"]]
                .drop_duplicates()
                .rename(columns={"ISIN Key": "ISIN", "Ticker Symbol": "Symbol"})
                .assign(Issue="Yahoo price not found")
                .to_dict("records")
            )

    def compute_running_avg_cost(transactions: pd.DataFrame) -> Tuple[float, float]:
        avg_cost = 0.0
        units = 0.0
        realised_pnl = 0.0
        ordered = transactions.sort_values(
            by=["Tran Date Parsed"],
            kind="mergesort",
            na_position="last"
        )

        for _, row in ordered.iterrows():
            quantity = row["Quantity Numeric"]
            rate = row["Rate Numeric"]
            transaction_type = row["Transaction Type"]

            if transaction_type == "BUY" and quantity > 0:
                total_cost = units * avg_cost + quantity * rate
                units += quantity
                avg_cost = total_cost / units if units else 0.0
            elif transaction_type == "SELL" and quantity < 0:
                sell_qty = abs(quantity)
                realised_pnl += (rate - avg_cost) * sell_qty
                units -= sell_qty
                if units <= 0:
                    units = 0.0
                    avg_cost = 0.0

        return avg_cost, realised_pnl

    summary_rows = []
    group_columns = ["Client UCC", "Category", "Company", "ISIN Key"]
    for group_values, group_df in working_df.groupby(group_columns, dropna=False, sort=True):
        wt_avg_cost, realised_pnl = compute_running_avg_cost(group_df)
        units = group_df["Quantity Numeric"].sum()

        group_symbols = group_df["Ticker Symbol"].dropna()
        current_price = float("nan")
        if not group_symbols.empty:
            current_price = price_by_symbol.get(group_symbols.iloc[-1], float("nan"))

        market_value = units * current_price if pd.notna(current_price) else float("nan")
        unrealised_pnl = (
            (current_price - wt_avg_cost) * units
            if pd.notna(current_price)
            else float("nan")
        )

        summary_rows.append({
            "Client UCC": group_values[0],
            "Category": group_values[1],
            "Company": group_values[2],
            "ISIN": group_values[3],
            "Units": units,
            "Wt Avg Cost": wt_avg_cost,
            "Current Price": current_price,
            "Market Value": market_value,
            "Realised P&L": realised_pnl,
            "Unrealised P&L": unrealised_pnl,
        })

    summary_df = pd.DataFrame(summary_rows, columns=PORTFOLIO_COLUMNS)
    numeric_columns = [
        "Units",
        "Wt Avg Cost",
        "Current Price",
        "Market Value",
        "Realised P&L",
        "Unrealised P&L",
    ]
    summary_df[numeric_columns] = summary_df[numeric_columns].round(2)

    diagnostics_df = pd.DataFrame(
        price_diagnostics,
        columns=["Client UCC", "Category", "Company", "ISIN", "Symbol", "Issue"],
    )

    return summary_df, diagnostics_df, price_fetch_timestamp


def compute_running_avg_cost(transactions: pd.DataFrame) -> Tuple[float, float]:
    avg_cost = 0.0
    units = 0.0
    realised_pnl = 0.0
    ordered = transactions.sort_values(
        by=["Tran Date Parsed"],
        kind="mergesort",
        na_position="last"
    )

    for _, row in ordered.iterrows():
        quantity = row["Quantity Numeric"]
        rate = row["Rate Numeric"]
        transaction_type = row["Transaction Type"]

        if transaction_type == "BUY" and quantity > 0:
            total_cost = units * avg_cost + quantity * rate
            units += quantity
            avg_cost = total_cost / units if units else 0.0
        elif transaction_type == "SELL" and quantity < 0:
            sell_qty = abs(quantity)
            realised_pnl += (rate - avg_cost) * sell_qty
            units -= sell_qty
            if units <= 0:
                units = 0.0
                avg_cost = 0.0

    return avg_cost, realised_pnl


@st.cache_data(ttl=60 * 15)
def get_current_and_previous_prices(symbols: Tuple[str, ...]) -> Dict[str, Dict[str, float]]:
    clean_symbols = sorted({
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip()
    })
    if not clean_symbols:
        return {}

    price_map: Dict[str, Dict[str, float]] = {
        symbol: {"Current Price": float("nan"), "Previous Close": float("nan")}
        for symbol in clean_symbols
    }

    for symbol in clean_symbols:
        ticker_symbol = f"{symbol}.NS"
        ticker = yf.Ticker(ticker_symbol)

        try:
            fast_info = ticker.fast_info
            fast_info_price = fast_info.get("last_price")
            if fast_info_price is not None:
                price_map[symbol]["Current Price"] = float(fast_info_price)

            if pd.isna(price_map[symbol]["Previous Close"]):
                previous_close = fast_info.get("previous_close")
                if previous_close is not None:
                    price_map[symbol]["Previous Close"] = float(previous_close)
        except Exception:
            pass

        try:
            history = ticker.history(period="5d", auto_adjust=False, actions=False)
            if not history.empty:
                close_series = history["Close"].dropna()
                if not close_series.empty:
                    if pd.isna(price_map[symbol]["Current Price"]):
                        price_map[symbol]["Current Price"] = float(close_series.iloc[-1])
                    if pd.isna(price_map[symbol]["Previous Close"]) and len(close_series) >= 2:
                        price_map[symbol]["Previous Close"] = float(close_series.iloc[-2])
        except Exception:
            pass

    return price_map


def build_consolidated_summaries(
    result_df: pd.DataFrame,
    isin_symbol_map: Dict[str, str],
    fetch_live_prices: bool = True,
) -> Dict[str, pd.DataFrame]:
    if result_df.empty:
        empty_df = pd.DataFrame(columns=[
            "Company [Total Holdings: 0]",
            "Units",
            "Wt Avg Cost",
            "Current Price",
            "Previous Close",
            "Market Value",
            "Today's Change",
            "Realised P&L",
            "Unrealised P&L",
        ])
        return {"PMS Consolidated": empty_df}

    working_df = result_df.copy()
    working_df["Quantity Numeric"] = parse_amount_series(working_df["Quantity"])
    working_df["Rate Numeric"] = parse_amount_series(working_df["Rate"])
    working_df["Tran Amount Numeric"] = parse_amount_series(working_df["Tran Amount"])
    working_df["Company"] = working_df["Security"].astype(str).str.strip()
    working_df["ISIN Key"] = working_df["ISIN"].astype(str).str.strip().str.upper()
    working_df["Transaction Type"] = working_df["Transaction Description"].astype(str).str.strip().str.upper()
    working_df["Tran Date Parsed"] = pd.to_datetime(
        working_df["Tran Date"], format="%d-%m-%Y", errors="coerce"
    )
    mapping_lookup = isin_symbol_map if isinstance(isin_symbol_map, dict) else dict(isin_symbol_map)
    working_df["Ticker Symbol"] = working_df["ISIN Key"].map(mapping_lookup).fillna("")
    working_df["Category"] = working_df["Transaction Tagging"].astype(str).str.strip()

    price_lookup: Dict[str, Dict[str, float]] = {}
    if fetch_live_prices:
        symbols = tuple(working_df["Ticker Symbol"].dropna().unique())
        price_lookup = get_current_and_previous_prices(symbols)

    portfolio_df, _, _ = build_portfolio_summary(
        result_df,
        isin_symbol_map,
        fetch_live_prices=fetch_live_prices,
    )
    portfolio_df = portfolio_df.copy()
    portfolio_df["Company"] = portfolio_df["Company"].astype(str).str.strip()
    portfolio_df["ISIN Key"] = portfolio_df["ISIN"].astype(str).str.strip().str.upper()
    portfolio_df["Category"] = portfolio_df["Category"].astype(str).str.strip()

    def get_price_metrics_for_group(group_company: str, group_isin: str) -> Tuple[float, float]:
        matching_transactions = working_df[
            (working_df["Company"].astype(str).str.strip() == group_company)
            & (working_df["ISIN Key"].astype(str).str.strip().str.upper() == group_isin.upper())
        ]
        if matching_transactions.empty:
            return float("nan"), float("nan")

        symbol = matching_transactions["Ticker Symbol"].dropna().iloc[-1] if not matching_transactions["Ticker Symbol"].dropna().empty else ""
        price_info = price_lookup.get(symbol, {}) if symbol else {}
        current_price = price_info.get("Current Price", float("nan"))
        previous_close = price_info.get("Previous Close", float("nan"))
        return float(current_price), float(previous_close)

    def compute_today_change_for_group(group_company: str, group_isin: str) -> float:
        matching_transactions = working_df[
            (working_df["Company"].astype(str).str.strip() == group_company)
            & (working_df["ISIN Key"].astype(str).str.strip().str.upper() == group_isin.upper())
        ]
        if matching_transactions.empty:
            return float("nan")

        current_price, previous_close = get_price_metrics_for_group(group_company, group_isin)
        if pd.isna(current_price) or pd.isna(previous_close):
            return float("nan")

        today = datetime.now().date()
        today_mask = matching_transactions["Tran Date Parsed"].dt.normalize() == pd.Timestamp(today)
        prior_mask = matching_transactions["Tran Date Parsed"].dt.normalize() < pd.Timestamp(today)
        today_transactions = matching_transactions.loc[today_mask]
        units_before_today = matching_transactions.loc[prior_mask]["Quantity Numeric"].sum()
        if not today_transactions.empty:
            today_change = units_before_today * (current_price - previous_close)
            today_change += (
                (today_transactions["Rate Numeric"] - previous_close) * today_transactions["Quantity Numeric"]
            ).sum()
        else:
            today_change = matching_transactions["Quantity Numeric"].sum() * (current_price - previous_close)
        return float(today_change)

    def build_summary_df(group_df: pd.DataFrame, group_columns: list) -> pd.DataFrame:
        summary_rows = []
        for _, group_values in group_df.groupby(group_columns, dropna=False, sort=True):
            group = group_df.loc[group_values.index]
            units = float(group["Units"].sum())
            weight = float((group["Units"] * group["Wt Avg Cost"]).sum()) if units else 0.0
            wt_avg_cost = weight / units if units else 0.0
            current_price = group["Current Price"].dropna().iloc[-1] if not group["Current Price"].dropna().empty else float("nan")
            market_value = float(group["Market Value"].sum())
            realised_pnl = float(group["Realised P&L"].sum())
            unrealised_pnl = float(group["Unrealised P&L"].sum())
            current_price, previous_close = get_price_metrics_for_group(
                str(group["Company"].iloc[0]).strip(),
                str(group["ISIN Key"].iloc[0]).strip(),
            )
            today_change = compute_today_change_for_group(
                str(group["Company"].iloc[0]).strip(),
                str(group["ISIN Key"].iloc[0]).strip(),
            )

            summary_rows.append({
                "Company": str(group["Company"].iloc[0]).strip(),
                "Units": units,
                "Wt Avg Cost": wt_avg_cost,
                "Current Price": current_price,
                "Previous Close": previous_close,
                "Market Value": market_value,
                "Today's Change": today_change,
                "Realised P&L": realised_pnl,
                "Unrealised P&L": unrealised_pnl,
            })

        summary_df = pd.DataFrame(summary_rows)
        if summary_df.empty:
            first_column_name = "Company [Total Holdings: 0]"
            return pd.DataFrame(columns=[
                first_column_name,
                "Units",
                "Wt Avg Cost",
                "Current Price",
                "Previous Close",
                "Market Value",
                "Today's Change",
                "Realised P&L",
                "Unrealised P&L",
            ])

        first_column_name = f"Company [Total Holdings: {len(summary_df)}]"
        summary_df = summary_df.rename(columns={"Company": first_column_name})
        numeric_columns = [
            "Units",
            "Wt Avg Cost",
            "Current Price",
            "Previous Close",
            "Market Value",
            "Today's Change",
            "Realised P&L",
            "Unrealised P&L",
        ]
        summary_df[numeric_columns] = summary_df[numeric_columns].round(2)
        return summary_df[[first_column_name] + numeric_columns]

    summaries: Dict[str, pd.DataFrame] = {}
    consolidated_df = build_summary_df(portfolio_df, ["Company", "ISIN Key"])
    summaries["PMS Consolidated"] = consolidated_df

    for analyst in sorted({value for value in working_df["Category"].dropna().unique() if str(value).strip()}):
        analyst_df = portfolio_df[portfolio_df["Category"].eq(analyst)]
        if analyst_df.empty:
            continue
        summaries[str(analyst)] = build_summary_df(analyst_df, ["Company", "ISIN Key"])

    return summaries


def set_page_style() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&display=swap');

        :root {
            --primary: #6366f1;
            --primary-dark: #4f46e5;
            --accent-teal: #14b8a6;
            --accent-rose: #f43f5e;
            --accent-amber: #f59e0b;
            --accent-violet: #8b5cf6;
            --text-primary: #1e1b4b;
            --text-secondary: #475569;
            --glass-bg: rgba(255, 255, 255, 0.72);
            --glass-border: rgba(255, 255, 255, 0.55);
            --shadow-soft: 0 8px 32px rgba(99, 102, 241, 0.12);
            --shadow-card: 0 20px 60px rgba(79, 70, 229, 0.14);
        }

        html, body, [class*="css"] {
            font-family: 'DM Sans', sans-serif !important;
        }

        .stApp {
            background:
                radial-gradient(ellipse 80% 60% at 10% 0%, rgba(99, 102, 241, 0.35) 0%, transparent 55%),
                radial-gradient(ellipse 70% 55% at 90% 10%, rgba(20, 184, 166, 0.28) 0%, transparent 50%),
                radial-gradient(ellipse 60% 50% at 50% 100%, rgba(244, 63, 94, 0.18) 0%, transparent 55%),
                radial-gradient(ellipse 50% 40% at 75% 60%, rgba(139, 92, 246, 0.22) 0%, transparent 50%),
                linear-gradient(160deg, #ede9fe 0%, #e0f2fe 30%, #fdf4ff 65%, #fff7ed 100%);
            color: var(--text-primary);
        }

        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2.5rem;
            max-width: 1200px;
        }

        /* ── Sidebar (light theme, bold readable text) ── */
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] > div:first-child {
            background: linear-gradient(180deg, #f0f4ff 0%, #e8eeff 50%, #f5f3ff 100%) !important;
            border-right: 1px solid rgba(99, 102, 241, 0.18);
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] ol,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] ul {
            color: #1e293b !important;
            font-weight: 500 !important;
            line-height: 1.55 !important;
        }

        [data-testid="stSidebar"] .stMarkdown h1,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
        [data-testid="stSidebar"] [data-testid="stHeadingWithActionElements"] h1,
        [data-testid="stSidebar"] [data-testid="stHeadingWithActionElements"] h2 {
            color: #1e1b4b !important;
            font-weight: 800 !important;
            font-size: 1.35rem !important;
            letter-spacing: -0.01em;
        }

        [data-testid="stSidebar"] .stMarkdown h2,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 {
            color: #312e81 !important;
            font-weight: 800 !important;
        }

        [data-testid="stSidebar"] .stMarkdown h3,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
            color: #3730a3 !important;
            font-weight: 700 !important;
        }

        [data-testid="stSidebar"] .stMarkdown h4,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h4 {
            color: #4338ca !important;
            font-weight: 700 !important;
            font-size: 1rem !important;
            margin-top: 0.6rem !important;
        }

        [data-testid="stSidebar"] .stCaption,
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: #334155 !important;
            font-weight: 600 !important;
            font-size: 0.88rem !important;
            line-height: 1.5 !important;
        }

        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        [data-testid="stSidebar"] label[data-testid="stWidgetLabel"] p,
        [data-testid="stSidebar"] label[data-testid="stWidgetLabel"] {
            color: #1e293b !important;
            font-weight: 700 !important;
            font-size: 0.92rem !important;
        }

        [data-testid="stSidebar"] hr {
            border: none !important;
            height: 1px !important;
            background: linear-gradient(90deg, transparent, rgba(99,102,241,0.35), transparent) !important;
            margin: 1rem 0 !important;
        }

        /* File uploader */
        [data-testid="stSidebar"] [data-testid="stFileUploader"] {
            background: #f8faff !important;
            border-radius: 14px;
            padding: 0.75rem;
            border: 1px solid #dbeafe;
            box-shadow: 0 2px 10px rgba(99, 102, 241, 0.06);
        }

        [data-testid="stSidebar"] [data-testid="stFileUploader"] label,
        [data-testid="stSidebar"] [data-testid="stFileUploader"] p,
        [data-testid="stSidebar"] [data-testid="stFileUploader"] span,
        [data-testid="stSidebar"] [data-testid="stFileUploader"] small,
        [data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] * {
            color: #1e1b4b !important;
            font-weight: 700 !important;
        }

        [data-testid="stSidebar"] [data-testid="stFileUploader"] button {
            background: #e8eeff !important;
            color: #312e81 !important;
            border: 1px solid #c7d2fe !important;
            border-radius: 10px !important;
            font-weight: 800 !important;
        }

        [data-testid="stSidebar"] [data-testid="stFileUploader"] button:hover {
            background: #dbeafe !important;
            color: #1e1b4b !important;
            border-color: #a5b4fc !important;
        }

        [data-testid="stSidebar"] [data-testid="stFileUploader"] section {
            background: #ffffff !important;
            border: 2px dashed #c7d2fe !important;
            border-radius: 10px !important;
        }

        [data-testid="stSidebar"] [data-testid="stFileUploader"] section * {
            color: #334155 !important;
            font-weight: 700 !important;
        }

        /* Checkbox */
        [data-testid="stSidebar"] .stCheckbox label span,
        [data-testid="stSidebar"] .stCheckbox label[data-testid="stWidgetLabel"] p {
            color: #1e293b !important;
            font-weight: 700 !important;
        }

        /* Sidebar buttons */
        [data-testid="stSidebar"] .stButton > button {
            background: linear-gradient(135deg, #0d9488, #14b8a6) !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 12px !important;
            font-weight: 700 !important;
            box-shadow: 0 4px 16px rgba(13, 148, 136, 0.35) !important;
            transition: transform 0.2s, box-shadow 0.2s !important;
        }

        [data-testid="stSidebar"] .stButton > button p,
        [data-testid="stSidebar"] .stButton > button span,
        [data-testid="stSidebar"] .stButton > button div {
            color: #ffffff !important;
            font-weight: 700 !important;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 8px 24px rgba(13, 148, 136, 0.45) !important;
        }

        [data-testid="stSidebar"] .stButton > button:disabled,
        [data-testid="stSidebar"] .stButton > button[disabled] {
            background: #cbd5e1 !important;
            color: #64748b !important;
            box-shadow: none !important;
            opacity: 1 !important;
        }

        [data-testid="stSidebar"] .stButton > button:disabled p,
        [data-testid="stSidebar"] .stButton > button:disabled span,
        [data-testid="stSidebar"] .stButton > button[disabled] p,
        [data-testid="stSidebar"] .stButton > button[disabled] span {
            color: #64748b !important;
            font-weight: 700 !important;
        }

        .sidebar-brand {
            text-align: center;
            padding: 0.9rem 0.6rem 1rem;
            background: linear-gradient(135deg, #eef2ff 0%, #f5f3ff 100%);
            border-radius: 16px;
            border: 1px solid #dbeafe;
            margin-bottom: 1.2rem;
            box-shadow: 0 2px 12px rgba(99, 102, 241, 0.08);
        }

        .sidebar-brand .brand-icon {
            font-size: 2.2rem;
            display: block;
            margin-bottom: 0.2rem;
        }

        .sidebar-brand h3 {
            margin: 0;
            font-size: 1.05rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #312e81 !important;
            font-weight: 800 !important;
        }

        /* ── Hero ── */
        .hero-banner {
            position: relative;
            overflow: hidden;
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 35%, #818cf8 65%, #14b8a6 100%);
            border-radius: 28px;
            padding: 2.4rem 2.8rem;
            margin-bottom: 2rem;
            box-shadow: var(--shadow-card);
        }

        .hero-banner::before {
            content: '';
            position: absolute;
            top: -40%;
            right: -10%;
            width: 340px;
            height: 340px;
            background: rgba(255, 255, 255, 0.12);
            border-radius: 50%;
            pointer-events: none;
        }

        .hero-banner::after {
            content: '';
            position: absolute;
            bottom: -50%;
            left: 5%;
            width: 260px;
            height: 260px;
            background: rgba(20, 184, 166, 0.25);
            border-radius: 50%;
            pointer-events: none;
        }

        .hero-banner h1 {
            position: relative;
            z-index: 1;
            color: #ffffff !important;
            font-size: 2.1rem;
            font-weight: 700;
            margin: 0 0 0.5rem 0;
            letter-spacing: -0.02em;
        }

        .hero-banner p {
            position: relative;
            z-index: 1;
            color: rgba(255, 255, 255, 0.88) !important;
            font-size: 1.05rem;
            margin: 0;
            max-width: 620px;
        }

        .hero-badge {
            position: relative;
            z-index: 1;
            display: inline-block;
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.35);
            border-radius: 999px;
            padding: 0.35rem 1rem;
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #ffffff;
            margin-bottom: 0.9rem;
        }

        /* ── Welcome / empty state ── */
        .welcome-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.2rem;
            margin-top: 1.5rem;
        }

        @media (max-width: 768px) {
            .welcome-grid { grid-template-columns: 1fr; }
        }

        .welcome-card {
            background: var(--glass-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 1.5rem;
            text-align: center;
            box-shadow: var(--shadow-soft);
            transition: transform 0.25s, box-shadow 0.25s;
        }

        .welcome-card:hover {
            transform: translateY(-4px);
            box-shadow: var(--shadow-card);
        }

        .welcome-card .wc-icon {
            font-size: 2rem;
            margin-bottom: 0.6rem;
        }

        .welcome-card h4 {
            color: var(--text-primary);
            margin: 0 0 0.4rem;
            font-size: 1rem;
            font-weight: 700;
        }

        .welcome-card p {
            color: var(--text-secondary);
            margin: 0;
            font-size: 0.88rem;
            line-height: 1.5;
        }

        /* ── Section cards ── */
        .section-card {
            border-radius: 24px;
            background: var(--glass-bg);
            backdrop-filter: blur(18px);
            border: 1px solid var(--glass-border);
            padding: 1.4rem 1.6rem;
            margin-bottom: 1.6rem;
            box-shadow: var(--shadow-soft);
        }

        .section-header {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(139, 92, 246, 0.08));
            border-left: 5px solid var(--primary);
            border-radius: 14px;
            padding: 0.75rem 1.1rem;
            margin-bottom: 1.1rem;
            color: var(--text-primary);
            font-size: 1.12rem;
            font-weight: 700;
        }

        .section-header .sh-icon {
            font-size: 1.3rem;
        }

        /* ── Metric cards ── */
        .metrics-row {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
        }

        @media (max-width: 900px) {
            .metrics-row { grid-template-columns: repeat(2, 1fr); }
        }

        .metric-card {
            border-radius: 20px;
            padding: 1.2rem 1.4rem;
            color: #ffffff;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12);
            transition: transform 0.2s;
        }

        .metric-card:hover {
            transform: translateY(-3px);
        }

        .metric-card .mc-label {
            font-size: 0.78rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            opacity: 0.88;
            margin-bottom: 0.3rem;
        }

        .metric-card .mc-value {
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.1;
        }

        .metric-card.mc-blue   { background: linear-gradient(135deg, #4f46e5, #6366f1); }
        .metric-card.mc-teal   { background: linear-gradient(135deg, #0d9488, #14b8a6); }
        .metric-card.mc-violet { background: linear-gradient(135deg, #7c3aed, #8b5cf6); }
        .metric-card.mc-rose   { background: linear-gradient(135deg, #e11d48, #f43f5e); }

        /* ── Dataframes ── */
        .dataframe-container {
            border-radius: 18px;
            padding: 0.5rem;
            background: rgba(255, 255, 255, 0.85);
            border: 1px solid rgba(99, 102, 241, 0.1);
        }

        [data-testid="stDataFrame"] {
            border-radius: 14px;
            overflow: hidden;
        }

        /* ── Alerts ── */
        [data-testid="stAlert"] {
            border-radius: 16px !important;
        }

        div[data-baseweb="notification"] {
            border-radius: 16px !important;
        }

        /* ── Buttons ── */
        .stDownloadButton > button,
        .stButton > button {
            border-radius: 14px !important;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark)) !important;
            color: white !important;
            border: none !important;
            padding: 0.75rem 1.2rem !important;
            font-weight: 600 !important;
            box-shadow: 0 6px 20px rgba(99, 102, 241, 0.35) !important;
            transition: transform 0.2s, box-shadow 0.2s !important;
        }

        .stDownloadButton > button:hover,
        .stButton > button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 10px 28px rgba(99, 102, 241, 0.5) !important;
        }

        .download-section .stDownloadButton > button {
            background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
            width: 100%;
        }

        /* ── Expanders ── */
        [data-testid="stExpander"] {
            background: rgba(255, 255, 255, 0.6);
            border: 1px solid rgba(99, 102, 241, 0.15);
            border-radius: 16px !important;
            margin-bottom: 0.6rem;
        }

        [data-testid="stExpander"] summary {
            font-weight: 700 !important;
            color: var(--text-primary) !important;
        }

        /* ── Tagging form ── */
        .tagging-banner {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(244, 63, 94, 0.1));
            border: 1px solid rgba(245, 158, 11, 0.35);
            border-radius: 20px;
            padding: 1.2rem 1.6rem;
            margin-bottom: 1.2rem;
        }

        .tagging-banner h3 {
            color: #92400e;
            margin: 0 0 0.3rem;
            font-size: 1.15rem;
        }

        .tagging-banner p {
            color: #78350f;
            margin: 0;
            font-size: 0.92rem;
        }

        /* ── Footer ── */
        .app-footer {
            text-align: center;
            padding: 1.5rem 0 0.5rem;
            color: var(--text-secondary);
            font-size: 0.82rem;
            opacity: 0.7;
        }

        /* ── Divider ── */
        hr {
            border: none;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(99,102,241,0.3), transparent);
            margin: 1.8rem 0;
        }

        /* Hide default Streamlit header/footer chrome */
        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }
        header[data-testid="stHeader"] {
            background: transparent !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Monarch Transaction Parser",
        page_icon="📊",
        layout="wide",
    )

    set_page_style()

    st.markdown(
        """
        <div class='hero-banner'>
            <div class='hero-badge'>Portfolio Management System</div>
            <h1>Monarch Transaction Report Generator</h1>
            <p>Upload your Monarch transaction export to parse buy/sell records,
               match analyst tags, and generate portfolio reports with live market prices.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown(
            """
            <div class='sidebar-brand'>
                <span class='brand-icon'>📊</span>
                <h3>Monarch PMS</h3>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.header("Upload & Download")
        uploaded_file = st.file_uploader(
            "Upload input CSV file",
            type=["csv"],
            help="Upload the raw Monarch transactions export file."
        )
        st.markdown("#### Transaction tagging source")
        st.caption("Tagging data will be loaded from Supabase using credentials in the .env file.")
        fetch_live_prices = st.checkbox(
            "Fetch live Yahoo prices",
            value=True,
            help="Turn this off to generate the reports without waiting for live market prices."
        )
        refresh_live_prices = st.button(
            "Refresh / Update prices",
            disabled=not fetch_live_prices,
            help="Clear cached prices and fetch the latest Yahoo prices again."
        )
        st.markdown(
            "---\n"
            "### How it works\n"
            "1. Upload the raw transaction CSV.\n"
            "2. Transaction tags are loaded from Supabase.\n"
            "3. The parser extracts BUY/SELL rows and matches tags by date, ISIN, and transaction.\n"
            "4. The portfolio report can use live Yahoo prices when enabled.\n"
            "5. Download CSV or Excel outputs."
        )

    if uploaded_file is None:
        st.markdown(
            """
            <div class='section-card'>
                <div class='section-header'><span class='sh-icon'>👋</span> Get started</div>
                <p style='color:#475569; margin:0 0 0.5rem;'>
                    Upload a Monarch transaction CSV from the sidebar to begin processing.
                </p>
                <div class='welcome-grid'>
                    <div class='welcome-card'>
                        <div class='wc-icon'>📁</div>
                        <h4>Upload CSV</h4>
                        <p>Drop your raw Monarch export file in the sidebar uploader.</p>
                    </div>
                    <div class='welcome-card'>
                        <div class='wc-icon'>🏷️</div>
                        <h4>Auto Tagging</h4>
                        <p>Transaction tags are matched automatically from Supabase.</p>
                    </div>
                    <div class='welcome-card'>
                        <div class='wc-icon'>📈</div>
                        <h4>Live Prices</h4>
                        <p>Portfolio values update with real-time Yahoo Finance prices.</p>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div class='app-footer'>Monarch PMS · Transaction Report Generator</div>",
            unsafe_allow_html=True,
        )
        return

    # Load tagging data from Supabase (credentials from .env)
    def read_env_file(path: str = ".env") -> dict:
        env = {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('\"').strip("\'")
                    env[key] = val
        except FileNotFoundError:
            return {}
        return env

    def fetch_tagging_from_supabase(supabase_url: str, supabase_key: str, table_name: str) -> pd.DataFrame:
        if not supabase_url or not supabase_key or not table_name:
            raise ValueError("Supabase URL, KEY or TABLE_NAME missing in .env")

        base = supabase_url.rstrip("/")
        # REST endpoint for Supabase
        table_quoted = urllib.parse.quote(table_name, safe="")
        url = f"{base}/rest/v1/{table_quoted}?select=*"
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data)
        # Normalize column names (strip whitespace)
        df.columns = [str(c).strip() for c in df.columns]
        return df

    env = read_env_file(os.path.join(os.getcwd(), ".env"))
    supabase_url = env.get("SUPABASE_URL")
    supabase_key = env.get("SUPABASE_KEY")
    table_name = env.get("TABLE_NAME_2")

    try:
        raw = pd.read_csv(
            uploaded_file,
            header=None,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8"
        )
    except Exception as exc:
        st.error(f"Unable to read the uploaded CSV file: {exc}")
        return

    try:
        tagging_raw = fetch_tagging_from_supabase(supabase_url, supabase_key, table_name)
        if tagging_raw.empty:
            st.error("Tagging table returned no rows from Supabase.")
            return
        tagging_raw = tagging_raw.astype(str).fillna("")
        tagging_raw.columns = tagging_raw.columns.astype(str).str.strip()
    except Exception as exc:
        st.error(f"Unable to load transaction tagging data from Supabase: {exc}")
        return

    result_df, skipped_df = parse_monarch_transactions(raw)

    if result_df.empty:
        st.warning("No valid transaction records were found in the uploaded file.")
        if not skipped_df.empty:
            st.markdown("### Skipped rows")
            st.dataframe(skipped_df)
        return

    try:
        result_df = add_transaction_tagging(result_df, tagging_raw)
    except ValueError as exc:
        st.error(str(exc))
        return

    # If some transactions remain untagged, ask the user to provide tags and persist them to Supabase
    def parse_date_to_iso(date_str: str) -> str:
        if not isinstance(date_str, str) or not date_str.strip():
            return ""
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).date().isoformat()
            except Exception:
                pass
        # fallback to pandas
        try:
            dt = pd.to_datetime(date_str, dayfirst=True, errors="coerce")
            if pd.isna(dt):
                return ""
            return dt.date().isoformat()
        except Exception:
            return ""

    def insert_tagging_to_supabase(
        supabase_url: str,
        supabase_key: str,
        table_name: str,
        isin: str,
        date_iso: str,
        transaction: str,
        security: str,
        client_ucc: str,
        quantity: int,
        tagging: str,
    ) -> None:
        if not supabase_url or not supabase_key or not table_name:
            raise ValueError("Supabase credentials/table missing")
        base = supabase_url.rstrip("/")
        table_quoted = urllib.parse.quote(table_name, safe="")
        url = f"{base}/rest/v1/{table_quoted}"
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        payload = {
            "ISIN": isin,
            "Date": date_iso,
            "Transaction": transaction,
            "Security": security,
            "Client UCC": client_ucc,
            "Quantity": int(quantity),
            "Transaction Tagging": tagging,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()

    def build_pending_tagging_rows(result_df: pd.DataFrame, tagging_raw: pd.DataFrame) -> pd.DataFrame:
        mismatch_df = compute_transaction_quantity_mismatch(result_df, tagging_raw)
        mismatch_keys = set(
            tuple(x)
            for x in mismatch_df[["Tran Date", "ISIN", "Transaction Description"]].values.tolist()
        )

        pending = result_df.copy()
        pending["Tran Date"] = pending["Tran Date"].astype(str).str.strip()
        pending["ISIN"] = pending["ISIN"].astype(str).str.strip().str.upper()
        pending["Transaction Description"] = pending["Transaction Description"].astype(str).str.strip().str.upper()
        pending["Quantity"] = pending["Quantity"].astype(str).str.strip()
        pending["Client UCC"] = pending["UCC"].astype(str).str.strip().str.upper()

        pending["Pending Tag"] = pending["Transaction Tagging"].astype(str).str.strip() == ""
        pending["Group Mismatch"] = pending.apply(
            lambda row: (row["Tran Date"], row["ISIN"], row["Transaction Description"]) in mismatch_keys,
            axis=1,
        )

        return pending[pending["Pending Tag"] | pending["Group Mismatch"]].copy()

    missing_df = build_pending_tagging_rows(result_df, tagging_raw)
    tags_saved = st.session_state.get("tags_saved", False)

    if not missing_df.empty and not tags_saved:
            st.markdown(
                """
                <div class='tagging-banner'>
                    <h3>⚠️ Missing or mismatched transaction tagging</h3>
                    <p>Some rows need analyst tags before the report can be generated.
                       Enter tags below and save them to the database.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.info(
                "Either some rows are untagged, or the client-based quantities for a date/stock/transaction do not tally with Supabase data. "
                "Enter tags for each pending row below and save them to the tagging table."
            )

            mismatch_summary = compute_transaction_quantity_mismatch(result_df, tagging_raw)
            if not mismatch_summary.empty:
                st.warning("Quantity mismatch detected for the following date/stock/transaction groups:")
                st.dataframe(mismatch_summary)

            missing_unique = missing_df.drop_duplicates(
                subset=["Tran Date", "ISIN", "Transaction Description", "Client UCC", "Quantity"]
            )

            grouping_columns = ["Tran Date", "ISIN", "Transaction Description"]
            grouped_missing_rows = []
            for group_idx, (group_key, group_df) in enumerate(
                missing_unique.groupby(grouping_columns, sort=False)
            ):
                group_rows = group_df.reset_index(drop=True)
                grouped_missing_rows.append(
                    {
                        "group_idx": group_idx,
                        "tran_date": group_key[0],
                        "isin": group_key[1],
                        "transaction_desc": group_key[2],
                        "security": group_rows["Security"].iloc[0] if not group_rows["Security"].empty else "",
                        "rows": group_rows.to_dict("records"),
                    }
                )

            form_group_choices = []
            row_selections = []

            for group in grouped_missing_rows:
                st.markdown(
                    f"#### {group['isin']} — {group['tran_date']} — {group['transaction_desc']}"
                )
                st.write(f"**Security:** {group['security']}")

                split_choice = st.radio(
                    "Stock tagging mode",
                    options=["Split", "Don't Split"],
                    index=1,
                    key=f"group_mode_{group['group_idx']}",
                )

                if split_choice == "Don't Split":
                    tag_choice = st.selectbox(
                        "Assign analyst for this stock",
                        options=["Select"] + sorted(VALID_TRANSACTION_TAGS),
                        index=0,
                        key=f"group_tag_{group['group_idx']}",
                        label_visibility="collapsed",
                    )
                    form_group_choices.append(
                        {
                            "group": group,
                            "mode": split_choice,
                            "tag": tag_choice,
                        }
                    )
                    st.markdown("**All clients and quantities for this stock will be tagged with the selected analyst.**")
                    continue

                header_cols = st.columns([2, 2, 2, 2, 2, 2])
                header_cols[0].markdown("**ISIN**")
                header_cols[1].markdown("**Date**")
                header_cols[2].markdown("**Security**")
                header_cols[3].markdown("**Client UCC**")
                header_cols[4].markdown("**Quantity**")
                header_cols[5].markdown("**Tag / Split**")

                for row_idx, row in enumerate(group["rows"]):
                    cols = st.columns([2, 2, 2, 2, 2, 2], vertical_alignment="center")
                    cols[0].write(row.get("ISIN", ""))
                    cols[1].write(row.get("Tran Date", ""))
                    cols[2].write(row.get("Security", ""))
                    cols[3].write(row.get("Client UCC", ""))
                    cols[4].write(row.get("Quantity", ""))

                    split_client = cols[5].checkbox(
                        "Split this client",
                        key=f"split_client_{group['group_idx']}_{row_idx}",
                        help="Split this client's transaction quantity across multiple analysts.",
                    )

                    if split_client:
                        nested_rows = []
                        split_count = st.number_input(
                            "Number of analyst allocations",
                            min_value=2,
                            max_value=5,
                            value=2,
                            step=1,
                            key=f"split_count_{group['group_idx']}_{row_idx}",
                            label_visibility="collapsed",
                        )
                        total_quantity = int(abs(parse_amount_series(pd.Series([row.get("Quantity", "")])).iloc[0]))
                        st.markdown(f"*Split total quantity: **{total_quantity}**. Allocated quantities must sum to this amount.*")

                        for split_idx in range(int(split_count)):
                            nested_cols = st.columns([2, 2, 2, 2, 2, 2], vertical_alignment="center")
                            nested_cols[0].write("")
                            nested_cols[1].write("")
                            nested_cols[2].write("")
                            nested_cols[3].write(row.get("Client UCC", ""))
                            nested_qty = nested_cols[4].number_input(
                                "Qty",
                                min_value=0,
                                value=0,
                                step=1,
                                key=f"split_qty_{group['group_idx']}_{row_idx}_{split_idx}",
                                label_visibility="collapsed",
                            )
                            nested_tag = nested_cols[5].selectbox(
                                "Analyst tag",
                                options=["Select"] + sorted(VALID_TRANSACTION_TAGS),
                                index=0,
                                key=f"split_tag_{group['group_idx']}_{row_idx}_{split_idx}",
                                label_visibility="collapsed",
                            )
                            nested_rows.append(
                                {
                                    "quantity": nested_qty,
                                    "tag": nested_tag,
                                }
                            )

                        allocated_sum = sum(int(alloc["quantity"]) for alloc in nested_rows)
                        if allocated_sum != total_quantity:
                            cols[5].warning(
                                f"Split quantities must sum to {total_quantity}. Current allocation: {allocated_sum}."
                            )

                        row_selections.append(
                            {
                                "group": group,
                                "isin": row.get("ISIN", ""),
                                "tran_date": row.get("Tran Date", ""),
                                "security": row.get("Security", ""),
                                "client_ucc": row.get("Client UCC", ""),
                                "quantity": row.get("Quantity", ""),
                                "transaction_desc": row.get("Transaction Description", ""),
                                "tag": None,
                                "split_client": True,
                                "split_allocations": nested_rows,
                            }
                        )
                    else:
                        sel = cols[5].selectbox(
                            f"Tag for {row.get('Client UCC', '')}",
                            options=["Select"] + sorted(VALID_TRANSACTION_TAGS),
                            index=0,
                            key=f"tag_select_{group['group_idx']}_{row_idx}",
                            label_visibility="visible",
                        )
                        row_selections.append(
                            {
                                "group": group,
                                "isin": row.get("ISIN", ""),
                                "tran_date": row.get("Tran Date", ""),
                                "security": row.get("Security", ""),
                                "client_ucc": row.get("Client UCC", ""),
                                "quantity": row.get("Quantity", ""),
                                "transaction_desc": row.get("Transaction Description", ""),
                                "tag": sel,
                                "split_client": False,
                                "split_allocations": [],
                            }
                        )
                form_group_choices.append(
                    {
                        "group": group,
                        "mode": split_choice,
                        "tag": None,
                    }
                )

            submit = st.button("Save tags to Database")

            if submit:
                any_failed = False

                for group_choice in form_group_choices:
                    if group_choice["mode"] == "Don't Split":
                        sel = group_choice["tag"]
                        if sel == "Select" or sel == "":
                            any_failed = True
                            group = group_choice["group"]
                            st.error(
                                f"Please select a valid analyst tag for {group['isin']} {group['tran_date']} {group['transaction_desc']}."
                            )
                            continue

                        for row in group_choice["group"]["rows"]:
                            isin = row.get("ISIN", "")
                            tran_date_str = row.get("Tran Date", "")
                            security = row.get("Security", "")
                            client_ucc = row.get("Client UCC", "")
                            quantity_str = row.get("Quantity", "")
                            transaction_desc = row.get("Transaction Description", "")

                            date_iso = parse_date_to_iso(tran_date_str)
                            try:
                                quantity_value = int(parse_amount_series(pd.Series([quantity_str])).iloc[0])
                            except Exception:
                                quantity_value = 0

                            try:
                                insert_tagging_to_supabase(
                                    supabase_url,
                                    supabase_key,
                                    table_name,
                                    isin,
                                    date_iso,
                                    transaction_desc,
                                    security,
                                    client_ucc,
                                    quantity_value,
                                    sel,
                                )
                                mask = (
                                    result_df["ISIN"].astype(str).str.strip().str.upper() == str(isin).strip().upper()
                                ) & (
                                    result_df["Tran Date"].astype(str).str.strip() == str(tran_date_str).strip()
                                ) & (
                                    result_df["Transaction Description"].astype(str).str.strip().str.upper() == str(transaction_desc).strip().upper()
                                ) & (
                                    result_df["UCC"].astype(str).str.strip().str.upper() == str(client_ucc).strip().upper()
                                ) & (
                                    parse_amount_series(result_df["Quantity"]).abs() == abs(quantity_value)
                                )
                                result_df.loc[mask, "Transaction Tagging"] = sel
                            except Exception as exc:
                                any_failed = True
                                st.error(
                                    f"Failed to save tag for {isin} {tran_date_str} {transaction_desc} (Client: {client_ucc}, Quantity: {quantity_str}): {exc}"
                                )

                for row_selection in row_selections:
                    if row_selection["split_client"]:
                        total_quantity = int(abs(parse_amount_series(pd.Series([row_selection["quantity"]])).iloc[0]))
                        allocated_sum = sum(int(alloc["quantity"]) for alloc in row_selection["split_allocations"])

                        if allocated_sum != total_quantity:
                            any_failed = True
                            st.error(
                                f"Split quantities for {row_selection['isin']} {row_selection['tran_date']} {row_selection['transaction_desc']} (Client: {row_selection['client_ucc']}) must sum to {total_quantity}. Currently {allocated_sum}."
                            )
                            continue

                        for alloc in row_selection["split_allocations"]:
                            tag = alloc["tag"]
                            if tag == "Select" or tag == "":
                                any_failed = True
                                st.error(
                                    f"Please select a valid analyst tag for split allocation of {row_selection['isin']} {row_selection['tran_date']} {row_selection['transaction_desc']} (Client: {row_selection['client_ucc']})."
                                )
                                continue

                            try:
                                base_qty = int(parse_amount_series(pd.Series([row_selection["quantity"]])).iloc[0])
                                signed_qty = int(alloc["quantity"]) if base_qty >= 0 else -int(alloc["quantity"])
                            except Exception:
                                signed_qty = 0

                            date_iso = parse_date_to_iso(row_selection["tran_date"])
                            try:
                                insert_tagging_to_supabase(
                                    supabase_url,
                                    supabase_key,
                                    table_name,
                                    row_selection["isin"],
                                    date_iso,
                                    row_selection["transaction_desc"],
                                    row_selection["security"],
                                    row_selection["client_ucc"],
                                    signed_qty,
                                    tag,
                                )
                            except Exception as exc:
                                any_failed = True
                                st.error(
                                    f"Failed to save split tag for {row_selection['isin']} {row_selection['tran_date']} {row_selection['transaction_desc']} (Client: {row_selection['client_ucc']}, Qty: {alloc['quantity']}): {exc}"
                                )
                    else:
                        sel = row_selection["tag"]
                        if sel == "Select" or sel == "":
                            any_failed = True
                            st.error(
                                f"Please select a valid analyst tag for {row_selection['isin']} {row_selection['tran_date']} {row_selection['transaction_desc']} (Client: {row_selection['client_ucc']}, Quantity: {row_selection['quantity']})."
                            )
                            continue

                        date_iso = parse_date_to_iso(row_selection["tran_date"])
                        try:
                            quantity_value = int(parse_amount_series(pd.Series([row_selection["quantity"]])).iloc[0])
                        except Exception:
                            quantity_value = 0

                        try:
                            insert_tagging_to_supabase(
                                supabase_url,
                                supabase_key,
                                table_name,
                                row_selection["isin"],
                                date_iso,
                                row_selection["transaction_desc"],
                                row_selection["security"],
                                row_selection["client_ucc"],
                                quantity_value,
                                sel,
                            )
                            mask = (
                                result_df["ISIN"].astype(str).str.strip().str.upper() == str(row_selection["isin"]).strip().upper()
                            ) & (
                                result_df["Tran Date"].astype(str).str.strip() == str(row_selection["tran_date"]).strip()
                            ) & (
                                result_df["Transaction Description"].astype(str).str.strip().str.upper() == str(row_selection["transaction_desc"]).strip().upper()
                            ) & (
                                result_df["UCC"].astype(str).str.strip().str.upper() == str(row_selection["client_ucc"]).strip().upper()
                            ) & (
                                parse_amount_series(result_df["Quantity"]).abs() == abs(quantity_value)
                            )
                            result_df.loc[mask, "Transaction Tagging"] = sel
                        except Exception as exc:
                            any_failed = True
                            st.error(
                                f"Failed to save tag for {row_selection['isin']} {row_selection['tran_date']} {row_selection['transaction_desc']} (Client: {row_selection['client_ucc']}, Quantity: {row_selection['quantity']}): {exc}"
                            )

                if not any_failed:
                    st.session_state["tags_saved"] = True
                    st.success("All tags saved to Supabase and report updated. Processing will continue now.")
                    try:
                        tagging_raw = fetch_tagging_from_supabase(supabase_url, supabase_key, table_name)
                        tagging_raw = tagging_raw.astype(str).fillna("")
                        tagging_raw.columns = tagging_raw.columns.astype(str).str.strip()
                    except Exception:
                        pass
                    st.rerun()

                # If tags haven't been saved yet, stop further processing until user saves them
                if not st.session_state.get("tags_saved", False):
                    st.info("Please save tags to Database to continue processing.")
                    st.stop()


    # Prevent downstream processing if there are pending tags that haven't been saved
    if 'missing_df' in locals() and (not missing_df.empty) and (not st.session_state.get("tags_saved", False)):
        st.info("Pending tags detected. Please save tags to Database to continue processing.")
        st.stop()

    try:
        isin_symbol_map = load_isin_symbol_map()
    except Exception as exc:
        st.error(f"Unable to read {ISIN_TICKER_MAPPING_FILE}: {exc}")
        return

    if fetch_live_prices and refresh_live_prices:
        get_current_prices.clear()
        get_current_and_previous_prices.clear()
        st.info("Refreshing Yahoo prices and recalculating reports.")

    if fetch_live_prices:
        with st.spinner("Fetching live Yahoo prices..."):
            portfolio_df, price_warnings_df, price_fetch_timestamp = build_portfolio_summary(
                result_df,
                isin_symbol_map,
                fetch_live_prices=True,
            )
            consolidated_sheets = build_consolidated_summaries(
                result_df,
                isin_symbol_map,
                fetch_live_prices=True,
            )
    else:
        portfolio_df, price_warnings_df, price_fetch_timestamp = build_portfolio_summary(
            result_df,
            isin_symbol_map,
            fetch_live_prices=False,
        )
        consolidated_sheets = build_consolidated_summaries(
            result_df,
            isin_symbol_map,
            fetch_live_prices=False,
        )

    total_rows = len(raw)
    valid_rows = len(result_df)
    skipped_rows = len(skipped_df)
    tagged_rows = result_df["Transaction Tagging"].str.strip().ne("").sum()

    st.success("Parsed transaction report successfully.")
    st.write(
        "Below is a summary of the parsed report. Use the download buttons in the output section to save your results."
    )

    with st.container():
        st.markdown(
            f"""
            <div class='section-card'>
                <div class='section-header'><span class='sh-icon'>📋</span> Report summary</div>
                <div class='metrics-row'>
                    <div class='metric-card mc-blue'>
                        <div class='mc-label'>Raw rows</div>
                        <div class='mc-value'>{total_rows:,}</div>
                    </div>
                    <div class='metric-card mc-teal'>
                        <div class='mc-label'>Parsed records</div>
                        <div class='mc-value'>{valid_rows:,}</div>
                    </div>
                    <div class='metric-card mc-violet'>
                        <div class='mc-label'>Tagged records</div>
                        <div class='mc-value'>{tagged_rows:,}</div>
                    </div>
                    <div class='metric-card mc-rose'>
                        <div class='mc-label'>Skipped rows</div>
                        <div class='mc-value'>{skipped_rows:,}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    with st.container():
        st.markdown("<div class='section-card'><div class='section-header'><span class='sh-icon'>📄</span> Parsed report preview</div>", unsafe_allow_html=True)
        st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
        st.dataframe(result_df)
        st.markdown("</div></div>", unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='section-card'><div class='section-header'><span class='sh-icon'>💼</span> Portfolio derived calculations</div>", unsafe_allow_html=True)
        if fetch_live_prices:
            st.caption(f"Last price fetched at: {price_fetch_timestamp}")
        else:
            st.info("Live price fetching is off. Current Price, Market Value, and Unrealised P&L will remain blank.")
        st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
        st.dataframe(portfolio_df)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='section-card'><div class='section-header'><span class='sh-icon'>📊</span> Consolidated PMS views</div>", unsafe_allow_html=True)
        for sheet_name, sheet_df in consolidated_sheets.items():
            with st.expander(sheet_name, expanded=False):
                st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
                st.dataframe(sheet_df)
                st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='section-card'><div class='section-header'><span class='sh-icon'>⚡</span> Price warnings</div>", unsafe_allow_html=True)
        if price_warnings_df.empty:
            st.info("No unmapped ISINs or missing Yahoo prices found.")
        else:
            st.warning("Some securities need attention before live-price based values are complete.")
            st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
            st.dataframe(price_warnings_df)
            st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='section-card'><div class='section-header'><span class='sh-icon'>🚫</span> Skipped rows</div>", unsafe_allow_html=True)
        if skipped_df.empty:
            st.info("No skipped rows.")
        else:
            st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
            st.dataframe(skipped_df)
            st.markdown("</div>", unsafe_allow_html=True)

    output_csv = dataframe_to_csv_bytes(result_df)
    portfolio_csv = dataframe_to_csv_bytes(portfolio_df)
    skipped_csv = dataframe_to_csv_bytes(skipped_df)
    consolidated_excel = dataframes_to_excel_bytes(consolidated_sheets)
    all_results_excel = dataframes_to_excel_bytes({
        "Parsed Report": result_df,
        "Portfolio Calculations": portfolio_df,
        **consolidated_sheets,
        "Price Warnings": price_warnings_df,
        "Skipped Rows": skipped_df,
    })

    st.markdown("---")
    st.markdown(
        "<div class='section-card download-section'><div class='section-header'><span class='sh-icon'>⬇️</span> Download results</div>",
        unsafe_allow_html=True,
    )
    download_col1, download_col2, download_col3, download_col4, download_col5 = st.columns(5)
    with download_col1:
        st.download_button(
            "Download parsed report",
            data=output_csv,
            file_name="Monarch_Transaction_Report.csv",
            mime="text/csv"
        )
    with download_col2:
        st.download_button(
            "Download portfolio calculations",
            data=portfolio_csv,
            file_name="Portfolio_Derived_Calculations.csv",
            mime="text/csv"
        )
    with download_col3:
        st.download_button(
            "Download skipped rows",
            data=skipped_csv,
            file_name="Skipped_Rows.csv",
            mime="text/csv"
        )
    with download_col4:
        st.download_button(
            "Download consolidated sheets",
            data=consolidated_excel,
            file_name="PMS_Consolidated_Sheets.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with download_col5:
        st.download_button(
            "Download Excel workbook",
            data=all_results_excel,
            file_name="Monarch_Reports.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    st.markdown(
        "<div class='app-footer'>Monarch PMS · Transaction Report Generator</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
