import streamlit as st
import pandas as pd
import os, random, smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

DATA_DIR = "datos"
USERS_FILE = os.path.join(DATA_DIR, "usuarios_forecast.xlsx")
DELEGACIONES_FILE = os.path.join(DATA_DIR, "delegaciones_forecast.xlsx")
ADMIN_EMAIL = "vbrrsg@gmail.com"

def _secret(key, default=""):
    """Safely read a Streamlit secret, falling back to env var or default."""
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)

def _get_admin_pass():
    return _secret("ADMIN_PASSWORD", "Albope5@")

def load_users():
    """Load users from Excel. Columns: Email | Contraseña | Comercial"""
    users = {ADMIN_EMAIL: {"password": _get_admin_pass(), "comercial": "__ADMIN__", "role": "admin"}}
    if os.path.exists(USERS_FILE):
        try:
            df = pd.read_excel(USERS_FILE)
            for _, r in df.iterrows():
                email = str(r.iloc[0]).strip().lower()
                pwd = str(r.iloc[1]).strip()
                com = str(r.iloc[2]).strip() if len(df.columns) >= 3 else ""
                if email and "@" in email and email != "nan":
                    users[email] = {"password": pwd, "comercial": com, "role": "comercial"}
        except Exception as e:
            st.error(f"Error leyendo usuarios: {e}")
    return users

def load_delegaciones():
    """Load delegation table. Columns: Comercial_Titular | Comercial_Gestor
    Means: Gestor can see and edit Titular's data too."""
    if os.path.exists(DELEGACIONES_FILE):
        try:
            df = pd.read_excel(DELEGACIONES_FILE)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except:
            pass
    return pd.DataFrame(columns=["Comercial_Titular", "Comercial_Gestor"])

def get_managed_comerciales(my_comercial):
    """Returns list of comerciales this user can see/edit (own + delegated)."""
    result = [my_comercial]
    df_del = load_delegaciones()
    if not df_del.empty and "Comercial_Gestor" in df_del.columns:
        rows = df_del[df_del["Comercial_Gestor"].str.strip() == my_comercial]
        for _, r in rows.iterrows():
            titular = str(r["Comercial_Titular"]).strip()
            if titular and titular != my_comercial:
                result.append(titular)
    return result

def send_otp(email_to, otp):
    smtp_server = _secret("SMTP_SERVER", "smtp.gmail.com")
    smtp_port   = int(_secret("SMTP_PORT", "587"))
    smtp_user   = _secret("SMTP_USER", "")
    smtp_pass   = _secret("SMTP_PASSWORD", "")
    if not smtp_user or not smtp_pass:
        # Local dev only: print to server log, never show on screen
        import sys
        print(f"[DEV] OTP para {email_to}: {otp}", file=sys.stderr)
        st.info("📧 Código enviado. Revisa la consola del servidor (modo desarrollo sin SMTP).")
        return True
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = email_to
        msg['Subject'] = "Código de acceso — Forecast Producción"
        body = f"Tu código de acceso temporal es: {otp}\n\nVálido por 5 minutos."
        msg.attach(MIMEText(body, 'plain'))
        s = smtplib.SMTP(smtp_server, smtp_port)
        s.starttls(); s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, email_to, msg.as_string()); s.quit()
        return True
    except Exception as e:
        st.error(f"Error SMTP: {e}")
        return False

def init_session():
    for k, v in [("authenticated", False), ("otp_sent", False),
                 ("otp_code", None), ("current_user", None),
                 ("user_role", None), ("user_comercial", None),
                 ("otp_attempts", 0), ("otp_timestamp", None)]:
        if k not in st.session_state:
            st.session_state[k] = v

def render_login():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h2 style='text-align:center;color:#1e3a8a'>📦 Forecast de Producción</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:gray'>Acceso para comerciales y administración</p>", unsafe_allow_html=True)

        if not st.session_state["otp_sent"]:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="tu@empresa.com")
                pwd = st.text_input("Contraseña", type="password")
                if st.form_submit_button("Siguiente →", use_container_width=True):
                    u = load_users()
                    ec = email.strip().lower()
                    if ec in u and u[ec]["password"] == pwd:
                        otp = str(random.randint(100000, 999999))
                        st.session_state.update({
                            "current_user": ec, "otp_code": otp,
                            "otp_attempts": 0, "otp_timestamp": datetime.now()
                        })
                        if send_otp(ec, otp):
                            st.session_state["otp_sent"] = True
                            st.rerun()
                    else:
                        st.error("❌ Credenciales incorrectas")
        else:
            # Never show OTP on screen in any mode
            with st.form("otp_form"):
                st.info("Se ha enviado un código de 6 dígitos a tu email.")
                otp_in = st.text_input("Código OTP", max_chars=6)
                if st.form_submit_button("Validar acceso", use_container_width=True):
                    age = (datetime.now() - st.session_state["otp_timestamp"]).total_seconds()
                    if age > 300:
                        st.error("⏰ Código expirado. Vuelve a intentarlo.")
                        st.session_state["otp_sent"] = False
                    elif st.session_state["otp_attempts"] >= 3:
                        st.error("🚫 Demasiados intentos.")
                        st.session_state["otp_sent"] = False
                    elif otp_in.strip() == st.session_state["otp_code"]:
                        u = load_users()
                        ec = st.session_state["current_user"]
                        st.session_state.update({
                            "authenticated": True, "otp_code": None,
                            "user_role": u[ec]["role"],
                            "user_comercial": u[ec]["comercial"]
                        })
                        st.rerun()
                    else:
                        st.session_state["otp_attempts"] += 1
                        st.error(f"❌ Código incorrecto. Intentos restantes: {3 - st.session_state['otp_attempts']}")
            if st.button("← Volver", use_container_width=True):
                st.session_state["otp_sent"] = False
                st.rerun()
