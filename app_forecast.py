import streamlit as st
from snowflake.snowpark.context import get_active_session
from auth import init_session, render_login
from views_admin import render_admin_tabs
from views_comercial import render_comercial_tabs

st.set_page_config(page_title="Forecast de Producción", page_icon="📦", layout="wide")

# Obtener sesión Snowflake
try:
    session = get_active_session()
except Exception:
    session = None

init_session()

if not st.session_state["authenticated"]:
    render_login(session)
else:
    role      = st.session_state["user_role"]
    comercial = st.session_state["user_comercial"]

    # Header con botón logout
    col1, col2 = st.columns([8, 1])
    with col1:
        icon = "🔑" if role == "admin" else "👤"
        st.markdown(f"**{icon} {st.session_state['current_user']}** | {role.upper()}")
    with col2:
        if st.button("Cerrar sesión"):
            for k in ["authenticated", "otp_sent", "otp_code", "current_user",
                      "user_role", "user_comercial", "otp_attempts", "otp_timestamp"]:
                st.session_state[k] = False if k == "authenticated" else None
            st.rerun()

    st.markdown("---")

    if role == "admin":
        render_admin_tabs(session)
    else:
        render_comercial_tabs(session, comercial)
