import streamlit as st
import os

st.set_page_config(layout="wide", page_title="Forecast Producción", page_icon="📦")

# CSS
st.markdown("""<style>
.main { background: #f0f2f6; }
div[data-testid="stMetricValue"] { font-size: 1.5rem !important; font-weight: 700; }
div[data-testid="stMetricDelta"] { font-size: 0.85rem !important; }
</style>""", unsafe_allow_html=True)

os.makedirs("datos", exist_ok=True)

from auth import init_session, render_login

init_session()

if not st.session_state["authenticated"]:
    render_login()
    st.stop()

# ── SIDEBAR ──────────────────────────────────────────────────────────────────
IS_ADMIN      = st.session_state["user_role"] == "admin"
MY_COMERCIAL  = st.session_state["user_comercial"]

with st.sidebar:
    st.title("📦 Forecast Producción")
    if IS_ADMIN:
        st.success("👑 Administrador")
    else:
        st.info(f"👤 {MY_COMERCIAL}")
    st.caption(f"📧 {st.session_state['current_user']}")
    st.markdown("---")
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        for k in ["authenticated", "otp_sent", "otp_code", "current_user",
                  "user_role", "user_comercial", "otp_attempts", "otp_timestamp"]:
            st.session_state[k] = False if k == "authenticated" else None
        st.rerun()

# ── ROUTE ─────────────────────────────────────────────────────────────────────
if IS_ADMIN:
    from views_admin import render_admin_tabs
    render_admin_tabs()
else:
    from views_comercial import render_comercial_tabs
    render_comercial_tabs(MY_COMERCIAL)
