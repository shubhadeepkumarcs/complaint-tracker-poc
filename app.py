import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("tracker_poc.db", check_same_thread=False)
    cursor = conn.cursor()
    
    # Complaints Table (Added status_changed_time for tracking duration per status)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            serial_number TEXT PRIMARY KEY,
            location_name TEXT,
            address TEXT,
            contact_no TEXT,
            model_number TEXT,
            issue TEXT,
            status TEXT,
            assigned_technician TEXT,
            resolution_notes TEXT,
            status_changed_time TEXT,
            last_updated TEXT,
            updated_by TEXT
        )
    """)
    
    # Audit Trail / Version History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_trail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_number TEXT,
            timestamp TEXT,
            username TEXT,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT
        )
    """)
    
    # Inventory Table with Individual Thresholds
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            item_code TEXT PRIMARY KEY,
            item_name TEXT,
            stock_count INTEGER,
            min_threshold INTEGER
        )
    """)
    
    # Inventory Requests Table with AMC / PO fields
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_number TEXT,
            item_code TEXT,
            quantity INTEGER,
            cost_type TEXT,
            po_number TEXT,
            po_date TEXT,
            requested_by TEXT,
            status TEXT
        )
    """)
    
    conn.commit()
    return conn

conn = init_db()

# --- HELPER LOGIC FOR LOGGING CHANGES ---
def log_change(conn, serial, user, field, old_val, new_val):
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO audit_trail (serial_number, timestamp, username, field_changed, old_value, new_value)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (serial, timestamp, user, field, str(old_val), str(new_val)))
    conn.commit()

# --- INDIVIDUAL LOW STOCK HIGHLIGHT FUNCTION ---
def highlight_individual_low_stock(row):
    color = 'background-color: #ffcccc' if row['stock_count'] <= row['min_threshold'] else ''
    return [color] * len(row)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Field Service & Complaint Manager", layout="wide")

st.title("🛠️ Field Service & Complaint Management System")
st.markdown("---")

user_role = st.sidebar.selectbox("Simulate User / Role", ["Technician / User", "Manager"])
current_user = st.sidebar.text_input("Logged-in Username", "Shubhadeep")

tabs = st.tabs(["1. Incident Logger & Stages", "2. Inventory & PO Approvals", "3. Audit Trail & Version History", "4. Monthly & Detailed Reports"])

