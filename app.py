import hashlib
import io
import time
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# --- Page Configuration ---
st.set_page_config(
    page_title="TNUWWB Smart Status & Tracking Portal",
    page_icon="📋",
    layout="wide",
)

TARGET_URL = "https://tnuwwb.tn.gov.in/applications/status"
DEFAULT_CAPTCHA = "Z5s23"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# --- Authentication Helper ---
def hash_password(password: str) -> str:
    """Returns SHA-256 hash of a password."""
    return hashlib.sha256(password.encode()).hexdigest()


def check_login():
    """Renders login form and verifies credentials against st.secrets."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
        st.session_state["username"] = None

    if st.session_state["authenticated"]:
        return True

    st.markdown("### 🔐 Client Portal Login")
    with st.form("login_form"):
        username = st.text_input("Username").strip()
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", type="primary")

        if submitted:
            # Load users from st.secrets
            users = st.secrets.get("users", {})

            if username in users:
                stored_hash = users[username]["password_hash"]
                if hash_password(password) == stored_hash:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            else:
                st.error("Invalid username or password.")

    return False


# Enforce authentication gate
if not check_login():
    st.stop()


# --- Logout Button in Sidebar ---
with st.sidebar:
    st.markdown(f"👤 Logged in as: **{st.session_state['username']}**")
    if st.button("Log out"):
        st.session_state["authenticated"] = False
        st.session_state["username"] = None
        st.rerun()
    st.markdown("---")


# --- Status Fetcher Function ---
def fetch_application_status(app_code: str, phone: str, captcha: str):
    """Sends POST request to TNUWWB portal and returns parsed status details."""
    app_code = str(app_code).strip()
    phone = str(phone).strip()

    if phone.endswith(".0"):
        phone = phone[:-2]
    if app_code.endswith(".0"):
        app_code = app_code[:-2]

    payload = {
        "applcode": app_code,
        "permanentmobile": phone,
        "catpcha": captcha.strip(),
    }

    try:
        response = requests.post(TARGET_URL, data=payload, headers=HEADERS, timeout=12)
        if response.status_code != 200:
            return {
                "success": False,
                "status": f"HTTP Error {response.status_code}",
                "remarks": "-",
                "date": "-",
            }

        soup = BeautifulSoup(response.text, "html.parser")
        status_header = soup.find(
            lambda tag: tag.name == "th" and "Application Status" in tag.text
        )

        if not status_header:
            return {
                "success": False,
                "status": "No Record / Invalid Captcha",
                "remarks": "Check application number, phone, or update captcha code.",
                "date": "-",
            }

        status_td = status_header.find_next("td")
        nested_table = status_td.find("table") if status_td else None

        if not nested_table:
            return {
                "success": False,
                "status": "No Status Table",
                "remarks": "Status structure not found.",
                "date": "-",
            }

        tbody = nested_table.find("tbody")
        rows = tbody.find_all("tr") if tbody else nested_table.find_all("tr")[1:]

        if not rows:
            return {
                "success": False,
                "status": "No Records",
                "remarks": "No status rows available.",
                "date": "-",
            }

        last_row = rows[-1]
        cols = [td.text.strip() for td in last_row.find_all("td")]

        if len(cols) >= 4:
            return {
                "success": True,
                "status": cols[3],
                "remarks": cols[2],
                "date": cols[1],
            }

        return {
            "success": False,
            "status": "Unknown Format",
            "remarks": "-",
            "date": "-",
        }

    except requests.exceptions.RequestException as req_err:
        return {
            "success": False,
            "status": "Network Error",
            "remarks": str(req_err),
            "date": "-",
        }
    except Exception as e:
        return {
            "success": False,
            "status": "Parsing Error",
            "remarks": str(e),
            "date": "-",
        }


def convert_gsheet_url_to_csv(url: str) -> str:
    """Converts a standard Google Sheets sharing URL to direct CSV export format."""
    if "/edit" in url:
        return url.split("/edit")[0] + "/export?format=csv"
    elif "/view" in url:
        return url.split("/view")[0] + "/export?format=csv"
    elif not url.endswith("/export?format=csv") and "docs.google.com/spreadsheets" in url:
        return url.rstrip("/") + "/export?format=csv"
    return url


# --- UI Sidebar ---
with st.sidebar:
    st.header("⚙️ Configuration")
    captcha_val = st.text_input("Cached Captcha Code", value=DEFAULT_CAPTCHA)
    request_delay = st.slider("Request Delay (seconds)", min_value=0.5, max_value=4.0, value=1.5, step=0.5)

    st.markdown("---")
    st.markdown("### 📊 Status Legend")
    st.write("🟢 **Approved** — Verification complete")
    st.write("🟡 **Pending / Under Process** — Requires follow-up")
    st.write("🔴 **Rejected / Error** — Needs correction")


# --- Main Dashboard ---
st.title("📋 TNUWWB Application Status Manager")
st.write("Automated status checking, review verification, and spreadsheet updating.")

tab_quick, tab_batch = st.tabs(["🔍 Instant Single Lookup", "📁 Batch Processor (Excel & Google Sheets)"])


# ==============================================================================
# TAB 1: INSTANT SINGLE LOOKUP
# ==============================================================================
with tab_quick:
    st.subheader("Instant Single Application Query")
    col1, col2 = st.columns(2)
    with col1:
        single_app = st.text_input("Application Number", placeholder="e.g. TNUWWB/12345678")
    with col2:
        single_phone = st.text_input("Registered Mobile Number", placeholder="e.g. 9876543210")

    if st.button("Check Single Status", type="primary"):
        if not single_app or not single_phone:
            st.warning("Please provide both Application Number and Mobile Number.")
        else:
            with st.spinner("Querying portal..."):
                res = fetch_application_status(single_app, single_phone, captcha_val)

            if res["success"]:
                st.success(f"**Current Status:** {res['status']}")
                c1, c2, c3 = st.columns(3)
                c1.metric("Status", res["status"])
                c2.metric("Date", res["date"])
                c3.metric("Remarks", res["remarks"])
            else:
                st.error(f"Status: {res['status']}")
                st.info(f"Details: {res['remarks']}")


# ==============================================================================
# TAB 2: BATCH PROCESSOR (EXCEL & GOOGLE SHEETS)
# ==============================================================================
with tab_batch:
    st.subheader("Source Selection")
    source_type = st.radio("Choose Data Source", ["Upload Local Excel File (.xlsx)", "Google Sheets Link (URL)"], horizontal=True)

    loaded_dfs = {}

    if source_type == "Upload Local Excel File (.xlsx)":
        uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])
        if uploaded_file:
            excel_obj = pd.ExcelFile(uploaded_file)
            selected_sheets = st.multiselect(
                "Select Sheet(s) to Scan",
                options=excel_obj.sheet_names,
                default=excel_obj.sheet_names[:min(5, len(excel_obj.sheet_names))]
            )
            for s in selected_sheets:
                loaded_dfs[s] = pd.read_excel(excel_obj, sheet_name=s, dtype=str)

    else:
        gsheet_url = st.text_input(
            "Paste Google Sheet URL",
            placeholder="https://docs.google.com/spreadsheets/d/your-sheet-id/edit#gid=0"
        )
        st.caption("Ensure sheet sharing is set to **'Anyone with the link can view'** (or edit).")
        if gsheet_url:
            try:
                csv_url = convert_gsheet_url_to_csv(gsheet_url)
                df_g = pd.read_csv(csv_url, dtype=str)
                loaded_dfs["Google_Sheet"] = df_g
                st.success(f"Successfully connected to Google Sheet ({len(df_g)} rows loaded).")
            except Exception as ex:
                st.error(f"Unable to read Google Sheet: {ex}. Ensure sharing permissions are active.")

    if loaded_dfs:
        st.markdown("---")
        st.subheader("Step 1: Intelligent Pre-check & Filter")

        processable_records = []

        for sheet_name, df in loaded_dfs.items():
            name_col = next((c for c in df.columns if c.strip().lower() in ["name", "customer name", "applicant name"]), None)
            phone_col = next((c for c in df.columns if c.strip().lower() in ["phone no", "mobile no", "phone", "mobile"]), None)
            app_col = next((c for c in df.columns if c.strip().lower() in ["application no", "appl code", "application number", "app no"]), None)
            status_col = next((c for c in df.columns if c.strip().lower() in ["status", "current status", "application status"]), None)

            if not phone_col or not app_col:
                st.warning(f"Sheet '{sheet_name}' is missing required 'Phone No' or 'Application No' column.")
                continue

            for idx, row in df.iterrows():
                app_no = str(row[app_col]).strip() if pd.notna(row[app_col]) else ""
                phone = str(row[phone_col]).strip() if pd.notna(row[phone_col]) else ""
                name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else "Unknown"
                prev_status = str(row[status_col]).strip() if status_col and pd.notna(row[status_col]) else "Not Checked"

                if not app_no or app_no == "nan" or not phone or phone == "nan":
                    continue

                is_already_approved = "approved" in prev_status.lower()

                processable_records.append({
                    "sheet_name": sheet_name,
                    "row_index": idx,
                    "Name": name,
                    "Application No": app_no,
                    "Phone No": phone,
                    "Previous Status": prev_status,
                    "Is Already Approved": is_already_approved,
                    "status_col_name": status_col,
                })

        if processable_records:
            df_preview = pd.DataFrame(processable_records)
            total_count = len(df_preview)
            already_approved_count = int(df_preview["Is Already Approved"].sum())
            to_check_count = total_count - already_approved_count

            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Total Valid Records", total_count)
            col_m2.metric("Already Approved (Skipped)", already_approved_count)
            col_m3.metric("Pending / Need Status Check", to_check_count)

            only_unapproved = st.checkbox("Check ONLY unapproved / pending records (Recommended)", value=True)

            if st.button("🚀 Start Status Verification", type="primary"):
                targets = [r for r in processable_records if not r["Is Already Approved"]] if only_unapproved else processable_records

                if not targets:
                    st.info("All records are already marked as Approved! No checks needed.")
                else:
                    progress_bar = st.progress(0.0)
                    status_banner = st.empty()
                    results = []

                    for i, item in enumerate(targets):
                        progress_bar.progress((i + 1) / len(targets))
                        status_banner.text(f"Checking ({i+1}/{len(targets)}): {item['Name']} ({item['Application No']})")

                        res = fetch_application_status(item["Application No"], item["Phone No"], captcha_val)

                        changed = (item["Previous Status"].lower() != res["status"].lower()) and res["success"]

                        results.append({
                            "Sheet": item["sheet_name"],
                            "Row Index": item["row_index"],
                            "Name": item["Name"],
                            "Application No": item["Application No"],
                            "Phone No": item["Phone No"],
                            "Previous Status": item["Previous Status"],
                            "New Live Status": res["status"],
                            "Remarks": res["remarks"],
                            "Status Date": res["date"],
                            "Status Changed": "YES" if changed else "NO",
                            "Is Approved": "approved" in res["status"].lower()
                        })

                        time.sleep(request_delay)

                    status_banner.text("Verification complete!")
                    progress_bar.progress(1.0)
                    st.session_state["comparison_results"] = pd.DataFrame(results)
                    st.session_state["source_dfs"] = loaded_dfs

    # --- Step 2: Before vs After Review & Confirmed Update ---
    if "comparison_results" in st.session_state:
        st.markdown("---")
        st.subheader("Step 2: Before vs. After Status Comparison")

        comp_df = st.session_state["comparison_results"]

        new_approved = int(comp_df["Is Approved"].sum())
        changed_count = int((comp_df["Status Changed"] == "YES").sum())

        r1, r2, r3 = st.columns(3)
        r1.metric("Records Checked", len(comp_df))
        r2.metric("Newly Approved Found", new_approved)
        r3.metric("Status Changes Detected", changed_count)

        st.dataframe(
            comp_df[["Sheet", "Name", "Application No", "Phone No", "Previous Status", "New Live Status", "Remarks", "Status Date", "Status Changed"]],
            use_container_width=True
        )

        st.markdown("---")
        st.subheader("Step 3: User Confirmation & Save")
        st.write("Review the changes above. Once confirmed, export the updated spreadsheet.")

        updated_dfs = {k: v.copy() for k, v in st.session_state["source_dfs"].items()}

        for _, row in comp_df.iterrows():
            s_name = row["Sheet"]
            r_idx = row["Row Index"]
            if s_name in updated_dfs:
                if "Status" not in updated_dfs[s_name].columns:
                    updated_dfs[s_name]["Status"] = ""
                if "Remarks" not in updated_dfs[s_name].columns:
                    updated_dfs[s_name]["Remarks"] = ""
                if "Last Checked Date" not in updated_dfs[s_name].columns:
                    updated_dfs[s_name]["Last Checked Date"] = ""

                updated_dfs[s_name].at[r_idx, "Status"] = row["New Live Status"]
                updated_dfs[s_name].at[r_idx, "Remarks"] = row["Remarks"]
                updated_dfs[s_name].at[r_idx, "Last Checked Date"] = row["Status Date"]

        excel_output = io.BytesIO()
        with pd.ExcelWriter(excel_output, engine="openpyxl") as writer:
            for s_name, df_out in updated_dfs.items():
                df_out.to_excel(writer, index=False, sheet_name=s_name[:31])

        st.download_button(
            label="✅ Confirm & Download Updated Excel File",
            data=excel_output.getvalue(),
            file_name="TNUWWB_Updated_Status.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
