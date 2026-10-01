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
    return hashlib.sha256(password.encode()).hexdigest()


def check_login():
    """Renders login form and verifies credentials against st.secrets."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None

    if st.session_state["authenticated"]:
        return True

    st.markdown("### 🔐 TNUWWB Portal Access")
    with st.form("login_form"):
        username = st.text_input("Username").strip()
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", type="primary")

        if submitted:
            users = st.secrets.get("users", {})
            if username in users:
                user_info = users[username]
                stored_hash = user_info.get("password_hash", "")
                if hash_password(password) == stored_hash:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    st.session_state["role"] = user_info.get("role", "customer")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            else:
                st.error("Invalid username or password.")

    return False


if not check_login():
    st.stop()


# --- Database Cloud Upsert Function ---
def sync_records_to_cloud(records: list, username: str) -> dict:
    """Sends records to the Google Sheet webhook for live upsert."""
    webhook_url = st.session_state.get(
        "custom_webhook_url", st.secrets.get("WEBHOOK_URL", "")
    )
    if not webhook_url:
        return {"success": False, "message": "No webhook URL configured."}

    payload = {
        "username": username,
        "records": records,
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=20)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# --- In-Memory Template Generator ---
@st.cache_data
def get_empty_template_excel() -> bytes:
    columns = [
        "Applicant Name",
        "Application No",
        "Phone No",
        "Status",
        "Remarks",
        "Last Checked Date",
    ]
    template_df = pd.DataFrame(columns=columns)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        template_df.to_excel(writer, index=False, sheet_name="Status_Tracker")
    return output.getvalue()


# --- Sidebar ---
with st.sidebar:
    st.markdown(f"👤 Logged in as: **{st.session_state['username']}**")
    st.caption(f"Role: {st.session_state.get('role', 'customer').capitalize()}")
    if st.button("Log out"):
        st.session_state["authenticated"] = False
        st.session_state["username"] = None
        st.rerun()

    st.markdown("---")
    st.header("⚙️ Configuration")
    captcha_val = st.text_input("Cached Captcha Code", value=DEFAULT_CAPTCHA)
    request_delay = st.slider("Request Delay (seconds)", min_value=0.5, max_value=4.0, value=1.5, step=0.5)

    # Admin configuration section
    if st.session_state.get("role") == "admin":
        st.markdown("---")
        st.markdown("### 🛠️ Admin Settings")
        default_wh = st.secrets.get("WEBHOOK_URL", "")
        admin_wh = st.text_input(
            "Cloud Sync Webhook URL",
            value=st.session_state.get("custom_webhook_url", default_wh),
            help="Google Apps Script web app endpoint for sheet upserts.",
        )
        if admin_wh:
            st.session_state["custom_webhook_url"] = admin_wh


# --- Status Fetcher Function ---
def fetch_application_status(app_code: str, phone: str, captcha: str):
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
            return {"success": False, "status": f"HTTP Error {response.status_code}", "remarks": "-", "date": "-"}

        soup = BeautifulSoup(response.text, "html.parser")
        status_header = soup.find(lambda tag: tag.name == "th" and "Application Status" in tag.text)

        if not status_header:
            return {"success": False, "status": "No Record / Invalid Captcha", "remarks": "Check application number or phone.", "date": "-"}

        status_td = status_header.find_next("td")
        nested_table = status_td.find("table") if status_td else None

        if not nested_table:
            return {"success": False, "status": "No Status Table", "remarks": "Status structure not found.", "date": "-"}

        tbody = nested_table.find("tbody")
        rows = tbody.find_all("tr") if tbody else nested_table.find_all("tr")[1:]

        if not rows:
            return {"success": False, "status": "No Records", "remarks": "No status rows available.", "date": "-"}

        cols = [td.text.strip() for td in rows[-1].find_all("td")]
        if len(cols) >= 4:
            return {"success": True, "status": cols[3], "remarks": cols[2], "date": cols[1]}

        return {"success": False, "status": "Unknown Format", "remarks": "-", "date": "-"}
    except requests.exceptions.RequestException as req_err:
        return {"success": False, "status": "Network Error", "remarks": str(req_err), "date": "-"}
    except Exception as e:
        return {"success": False, "status": "Parsing Error", "remarks": str(e), "date": "-"}


def convert_gsheet_url_to_csv(url: str) -> str:
    if "/edit" in url:
        return url.split("/edit")[0] + "/export?format=csv"
    elif "/view" in url:
        return url.split("/view")[0] + "/export?format=csv"
    return url


# --- Main Dashboard ---
st.title("📋 TNUWWB Application Status Manager")
tab_quick, tab_batch = st.tabs(["🔍 Instant Single Lookup", "📁 Batch Processor (Excel & Sheets)"])


# ==============================================================================
# TAB 1: INSTANT SINGLE LOOKUP
# ==============================================================================
with tab_quick:
    st.subheader("Instant Single Application Query")
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        single_name = st.text_input("Applicant Name (Optional)", placeholder="e.g. John Doe")
    with c2:
        single_app = st.text_input("Application Number", placeholder="e.g. TNUWWB/12345678")
    with c3:
        single_phone = st.text_input("Registered Mobile Number", placeholder="e.g. 9876543210")

    if st.button("Check Single Status", type="primary"):
        if not single_app or not single_phone:
            st.warning("Please provide both Application Number and Mobile Number.")
        else:
            with st.spinner("Querying portal..."):
                res = fetch_application_status(single_app, single_phone, captcha_val)

            if res["success"]:
                st.success(f"**Current Status:** {res['status']}")
                m1, m2, m3 = st.columns(3)
                m1.metric("Status", res["status"])
                m2.metric("Date", res["date"])
                m3.metric("Remarks", res["remarks"])

                # Upsert to Cloud Database
                record = [{
                    "app_no": single_app,
                    "name": single_name or "Single Query",
                    "phone": single_phone,
                    "status": res["status"],
                    "remarks": res["remarks"],
                    "date": res["date"]
                }]
                sync_res = sync_records_to_cloud(record, st.session_state["username"])
                if sync_res.get("success"):
                    st.info("☁️ Record updated in central database.")
            else:
                st.error(f"Status: {res['status']}")
                st.info(f"Details: {res['remarks']}")


# ==============================================================================
# TAB 2: BATCH PROCESSOR
# ==============================================================================
with tab_batch:
    head_col, dl_col = st.columns([3, 1])
    with head_col:
        st.subheader("Source Selection")
    with dl_col:
        st.download_button(
            label="📥 Download Template",
            data=get_empty_template_excel(),
            file_name="TNUWWB_Status_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Download an empty template with expected column names.",
        )

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
        gsheet_url = st.text_input("Paste Google Sheet URL", placeholder="https://docs.google.com/spreadsheets/d/your-sheet-id/edit#gid=0")
        if gsheet_url:
            try:
                csv_url = convert_gsheet_url_to_csv(gsheet_url)
                df_g = pd.read_csv(csv_url, dtype=str)
                loaded_dfs["Google_Sheet"] = df_g
                st.success(f"Connected ({len(df_g)} rows loaded).")
            except Exception as ex:
                st.error(f"Error loading Google Sheet: {ex}")

    if loaded_dfs:
        st.markdown("---")
        processable_records = []

        for sheet_name, df in loaded_dfs.items():
            name_col = next((c for c in df.columns if c.strip().lower() in ["name", "customer name", "applicant name"]), None)
            phone_col = next((c for c in df.columns if c.strip().lower() in ["phone no", "mobile no", "phone", "mobile"]), None)
            app_col = next((c for c in df.columns if c.strip().lower() in ["application no", "appl code", "application number", "app no"]), None)
            status_col = next((c for c in df.columns if c.strip().lower() in ["status", "current status", "application status"]), None)

            if not phone_col or not app_col:
                continue

            for idx, row in df.iterrows():
                app_no = str(row[app_col]).strip() if pd.notna(row[app_col]) else ""
                phone = str(row[phone_col]).strip() if pd.notna(row[phone_col]) else ""
                name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else "Unknown"
                prev_status = str(row[status_col]).strip() if status_col and pd.notna(row[status_col]) else "Not Checked"

                if not app_no or app_no == "nan" or not phone or phone == "nan":
                    continue

                processable_records.append({
                    "sheet_name": sheet_name,
                    "row_index": idx,
                    "Name": name,
                    "Application No": app_no,
                    "Phone No": phone,
                    "Previous Status": prev_status,
                    "Is Already Approved": "approved" in prev_status.lower(),
                })

        if processable_records:
            df_preview = pd.DataFrame(processable_records)
            col_m1, col_m2 = st.columns(2)
            col_m1.metric("Total Records Found", len(df_preview))
            col_m2.metric("Unapproved / Need Check", len(df_preview[~df_preview["Is Already Approved"]]))

            only_unapproved = st.checkbox("Check ONLY unapproved / pending records", value=True)

            if st.button("🚀 Start Verification", type="primary"):
                targets = [r for r in processable_records if not r["Is Already Approved"]] if only_unapproved else processable_records

                if not targets:
                    st.info("No records need checking.")
                else:
                    progress_bar = st.progress(0.0)
                    status_banner = st.empty()
                    results = []
                    cloud_payload = []

                    for i, item in enumerate(targets):
                        progress_bar.progress((i + 1) / len(targets))
                        status_banner.text(f"Checking ({i+1}/{len(targets)}): {item['Application No']}")

                        res = fetch_application_status(item["Application No"], item["Phone No"], captcha_val)

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
                            "Status Changed": "YES" if item["Previous Status"].lower() != res["status"].lower() else "NO",
                        })

                        # Collect record for upsert
                        cloud_payload.append({
                            "app_no": item["Application No"],
                            "name": item["Name"],
                            "phone": item["Phone No"],
                            "status": res["status"],
                            "remarks": res["remarks"],
                            "date": res["date"],
                        })

                        time.sleep(request_delay)

                    status_banner.text("Verification complete ...")
                    sync_res = sync_records_to_cloud(cloud_payload, st.session_state["username"])

                    if sync_res.get("success"):
                        st.success(f"☁️ Successfully done the operation.")
                    else:
                        st.warning(f"Status checked, but cloud sync warning: {sync_res.get('message')}")

                    st.session_state["comparison_results"] = pd.DataFrame(results)
                    st.session_state["source_dfs"] = loaded_dfs

    # Step 2: Download local updated file
    if "comparison_results" in st.session_state:
        st.markdown("---")
        comp_df = st.session_state["comparison_results"]
        st.dataframe(comp_df, use_container_width=True)

        updated_dfs = {k: v.copy() for k, v in st.session_state["source_dfs"].items()}
        for _, row in comp_df.iterrows():
            s_name = row["Sheet"]
            r_idx = row["Row Index"]
            if s_name in updated_dfs:
                for col in ["Status", "Remarks", "Last Checked Date"]:
                    if col not in updated_dfs[s_name].columns:
                        updated_dfs[s_name][col] = ""
                updated_dfs[s_name].at[r_idx, "Status"] = row["New Live Status"]
                updated_dfs[s_name].at[r_idx, "Remarks"] = row["Remarks"]
                updated_dfs[s_name].at[r_idx, "Last Checked Date"] = row["Status Date"]

        excel_output = io.BytesIO()
        with pd.ExcelWriter(excel_output, engine="openpyxl") as writer:
            for s_name, df_out in updated_dfs.items():
                df_out.to_excel(writer, index=False, sheet_name=s_name[:31])

        st.download_button(
            label="✅ Download Updated Local Excel",
            data=excel_output.getvalue(),
            file_name="TNUWWB_Updated_Status.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
