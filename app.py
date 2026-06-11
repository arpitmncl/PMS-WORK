#### Changes from app3.py : Change Realized P&L logic to direct take from Transaction Amount column
####    Add ISIN column in Final Output File
####    Making 'Shares - Listed' row dynamic so that other names like 'Shares - Equity ETF' can also be accomodated

import io
import re
from datetime import datetime
from typing import Dict, Tuple

import pandas as pd
import streamlit as st
import yfinance as yf


VALID_TRANSACTION_TYPES = {"BUY", "SELL"}
VALID_TRANSACTION_TAGS = {"MOMENTUM", "DHRUV", "SHAUKAT", "GAURAV"}

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

                if len(row) < 12:
                    skipped_rows.append({"Row": j, "Reason": "Less than 12 columns"})
                    j += 1
                    continue

                transaction_desc = str(row[0]).strip().upper()
                if transaction_desc not in VALID_TRANSACTION_TYPES:
                    j += 1
                    continue

                quantity = str(row[5]).strip()
                if transaction_desc == "SELL" and quantity:
                    quantity = f"-{quantity.lstrip('-')}"

                records.append({
                    "Acc number": acc_number,
                    "UCC": ucc,
                    "Transaction Description": str(row[0]).strip(),
                    "Tran Date": str(row[1]).strip(),
                    "Settlement Date": str(row[2]).strip(),
                    "Security": str(row[3]).strip(),
                    "ISIN": str(row[4]).strip(),
                    "Quantity": quantity,
                    "Rate": str(row[6]).strip(),
                    "Brokerage": str(row[7]).strip(),
                    "STT": str(row[8]).strip(),
                    "Tran Amount": str(row[9]).strip(),
                    "Transaction Rate": str(row[10]).strip(),
                    "Orignal Pur Date": str(row[11]).strip(),
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

    df["Tran Date"] = pd.to_datetime(df["Tran Date"], format="%d-%m-%Y", errors="coerce")

    required_columns = ["Tran Date", "UCC", "Security", "Quantity"]
    df = df.dropna(subset=required_columns)
    df = df[df["Security"].str.strip() != ""]
    df = df[df["Quantity"].str.strip() != ""]
    df = df[df["UCC"].str.strip() != ""]

    df["Tran Date"] = df["Tran Date"].dt.strftime("%d-%m-%Y")
    df = df[OUTPUT_COLUMNS]

    return df, pd.DataFrame(skipped_rows)


def add_transaction_tagging(result_df: pd.DataFrame, tagging_raw: pd.DataFrame) -> pd.DataFrame:
    required_columns = ["ISIN", "Transaction", "Date", "Transaction Tagging"]
    missing_columns = [col for col in required_columns if col not in tagging_raw.columns]
    if missing_columns:
        raise ValueError(f"Tagging file is missing columns: {', '.join(missing_columns)}")

    tagging_df = tagging_raw[required_columns].copy()
    original_dates = tagging_df["Date"].copy()
    for col in ["ISIN", "Transaction", "Transaction Tagging"]:
        tagging_df[col] = tagging_df[col].astype(str).str.strip()

    parsed_dates = pd.to_datetime(original_dates, errors="coerce")
    missing_dates = parsed_dates.isna()
    if missing_dates.any():
        parsed_dates.loc[missing_dates] = pd.to_datetime(
            original_dates.loc[missing_dates].astype(str).str.strip(),
            dayfirst=True,
            errors="coerce"
        )

    tagging_df["Tran Date"] = parsed_dates.dt.strftime("%d-%m-%Y")
    tagging_df["ISIN"] = tagging_df["ISIN"].str.upper()
    tagging_df["Transaction Description"] = tagging_df["Transaction"].str.upper()
    tagging_df["Tag Key"] = tagging_df["Transaction Tagging"].str.upper()

    tagging_df = tagging_df[
        tagging_df["Tran Date"].notna()
        & tagging_df["ISIN"].ne("")
        & tagging_df["Transaction Description"].isin(VALID_TRANSACTION_TYPES)
        & tagging_df["Tag Key"].isin(VALID_TRANSACTION_TAGS)
    ]

    tagging_lookup = tagging_df.drop_duplicates(
        subset=["Tran Date", "ISIN", "Transaction Description"],
        keep="last"
    )[["Tran Date", "ISIN", "Transaction Description", "Transaction Tagging"]].rename(
        columns={
            "ISIN": "Tag Match ISIN",
            "Transaction Description": "Tag Match Transaction Description",
        }
    )

    tagged_result = result_df.copy()
    tagged_result["Tag Match ISIN"] = tagged_result["ISIN"].astype(str).str.strip().str.upper()
    tagged_result["Tag Match Transaction Description"] = (
        tagged_result["Transaction Description"].astype(str).str.strip().str.upper()
    )

    tagged_result = tagged_result.drop(columns=["Transaction Tagging"], errors="ignore")
    tagged_result = tagged_result.merge(
        tagging_lookup,
        how="left",
        on=["Tran Date", "Tag Match ISIN", "Tag Match Transaction Description"]
    )
    tagged_result["Transaction Tagging"] = tagged_result["Transaction Tagging"].fillna("")
    tagged_result = tagged_result.drop(
        columns=["Tag Match ISIN", "Tag Match Transaction Description"]
    )

    return tagged_result[OUTPUT_COLUMNS]


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

    summary_rows = []
    group_columns = ["Client UCC", "Category", "Company", "ISIN Key"]
    for group_values, group_df in working_df.groupby(group_columns, dropna=False, sort=True):
        buy_df = group_df[group_df["Transaction Type"].eq("BUY") & group_df["Quantity Numeric"].gt(0)]
        sell_df = group_df[group_df["Transaction Type"].eq("SELL")]

        total_buy_quantity = buy_df["Quantity Numeric"].sum()
        wt_avg_cost = (
            (buy_df["Quantity Numeric"] * buy_df["Rate Numeric"]).sum() / total_buy_quantity
            if total_buy_quantity
            else 0
        )
        units = group_df["Quantity Numeric"].sum()

        group_symbols = group_df["Ticker Symbol"].dropna()
        current_price = float("nan")
        if not group_symbols.empty:
            current_price = price_by_symbol.get(group_symbols.iloc[-1], float("nan"))

        market_value = units * current_price if pd.notna(current_price) else float("nan")
        sell_prices = sell_df["Tran Amount Numeric"] / sell_df["Quantity Numeric"].abs().replace({0: pd.NA})
        realised_pnl = ((sell_prices.fillna(0) - wt_avg_cost) * sell_df["Quantity Numeric"].abs()).sum()
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


def set_page_style() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #eef4ff 0%, #fff7f2 45%, #ffffff 100%);
            color: #0f3a72;
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            background: rgba(255, 255, 255, 0.88);
            box-shadow: 0 24px 80px rgba(17, 85, 204, 0.08);
            border-radius: 24px;
        }

        .streamlit-expanderHeader {
            font-weight: 700;
        }

        .stDownloadButton>button, .stButton>button {
            border-radius: 14px;
            background-color: #1f77d0;
            color: white;
            border: none;
            padding: 0.9rem 1.4rem;
            box-shadow: 0 10px 25px rgba(31, 119, 208, 0.2);
        }

        .stDownloadButton>button:hover, .stButton>button:hover {
            background-color: #145b98;
        }

        .stMetric {
            border: 1px solid rgba(31, 119, 208, 0.16);
            border-radius: 20px;
            padding: 1rem;
            background: linear-gradient(135deg, rgba(31, 119, 208, 0.08), rgba(255, 255, 255, 0.8));
        }

        .dataframe-container {
            border-radius: 22px;
            padding: 1rem;
            background: #ffffff;
            box-shadow: 0 22px 45px rgba(31, 119, 208, 0.08);
        }

        .hero-banner {
            background: linear-gradient(90deg, #4d8bf5 0%, #89dff0 100%);
            border-radius: 24px;
            padding: 1.6rem 2rem;
            color: white;
            margin-bottom: 1.5rem;
            box-shadow: 0 24px 50px rgba(77, 139, 245, 0.24);
        }

        .hero-banner h1,
        .hero-banner h2,
        .hero-banner p {
            color: white;
        }

        .sidebar .stButton>button,
        .sidebar .stDownloadButton>button {
            width: 100%;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Monarch Transaction Parser",
        page_icon=":briefcase:",
        layout="wide",
    )

    set_page_style()

    st.markdown(
        "<div class='hero-banner'><h1>Monarch Transaction Report Generator</h1><p>Upload your monarch transaction export and download a clean report with parsed buy/sell records.</p></div>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Upload & Download")
        uploaded_file = st.file_uploader(
            "Upload input CSV file",
            type=["csv"],
            help="Upload the raw Monarch transactions export file."
        )
        tagging_file = st.file_uploader(
            "Upload transaction tagging Excel file",
            type=["xlsx", "xls"],
            help="Upload the file with ISIN, Transaction, Date, and Transaction Tagging."
        )
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
            "2. Upload the transaction tagging Excel file.\n"
            "3. The parser extracts BUY/SELL rows and matches tags by date, ISIN, and transaction.\n"
            "4. The portfolio report can use live Yahoo prices when enabled.\n"
            "5. Download CSV or Excel outputs."
        )

    if uploaded_file is None:
        st.info("Please upload a CSV file from the sidebar to generate the report.")
        return

    if tagging_file is None:
        st.info("Please upload the transaction tagging Excel file from the sidebar.")
        return

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
        tagging_raw = pd.read_excel(
            tagging_file,
            dtype=str,
            keep_default_na=False
        )
        tagging_raw.columns = tagging_raw.columns.astype(str).str.strip()
    except Exception as exc:
        st.error(f"Unable to read the uploaded transaction tagging Excel file: {exc}")
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

    try:
        isin_symbol_map = load_isin_symbol_map()
    except Exception as exc:
        st.error(f"Unable to read {ISIN_TICKER_MAPPING_FILE}: {exc}")
        return

    if fetch_live_prices and refresh_live_prices:
        get_current_prices.clear()
        st.info("Refreshing Yahoo prices and recalculating reports.")

    if fetch_live_prices:
        with st.spinner("Fetching live Yahoo prices..."):
            portfolio_df, price_warnings_df, price_fetch_timestamp = build_portfolio_summary(
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

    total_rows = len(raw)
    valid_rows = len(result_df)
    skipped_rows = len(skipped_df)
    tagged_rows = result_df["Transaction Tagging"].str.strip().ne("").sum()

    st.success("Parsed transaction report successfully.")
    st.write(
        "Below is a summary of the parsed report. Use the download buttons in the output section to save your results."
    )

    with st.container():
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        metric_col1.metric("Raw rows", total_rows)
        metric_col2.metric("Parsed records", valid_rows)
        metric_col3.metric("Tagged records", tagged_rows)
        metric_col4.metric("Skipped rows", skipped_rows)

    st.markdown("---")

    with st.container():
        st.subheader("Parsed report preview")
        st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
        st.dataframe(result_df)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.subheader("Portfolio derived calculations")
        if fetch_live_prices:
            st.caption(f"Last price fetched at: {price_fetch_timestamp}")
        else:
            st.info("Live price fetching is off. Current Price, Market Value, and Unrealised P&L will remain blank.")
        st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
        st.dataframe(portfolio_df)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.subheader("Price warnings")
        if price_warnings_df.empty:
            st.info("No unmapped ISINs or missing Yahoo prices found.")
        else:
            st.warning("Some securities need attention before live-price based values are complete.")
            st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
            st.dataframe(price_warnings_df)
            st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.subheader("Skipped rows")
        if skipped_df.empty:
            st.info("No skipped rows.")
        else:
            st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
            st.dataframe(skipped_df)
            st.markdown("</div>", unsafe_allow_html=True)

    output_csv = dataframe_to_csv_bytes(result_df)
    portfolio_csv = dataframe_to_csv_bytes(portfolio_df)
    skipped_csv = dataframe_to_csv_bytes(skipped_df)
    all_results_excel = dataframes_to_excel_bytes({
        "Parsed Report": result_df,
        "Portfolio Calculations": portfolio_df,
        "Price Warnings": price_warnings_df,
        "Skipped Rows": skipped_df,
    })

    st.markdown("---")
    st.subheader("Download results")
    download_col1, download_col2, download_col3, download_col4 = st.columns(4)
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
            "Download Excel workbook",
            data=all_results_excel,
            file_name="Monarch_Reports.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


if __name__ == "__main__":
    main()