# --- TAB 1: INCIDENT LOGGER & WORKFLOW STAGES ---
with tabs[0]:
    st.subheader("Manage Machine Complaints, PO Statuses & Duration Tracking")
    
    uploaded_master = st.file_uploader("Upload Master Excel File (master_data.xlsx)", type=["xlsx"])
    master_df = None
    if uploaded_master:
        master_df = pd.read_excel(uploaded_master, sheet_name="Locations")
        st.success("Master Excel Loaded Successfully!")

    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Log New Incident / Override Master")
        serial_input = st.text_input("Machine Serial Number", "SN-1001")
        
        loc_val, addr_val, contact_val, model_val = "", "", "", ""
        if master_df is not None and not master_df.empty:
            match = master_df[master_df['serial_number'].astype(str) == serial_input]
            if not match.empty:
                loc_val = match.iloc[0]['location_name']
                addr_val = match.iloc[0]['address']
                contact_val = str(match.iloc[0]['contact_no'])
                model_val = match.iloc[0]['model_number']

        location = st.text_input("Report Location", value=loc_val)
        address = st.text_input("Address", value=addr_val)
        contact = st.text_input("Contact No", value=contact_val)
        model = st.text_input("Model Number", value=model_val)
        issue = st.text_area("Reported Issue", "Machine not dispensing cash properly.")
        
        if st.button("Log / Register Incident"):
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM complaints WHERE serial_number = ?", (serial_input,))
            existing = cursor.fetchone()
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not existing:
                cursor.execute("""
                    INSERT INTO complaints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (serial_input, location, address, contact, model, issue, "1. Call Log", "Unassigned", "", timestamp, timestamp, current_user))
                conn.commit()
                st.success(f"Incident {serial_input} registered successfully!")
            else:
                cursor.execute("""
                    UPDATE complaints SET location_name=?, address=?, contact_no=?, model_number=?, issue=?
                    WHERE serial_number=?
                """, (location, address, contact, model, issue, serial_input))
                conn.commit()
                log_change(conn, serial_input, current_user, "Master Override", "Previous Data", "Updated via Incident Logger")
                st.info(f"Incident {serial_input} details overridden with new input.")
            st.rerun()

    with col2:
        st.markdown("### Update Workflow Status & View Status Duration")
        cursor = conn.cursor()
        cursor.execute("SELECT serial_number FROM complaints")
        all_serials = [row[0] for row in cursor.fetchall()]
        
        if all_serials:
            selected_serial = st.selectbox("Select Machine Serial to Update", all_serials)
            
            cursor.execute("SELECT status, assigned_technician, resolution_notes, status_changed_time FROM complaints WHERE serial_number = ?", (selected_serial,))
            curr_status, curr_tech, curr_notes, curr_status_time = cursor.fetchone()
            
            # Calculate days pending in current status
            if curr_status_time:
                try:
                    dt_start = datetime.strptime(curr_status_time, "%Y-%m-%d %H:%M:%S")
                    days_pending = (datetime.now() - dt_start).days
                    hours_pending = (datetime.now() - dt_start).seconds // 3600
                    st.info(⏱️ **Time in Current Status (`{curr_status}`):** {days_pending} days, {hours_pending} hours)
                except Exception:
                    st.info(⏱️ **Current Status:** {curr_status})
            
            # Workflow options including PO Quotation statuses
            workflow_options = [
                "1. Call Log", 
                "2. Video Call Support Queue", 
                "3. Branch Visit", 
                "4. Spare Change", 
                "5. Quotation Pending",
                "6. Quotation Send",
                "7. Final Fix & Closure",
                "✅ Closed / Resolved"
            ]
            
            default_index = workflow_options.index(curr_status) if curr_status in workflow_options else 0
            new_status = st.selectbox("Current Stage / Status", workflow_options, index=default_index)
            technician = st.text_input("Assigned Technician / Support Agent", value=curr_tech)
            resolution_notes = st.text_area("Resolution / Status Notes", value=curr_notes if curr_notes else "")
            
            if st.button("Update Stage / Close Ticket"):
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # If status changed, update status_changed_time clock
                if new_status != curr_status:
                    log_change(conn, selected_serial, current_user, "Status", curr_status, new_status)
                    cursor.execute("""
                        UPDATE complaints SET status = ?, assigned_technician = ?, resolution_notes = ?, status_changed_time = ?, last_updated = ?, updated_by = ?
                        WHERE serial_number = ?
                    """, (new_status, technician, resolution_notes, timestamp, timestamp, current_user, selected_serial))
                else:
                    cursor.execute("""
                        UPDATE complaints SET assigned_technician = ?, resolution_notes = ?, last_updated = ?, updated_by = ?
                        WHERE serial_number = ?
                    """, (technician, resolution_notes, timestamp, current_user, selected_serial))
                
                conn.commit()
                st.success("Ticket stage and status updated successfully!")
                st.rerun()
        else:
            st.warning("No incidents logged yet.")

# --- TAB 2: INVENTORY & PO APPROVALS ---
with tabs[1]:
    st.subheader("Inventory Master & Spare Request Workflow (AMC vs PO)")
    
    if user_role == "Manager":
        with st.expander("📦 Manager: Bulk Upload / Update Inventory via Excel"):
            st.markdown("Upload Excel with columns: `item_code`, `item_name`, `stock_count`, `min_threshold`")
            uploaded_inv = st.file_uploader("Upload Inventory Master Excel", type=["xlsx"], key="inv_upload")
            if uploaded_inv:
                inv_upload_df = pd.read_excel(uploaded_inv)
                required_cols = {"item_code", "item_name", "stock_count", "min_threshold"}
                if required_cols.issubset(inv_upload_df.columns):
                    cursor = conn.cursor()
                    for _, row in inv_upload_df.iterrows():
                        cursor.execute("""
                            INSERT INTO inventory (item_code, item_name, stock_count, min_threshold)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(item_code) DO UPDATE SET 
                            item_name=excluded.item_name, 
                            stock_count=excluded.stock_count,
                            min_threshold=excluded.min_threshold
                        """, (str(row['item_code']), str(row['item_name']), int(row['stock_count']), int(row['min_threshold'])))
                    conn.commit()
                    st.success("Inventory master successfully updated from Excel!")
                else:
                    st.error(f"Excel file must contain exact columns: {', '.join(required_cols)}")
    
    col_inv1, col_inv2 = st.columns(2)
    
    with col_inv1:
        st.markdown("### Inventory Stock List")
        inv_df = pd.read_sql("SELECT * FROM inventory", conn)
        
        if not inv_df.empty:
            styled_inv = inv_df.style.apply(highlight_individual_low_stock, axis=1)
            st.dataframe(styled_inv, use_container_width=True)
            
            low_stock_df = inv_df[inv_df['stock_count'] <= inv_df['min_threshold']]
            if not low_stock_df.empty:
                st.warning(f"⚠️ {len(low_stock_df)} items have dropped below their individual minimum threshold!")
                low_stock_file = "low_stock_report.xlsx"
                low_stock_df.to_excel(low_stock_file, index=False)
                with open(low_stock_file, "rb") as f:
                    st.download_button(
                        label="📥 Download Low-Stock Alert Report",
                        data=f,
                        file_name="Low_Stock_Report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        else:
            st.info("No inventory data loaded yet. Upload an Excel file above.")
        
        st.markdown("### Request Spares for a Branch")
        cursor = conn.cursor()
        cursor.execute("SELECT serial_number FROM complaints")
        complaint_serials = [row[0] for row in cursor.fetchall()]
        
        if complaint_serials and not inv_df.empty:
            req_serial = st.selectbox("Target Machine Serial", complaint_serials, key="req_s")
            selected_items = st.multiselect("Select Spare Parts Needed", inv_df['item_code'].tolist())
            
            cost_type = st.radio("Spare Cost Basis", ["AMC (No Additional Cost)", "PO Required"])
            
            quantities = {}
            if selected_items:
                st.markdown("**Specify Quantities for Selected Parts:**")
                for item in selected_items:
                    item_name_row = inv_df[inv_df['item_code'] == item]['item_name'].values[0]
                    quantities[item] = st.number_input(f"Qty for {item} ({item_name_row})", min_value=1, value=1, key=f"qty_{item}")
            
            if st.button("Submit Spare Request for Approval"):
                if selected_items:
                    cursor = conn.cursor()
                    for item in selected_items:
                        qty = quantities[item]
                        cursor.execute("""
                            INSERT INTO inventory_requests (serial_number, item_code, quantity, cost_type, po_number, po_date, requested_by, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (req_serial, item, qty, cost_type, "", "", current_user, "Pending Approval"))
                    conn.commit()
                    st.success(f"Successfully submitted batch request for {len(selected_items)} parts!")
                    st.rerun()
                else:
                    st.warning("Please select at least one spare part.")
        else:
            st.info("Log an incident first before requesting parts.")

    with col_inv2:
        st.markdown("### Manager Approval Queue")
        pending_reqs = pd.read_sql("SELECT * FROM inventory_requests WHERE status = 'Pending Approval'", conn)
        
        if not pending_reqs.empty:
            st.dataframe(pending_reqs, use_container_width=True)
            req_id_to_process = st.selectbox("Select Request ID to Action", pending_reqs['id'].tolist())
            
            cursor = conn.cursor()
            cursor.execute("SELECT cost_type FROM inventory_requests WHERE id = ?", (req_id_to_process,))
            req_row = cursor.fetchone()
            req_cost_type = req_row[0] if req_row else "AMC (No Additional Cost)"
            
            po_num_input, po_date_input = "", ""
            if req_cost_type == "PO Required":
                st.info("⚠️ This request requires a Purchase Order (PO).")
                po_num_input = st.text_input("Enter PO Number")
                po_date_input = st.date_input("Enter PO Date").strftime("%Y-%m-%d")
            
            if user_role == "Manager":
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    if st.button("Approve Request"):
                        if req_cost_type == "PO Required" and not po_num_input:
                            st.error("Manager approval requires a valid PO Number!")
                        else:
                            cursor = conn.cursor()
                            cursor.execute("SELECT item_code, quantity FROM inventory_requests WHERE id = ?", (req_id_to_process,))
                            i_code, i_qty = cursor.fetchone()
                            
                            cursor.execute("UPDATE inventory SET stock_count = stock_count - ? WHERE item_code = ?", (i_qty, i_code))
                            cursor.execute("""
                                UPDATE inventory_requests SET status = 'Approved', po_number = ?, po_date = ? 
                                WHERE id = ?
                            """, (po_num_input, po_date_input, req_id_to_process))
                            conn.commit()
                            log_change(conn, "INVENTORY", current_user, f"Part Issued ({i_code})", "Pending", f"Approved (PO: {po_num_input})")
                            st.success("Request approved and inventory count reduced!")
                            st.rerun()
                with col_m2:
                    if st.button("Reject Request"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE inventory_requests SET status = 'Rejected' WHERE id = ?", (req_id_to_process,))
                        conn.commit()
                        st.warning("Request rejected.")
                        st.rerun()
            else:
                st.info("Switch role to 'Manager' in sidebar to action approvals.")
        else:
            st.info("No pending spare requests found.")

# --- TAB 3: AUDIT TRAIL & VERSION HISTORY ---
with tabs[2]:
    st.subheader("Full Audit Trail & Version History Matrix")
    audit_df = pd.read_sql("SELECT * FROM audit_trail ORDER BY id DESC", conn)
    st.dataframe(audit_df, use_container_width=True)

# --- TAB 4: MONTHLY & DETAILED REPORTS ---
with tabs[3]:
    st.subheader("Monthly Summary & Detailed Incident Analytics (With Days Pending)")
    
    complaints_df = pd.read_sql("SELECT * FROM complaints", conn)
    
    if not complaints_df.empty:
        # Calculate live days pending in current status for reporting
        def calc_days_pending(val):
            if pd.isna(val):
                return 0
            try:
                dt = datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S")
                return (datetime.now() - dt).days
            except Exception:
                return 0

        complaints_df['Days Pending in Current Status'] = complaints_df['status_changed_time'].apply(calc_days_pending)
        
        complaints_df['last_updated'] = pd.to_datetime(complaints_df['last_updated'], errors='coerce')
        complaints_df['Month-Year'] = complaints_df['last_updated'].dt.to_period('M').astype(str)
        
        st.markdown("### 📊 Monthly Summary Report")
        monthly_summary = complaints_df.groupby(['Month-Year', 'status']).size().unstack(fill_value=0)
        monthly_summary['Total Calls Logged'] = complaints_df.groupby('Month-Year').size()
        st.dataframe(monthly_summary, use_container_width=True)
        
        st.markdown("### 📋 Detailed Incident Report (With Status Age)")
        st.dataframe(complaints_df, use_container_width=True)
        
        output_file = "comprehensive_incident_report.xlsx"
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            monthly_summary.to_excel(writer, sheet_name='Monthly Summary')
            complaints_df.to_excel(writer, sheet_name='Detailed Report', index=False)
            
        with open(output_file, "rb") as f:
            st.download_button(
                label="📥 Download Complete Excel Report (Summary + Details)",
                data=f,
                file_name="Monthly_And_Detailed_Complaint_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.info("No incident records available to generate reports.")