import streamlit as st
import os, random, smtplib, sys, json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from data import load_users, load_delegaciones, get_managed_comerciales

ADMIN_EMAIL = "vbrrsg@gmail.com"


def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


def _get_smtp_credentials():
    """Lee SMTP desde Snowflake Secret (_snowflake) o st.secrets."""
    try:
        import _snowflake
        raw   = _snowflake.get_generic_secret_string('SMTP_CREDENTIALS')
        creds = json.loads(raw)
        return (creds.get('smtp_user', ''), creds.get('smtp_pass', ''),
                'smtp.gmail.com', 587)
    except Exception:
        pass
    return (
        _secret("SMTP_USER", ""),
        _secret("SMTP_PASSWORD", ""),
        _secret("SMTP_SERVER", "smtp.gmail.com"),
        int(_secret("SMTP_PORT", "587"))
    )


def send_otp(email_to, otp):
    smtp_user, smtp_pass, smtp_server, smtp_port = _get_smtp_credentials()
    if not smtp_user or not smtp_pass:
        print(f"[DEV] OTP para {email_to}: {otp}", file=sys.stderr)
        with st.expander("⚙️ SMTP no configurado — ver código (solo admin)"):
            st.code(otp)
        return True
    try:
        msg = MIMEMultipart()
        msg['From']    = smtp_user
        msg['To']      = email_to
        msg['Subject'] = "Código de acceso — Forecast Producción"
        msg.attach(MIMEText(
            f"Tu código de acceso temporal es: {otp}\n\nVálido por 5 minutos.", 'plain'))
        s = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, email_to, msg.as_string())
        s.quit()
        return True
    except Exception as e:
        st.error(f"❌ Error SMTP: `{type(e).__name__}: {e}`")
        with st.expander("⚙️ Acceso de emergencia — ver código"):
            st.code(otp)
        return True


def init_session():
    for k, v in [("authenticated", False), ("otp_sent", False),
                  ("otp_code", None), ("current_user", None),
                  ("user_role", None), ("user_comercial", None),
                  ("otp_attempts", 0), ("otp_timestamp", None),
                  ("sf_session", None)]:
        if k not in st.session_state:
            st.session_state[k] = v


def render_login():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown(
            "<h2 style='text-align:center;color:#1e3a8a'>📦 Forecast de Producción</h2>",
            unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align:center;color:gray'>Acceso para comerciales y administración</p>",
            unsafe_allow_html=True)

        if not st.session_state["otp_sent"]:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="tu@empresa.com")
                pwd   = st.text_input("Contraseña", type="password")
                if st.form_submit_button("Siguiente →", use_container_width=True):
                    try:
                        u  = load_users()
                        ec = email.strip().lower()
                        if not u:
                            st.error("⚠️ No se pudo conectar a Snowflake. "
                                     "Revisa los Secrets de Streamlit Cloud.")
                        elif ec in u and u[ec]["password"] == pwd:
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
                    except Exception as ex:
                        st.error(f"❌ Error al conectar: `{type(ex).__name__}: {ex}`")
        else:
            with st.form("otp_form"):
                st.info("Se ha enviado un código de 6 dígitos a tu email.")
                otp_in = st.text_input("Código OTP", max_chars=6, type="password")
                if st.form_submit_button("Validar acceso", use_container_width=True):
                    age = (datetime.now() - st.session_state["otp_timestamp"]).total_seconds()
                    if age > 300:
                        st.error("⏰ Código expirado.")
                        st.session_state["otp_sent"] = False
                    elif st.session_state["otp_attempts"] >= 3:
                        st.error("🚫 Demasiados intentos.")
                        st.session_state["otp_sent"] = False
                    elif otp_in.strip() == st.session_state["otp_code"]:
                        u  = load_users()
                        ec = st.session_state["current_user"]
                        st.session_state.update({
                            "authenticated": True, "otp_code": None,
                            "user_role":      u[ec]["role"],
                            "user_comercial": u[ec]["comercial"]
                        })
                        st.rerun()
                    else:
                        st.session_state["otp_attempts"] += 1
                        st.error(f"❌ Código incorrecto. "
                                 f"Intentos restantes: {3 - st.session_state['otp_attempts']}")
            if st.button("← Volver", use_container_width=True):
                st.session_state["otp_sent"] = False
                st.rerun()
