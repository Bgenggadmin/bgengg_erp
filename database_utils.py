import streamlit as st
import pandas as pd

def fetch_all_master_data(conn):
    """
    Central function to fetch all master lists from Supabase.
    Pass 'conn' as an argument so it can be used in any page.
    """
    try:
        # Fetching data with a fallback to an empty list if table is empty
        staff = conn.table("master_staff").select("name").order("name").execute()
        workers = conn.table("master_workers").select("name").order("name").execute()
        machines = conn.table("master_machines").select("name").order("name").execute()
        vehicles = conn.table("master_vehicles").select("reg_no").order("reg_no").execute()
        gates = conn.table("production_gates").select("gate_name").order("step_order").execute()
        
        return {
            "staff": [s['name'] for s in (staff.data or [])],
            "workers": [w['name'] for w in (workers.data or [])],
            "machines": [m['name'] for m in (machines.data or [])],
            "vehicles": [v['reg_no'] for v in (vehicles.data or [])],
            "gates": [g['gate_name'] for g in (gates.data or [])]
        }
    except Exception as e:
        st.error(f"⚠️ Master Data Sync Error: {e}")
        return {
            "staff": [], 
            "workers": [], 
            "machines": [], 
            "vehicles": [], 
            "gates": []
        }
