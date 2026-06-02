import io
import re
from typing import Tuple

import pandas as pd
import streamlit as st


VALID_TRANSACTION_TYPES = {"BUY", "SELL"}

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
    "Orignal Pur Date"
]


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
                if value == "Shares - Listed":
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

                records.append({
                    "Acc number": acc_number,
                    "UCC": ucc,
                    "Transaction Description": str(row[0]).strip(),
                    "Tran Date": str(row[1]).strip(),
                    "Settlement Date": str(row[2]).strip(),
                    "Security": str(row[3]).strip(),
                    "ISIN": str(row[4]).strip(),
                    "Quantity": str(row[5]).strip(),
                    "Rate": str(row[6]).strip(),
                    "Brokerage": str(row[7]).strip(),
                    "STT": str(row[8]).strip(),
                    "Tran Amount": str(row[9]).strip(),
                    "Transaction Rate": str(row[10]).strip(),
                    "Orignal Pur Date": str(row[11]).strip()
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


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


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
        page_icon="💼",
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
        st.markdown(
            "---\n"
            "### How it works\n"
            "1. Upload the raw transaction CSV.\n"
            "2. The parser extracts BUY/SELL rows.\n"
            "3. Download the cleaned report and skipped rows."
        )

    if uploaded_file is None:
        st.info("Please upload a CSV file from the sidebar to generate the report.")
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

    result_df, skipped_df = parse_monarch_transactions(raw)

    if result_df.empty:
        st.warning("No valid transaction records were found in the uploaded file.")
        if not skipped_df.empty:
            st.markdown("### Skipped rows")
            st.dataframe(skipped_df)
        return

    total_rows = len(raw)
    valid_rows = len(result_df)
    skipped_rows = len(skipped_df)

    st.success("Parsed transaction report successfully.")
    st.write(
        "Below is a summary of the parsed report. Use the download buttons in the output section to save your results."
    )

    with st.container():
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric("Raw rows", total_rows)
        metric_col2.metric("Parsed records", valid_rows)
        metric_col3.metric("Skipped rows", skipped_rows)

    st.markdown("---")

    with st.container():
        st.subheader("Parsed report preview")
        st.markdown("<div class='dataframe-container'>", unsafe_allow_html=True)
        st.dataframe(result_df)
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
    skipped_csv = dataframe_to_csv_bytes(skipped_df)

    st.markdown("---")
    st.subheader("Download results")
    download_col1, download_col2 = st.columns(2)
    with download_col1:
        st.download_button(
            "Download parsed report",
            data=output_csv,
            file_name="Monarch_Transaction_Report.csv",
            mime="text/csv"
        )
    with download_col2:
        st.download_button(
            "Download skipped rows",
            data=skipped_csv,
            file_name="Skipped_Rows.csv",
            mime="text/csv"
        )


if __name__ == "__main__":
    main()
