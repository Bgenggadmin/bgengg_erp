"""Save / Issue tab — persist costing to DB and hand off to offer_generator."""
from __future__ import annotations
import streamlit as st

from bg_estimation_costing import db
from bg_estimation_costing.utils.state import S, reset_state
from bg_estimation_costing.utils.totals import (
    price_summary, total_equipment_cost,
)
from bg_estimation_costing.utils.persistence import save_costing


def render():
    st.subheader("Save / Issue Costing")

    if not db.is_connected():
        st.error("⚠️ Database is not connected. Costings can't be saved.")
        st.caption("Configure the Supabase connection (`.streamlit/secrets.toml`) "
                   "to enable persistence.")
    else:
        ps = price_summary()
        st.write("Saving will:")
        st.write(f"• Persist this costing to **mee_qps_costings** "
                 f"(supply cost ₹{ps['supply_cost']/1e5:,.1f} L · "
                 f"quote price ₹{ps['quote_price']/1e5:,.1f} L)")
        st.write(f"• Replace child rows in **mee_qps_costing_lines** "
                 f"({len(S('equipment_lines', []) or [])} equipment lines)")
        st.write("• Make this costing available to **bg_offer_generator**")

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("💾 Save as Draft", type="primary",
                         use_container_width=True):
                if save_costing(mark_issued=False):
                    st.success(f"✅ Saved costing #{S('costing_id')} as Draft.")
                    st.rerun()
        with c2:
            if st.button("✅ Save & Mark Issued", use_container_width=True):
                if not S("client_name") or not S("project_name"):
                    st.warning("Please fill Client Name and Project Name "
                               "before issuing.")
                elif total_equipment_cost() == 0:
                    st.warning("Add at least one priced equipment line "
                               "before issuing.")
                elif save_costing(mark_issued=True):
                    st.success(f"✅ Issued costing #{S('costing_id')} — now "
                               f"available to bg_offer_generator.")
                    st.rerun()
        with c3:
            if S("costing_id"):
                if st.button("🗑️ Reset (start fresh)",
                             use_container_width=True, type="secondary"):
                    reset_state()
                    st.rerun()

    st.divider()
    st.markdown("### 🔌 Hand-off to Offer Generator")
    cid = S("costing_id")
    if cid and S("status") == "Issued":
        st.success(f"✅ Costing #{cid} is **Issued**. "
                   f"`bg_offer_generator` can fetch it via "
                   f"`mee_qps_costings.id = {cid}`.")
        st.code(
            f"# Inside bg_offer_generator:\n"
            f"from bg_estimation_costing import db as costing_db\n\n"
            f"costing = costing_db.get_costing({cid})\n"
            f"lines   = costing_db.get_costing_lines({cid})",
            language="python",
        )
    elif cid:
        st.info(f"Costing #{cid} is currently **{S('status')}**. "
                f"Mark it Issued before offer generation.")
    else:
        st.caption("Save the costing first to enable hand-off.")
