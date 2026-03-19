import streamlit as st
from datetime import datetime
import pytz

# --- 1. CLOCK CALIBRATION ---
IST = pytz.timezone('Asia/Kolkata')
time_now = datetime.now(IST).strftime('%H:%M:%S')

# --- 2. THE INTERFACE ---
st.title("B&G System Control")
st.metric(label="Current Shift Time (IST)", value=time_now)

# --- 3. THE LOGGING LOGIC ---
if st.button("Log Production Entry"):
    # This captures the EXACT moment the button (valve) is pressed
    exact_log_time = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
    st.write(f"Entry recorded at: {exact_log_time}")
# --- SYSTEM CONFIGURATION ---
st.set_page_config(page_title="B&G Test Bench", layout="centered")
# --- PASSWORD PROTECTION ---
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == "9025": # You can change this!
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True

if not check_password():
    st.stop()  # Do not run the rest of the app if password isn't correct

# --- DATA INTAKE (THE MANIFOLD) ---
st.title("⚙️ Engineering Test Bench Session")
st.header("Sub-System: The Import")

# --- THE SENSOR CHECK ---
# We are checking if the 'Streamlit' valve is pressurized and flowing
status = "SYSTEM N ACTIVE"

# --- THE OUTPUT GAUGE ---
st.metric(label="Manifold Status", value=status)

if st.button("Initialize System"):
    st.success("The 'Import' protocol is stable. Resources are flowing.")
else:
    st.warning("System on Standby. Awaiting operator input.")
