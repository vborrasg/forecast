import streamlit as st
import pandas as pd
import re
import os

# ── Tablas Snowflake ──────────────────────────────────────────────────────────
FORECAST_TABLE     = "FORECAST_DB.APP.FORECAST_DATA"
USUARIOS_TABLE     = "FORECAST_DB.APP.USUARIOS"
DELEGACIONES_TABLE = "FORECAST_DB.APP.DELEGACIONES"

APP_TO_SF = {
    'Planta': 'PLANTA', 'Actividad': 'ACTIVIDAD', 'Mercado': 'MERCADO',
    'SAP': 'SAP', 'Clientes': 'CLIENTES', 'Comercial': 'COMERCIAL',
    'Qty LY': 'QTY_LY', 'Actual LY': 'ACTUAL_LY',
    'Qty Budget': 'QTY_BUDGET', 'Budget': 'BUDGET',
    'Qty Actual': 'QTY_ACTUAL', 'Actual': 'ACTUAL',
}
SF_TO_APP = {v: k for k, v in APP_TO_SF.items()}

DATA_DIR      = "datos"
ACTIVITY_FILE = os.path.join(DATA_DIR, "_upload_actividad.csv")
MARKET_FILE   = os.path.join(DATA_DIR, "_upload_mercado.xlsx")


# ── Conexión Snowflake (snowflake-connector-python) ──────────────────────────

def _get_connection():
    """Crea o reutiliza una conexión a Snowflake, reconectando si la conexión expiró."""
    # Usar session_state para almacenar la conexión (no cache_resource, que no
    # permite invalidar fácilmente una conexión muerta)
    if '_sf_conn' in st.session_state and st.session_state['_sf_conn'] is not None:
        conn = st.session_state['_sf_conn']
        try:
            # Health check: ejecutar una query trivial para verificar que la conexión vive
            conn.cursor().execute("SELECT 1")
            return conn
        except Exception:
            # Conexión muerta — reconectar
            try:
                conn.close()
            except Exception:
                pass
            st.session_state['_sf_conn'] = None

    # Crear nueva conexión
    import snowflake.connector
    try:
        conn = snowflake.connector.connect(
            account   = st.secrets["SNOWFLAKE_ACCOUNT"],
            user      = st.secrets["SNOWFLAKE_USER"],
            password  = st.secrets["SNOWFLAKE_PASSWORD"],
            warehouse = st.secrets.get("SNOWFLAKE_WAREHOUSE", "FORECAST_WH"),
            database  = st.secrets.get("SNOWFLAKE_DATABASE", "FORECAST_DB"),
            schema    = st.secrets.get("SNOWFLAKE_SCHEMA", "APP"),
            role      = st.secrets.get("SNOWFLAKE_ROLE", "FORECAST_ROLE"),
        )
        st.session_state['_sf_conn'] = conn
        return conn
    except Exception as e:
        st.error(f"❌ Error de conexión a Snowflake: `{type(e).__name__}: {e}`")
        return None


def _query(sql):
    """Ejecuta SQL y devuelve un DataFrame."""
    conn = _get_connection()
    if conn is None:
        return pd.DataFrame()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    except Exception as e:
        st.error(f"❌ Error SQL: `{e}`")
        return pd.DataFrame()


def _exec(sql):
    """Ejecuta SQL sin devolver datos. LANZA EXCEPCIÓN si falla."""
    conn = _get_connection()
    if conn is None:
        raise ConnectionError("No hay conexión a Snowflake")
    conn.cursor().execute(sql)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_es_number(val):
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s or re.match(r'^\s*-\s*€?\s*$', s) or s in ('-', '—'):
        return 0.0
    s = s.replace('€', '').replace(' ', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _extract_sap(client_str):
    m = re.match(r'^\s*(\d+)', str(client_str).strip())
    return m.group(1) if m else None


def _esc(val):
    """Escapa comillas simples para SQL."""
    return str(val).replace("'", "''")


# ── Forecast ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def load_forecast():
    df = _query(f"SELECT * FROM {FORECAST_TABLE}")
    if df.empty:
        return df
    return df.rename(columns=SF_TO_APP)


def save_forecast(df):
    load_forecast.clear()
    conn = _get_connection()
    if conn is None:
        return
    df_sf = df.rename(columns=APP_TO_SF)
    cols  = [c for c in APP_TO_SF.values() if c in df_sf.columns]
    df_sf = df_sf[cols].copy()
    for c in ['QTY_LY', 'ACTUAL_LY', 'QTY_BUDGET', 'BUDGET', 'QTY_ACTUAL', 'ACTUAL']:
        if c in df_sf.columns:
            df_sf[c] = pd.to_numeric(df_sf[c], errors='coerce').fillna(0)

    _exec(f"TRUNCATE TABLE {FORECAST_TABLE}")

    # Insertar en lotes de 100 filas usando INSERT multi-valor
    col_names = ', '.join(cols)
    batch = []
    for _, row in df_sf.iterrows():
        vals = []
        for c in cols:
            v = row[c]
            if c in ['QTY_LY', 'ACTUAL_LY', 'QTY_BUDGET', 'BUDGET', 'QTY_ACTUAL', 'ACTUAL']:
                vals.append(str(float(v)) if pd.notna(v) else '0')
            else:
                vals.append(f"'{_esc(v)}'")
        batch.append(f"({', '.join(vals)})")
        if len(batch) >= 100:
            _exec(f"INSERT INTO {FORECAST_TABLE} ({col_names}) VALUES {', '.join(batch)}")
            batch = []
    if batch:
        _exec(f"INSERT INTO {FORECAST_TABLE} ({col_names}) VALUES {', '.join(batch)}")


def delete_forecast():
    _exec(f"TRUNCATE TABLE {FORECAST_TABLE}")
    load_forecast.clear()


# ── Usuarios ──────────────────────────────────────────────────────────────────

# Admin hardcodeado: siempre puede entrar aunque la tabla esté vacía
_HARDCODED_ADMINS = {
    'vbrrsg@gmail.com': {
        'password': 'Albope5@', 'comercial': '__ADMIN__', 'role': 'admin'
    },
}


@st.cache_data(ttl=60, show_spinner=False)
def load_users():
    # Empezar con los admins hardcodeados (fallback de seguridad)
    users = dict(_HARDCODED_ADMINS)
    df = _query(f"SELECT EMAIL, PASSWORD, COMERCIAL, ROL FROM {USUARIOS_TABLE}")
    if not df.empty:
        for _, r in df.iterrows():
            email = str(r['EMAIL']).strip().lower()
            users[email] = {
                'password':  str(r['PASSWORD']),
                'comercial': str(r['COMERCIAL']),
                'role':      str(r['ROL'])
            }
    return users


def save_users_from_df(df):
    """Guarda usuarios en Snowflake. Lanza excepción si falla."""
    # Primero borrar los datos existentes
    _exec(f"TRUNCATE TABLE {USUARIOS_TABLE}")

    batch = []
    for _, r in df.iterrows():
        email = str(r.iloc[0]).strip().lower()
        pwd   = str(r.iloc[1]).strip()
        com   = str(r.iloc[2]).strip() if len(df.columns) >= 3 else ''
        if email and '@' in email and email != 'nan':
            batch.append(f"('{_esc(email)}', '{_esc(pwd)}', '{_esc(com)}', 'comercial')")
        
        if len(batch) >= 100:
            _exec(f"INSERT INTO {USUARIOS_TABLE} (EMAIL, PASSWORD, COMERCIAL, ROL) VALUES {', '.join(batch)}")
            batch = []
            
    if batch:
        _exec(f"INSERT INTO {USUARIOS_TABLE} (EMAIL, PASSWORD, COMERCIAL, ROL) VALUES {', '.join(batch)}")

    # Siempre mantener admin
    _exec(f"""
        INSERT INTO {USUARIOS_TABLE} (EMAIL, PASSWORD, COMERCIAL, ROL)
        SELECT 'vbrrsg@gmail.com','Albope5@','__ADMIN__','admin'
        WHERE NOT EXISTS (
            SELECT 1 FROM {USUARIOS_TABLE} WHERE EMAIL='vbrrsg@gmail.com')
    """)
    # Invalidar SOLO el cache de usuarios
    load_users.clear()


# ── Delegaciones ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def load_delegaciones():
    df = _query(f"SELECT TITULAR, GESTOR FROM {DELEGACIONES_TABLE}")
    if df.empty:
        return pd.DataFrame(columns=['Comercial_Titular', 'Comercial_Gestor'])
    df.columns = ['Comercial_Titular', 'Comercial_Gestor']
    return df


def save_delegaciones_from_df(df):
    """Guarda delegaciones en Snowflake. Lanza excepción si falla."""
    # Primero borrar los datos existentes
    _exec(f"TRUNCATE TABLE {DELEGACIONES_TABLE}")

    batch = []
    for _, r in df.iterrows():
        t = str(r.iloc[0]).strip()
        g = str(r.iloc[1]).strip()
        if t and g and t != 'nan':
            batch.append(f"('{_esc(t)}', '{_esc(g)}')")
            
        if len(batch) >= 100:
            _exec(f"INSERT INTO {DELEGACIONES_TABLE} (TITULAR, GESTOR) VALUES {', '.join(batch)}")
            batch = []
            
    if batch:
        _exec(f"INSERT INTO {DELEGACIONES_TABLE} (TITULAR, GESTOR) VALUES {', '.join(batch)}")

    # Invalidar SOLO el cache de delegaciones
    load_delegaciones.clear()


def get_managed_comerciales(my_comercial):
    result = [my_comercial]
    df_del = load_delegaciones()
    if not df_del.empty:
        rows = df_del[df_del['Comercial_Gestor'].str.strip() == my_comercial]
        for _, r in rows.iterrows():
            t = str(r['Comercial_Titular']).strip()
            if t and t != my_comercial:
                result.append(t)
    return result


# ── Parsers de archivos ───────────────────────────────────────────────────────

def load_activity_csv(path):
    for enc in ['utf-16', 'utf-16-le', 'utf-16-be']:
        try:
            df = pd.read_csv(path, sep='\t', encoding=enc, dtype=str)
            break
        except Exception:
            continue
    else:
        raise ValueError("No se pudo leer el CSV de actividad.")
    df.columns = [c.strip() for c in df.columns]
    if 'Cliente' in df.columns and 'Clientes' not in df.columns:
        df = df.rename(columns={'Cliente': 'Clientes'})
    for c in ['Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']:
        if c in df.columns:
            df[c] = df[c].apply(_parse_es_number)
    for c in ['Planta', 'Actividad', 'SAP', 'Clientes', 'Comercial']:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    return df


def load_market_excel(path):
    df = pd.read_excel(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    if 'Clientes' not in df.columns or 'Mercado' not in df.columns:
        raise ValueError("El archivo de mercado debe tener columnas 'Clientes' y 'Mercado'.")
    df['SAP']     = df['Clientes'].apply(_extract_sap)
    df['Mercado'] = df['Mercado'].astype(str).str.strip()
    return (df.dropna(subset=['SAP'])
              .drop_duplicates(subset=['SAP'])
              .set_index('SAP')['Mercado']
              .to_dict())


def load_and_merge(activity_path, market_path):
    df      = load_activity_csv(activity_path)
    sap_map = load_market_excel(market_path)
    df['Mercado'] = df['SAP'].map(sap_map).fillna('Sin asignar')
    priority = ['Planta', 'Actividad', 'Mercado', 'SAP', 'Clientes', 'Comercial',
                'Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']
    df = df[[c for c in priority if c in df.columns]]
    return recalc(df)


# ── Recálculo ─────────────────────────────────────────────────────────────────

def recalc(df):
    df = df.copy()
    for c in ['Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    if all(c in df.columns for c in ['Actual', 'Actual LY', 'Qty LY']):
        price = df['Actual LY'] / df['Qty LY'].replace(0, float('nan'))
        df['Qty Actual'] = (df['Actual'] / price).fillna(0).round(2)
    if all(c in df.columns for c in ['Actual', 'Actual LY']):
        df['Dif % 2026 vs 2025'] = (
            (df['Actual'] - df['Actual LY']) /
            df['Actual LY'].replace(0, float('nan')) * 100
        ).fillna(0).round(1)
    if all(c in df.columns for c in ['Budget', 'Actual LY']):
        df['Dif % Budget vs 2025'] = (
            (df['Budget'] - df['Actual LY']) /
            df['Actual LY'].replace(0, float('nan')) * 100
        ).fillna(0).round(1)
    return df
