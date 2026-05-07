import pandas as pd
import re

# ── Tablas Snowflake ──────────────────────────────────────────────────────────
FORECAST_TABLE   = "FORECAST_DB.APP.FORECAST_DATA"
USUARIOS_TABLE   = "FORECAST_DB.APP.USUARIOS"
DELEGACIONES_TABLE = "FORECAST_DB.APP.DELEGACIONES"

# ── Mapeo de columnas app ↔ Snowflake ─────────────────────────────────────────
APP_TO_SF = {
    'Planta': 'PLANTA', 'Actividad': 'ACTIVIDAD', 'Mercado': 'MERCADO',
    'SAP': 'SAP', 'Clientes': 'CLIENTES', 'Comercial': 'COMERCIAL',
    'Qty LY': 'QTY_LY', 'Actual LY': 'ACTUAL_LY',
    'Qty Budget': 'QTY_BUDGET', 'Budget': 'BUDGET',
    'Qty Actual': 'QTY_ACTUAL', 'Actual': 'ACTUAL',
}
SF_TO_APP = {v: k for k, v in APP_TO_SF.items()}


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


# ── Carga y guardado de forecast ──────────────────────────────────────────────

def load_forecast(session):
    try:
        df = session.sql(f"SELECT * FROM {FORECAST_TABLE}").to_pandas()
        df = df.rename(columns=SF_TO_APP)
        return df
    except Exception:
        return pd.DataFrame()


def save_forecast(session, df):
    df_sf = df.rename(columns=APP_TO_SF)
    cols = [c for c in APP_TO_SF.values() if c in df_sf.columns]
    df_sf = df_sf[cols].copy()
    for c in ['QTY_LY', 'ACTUAL_LY', 'QTY_BUDGET', 'BUDGET', 'QTY_ACTUAL', 'ACTUAL']:
        if c in df_sf.columns:
            df_sf[c] = pd.to_numeric(df_sf[c], errors='coerce').fillna(0)
    session.sql(f"TRUNCATE TABLE {FORECAST_TABLE}").collect()
    session.write_pandas(df_sf, "FORECAST_DATA",
                         database="FORECAST_DB", schema="APP", overwrite=False)


def delete_forecast(session):
    session.sql(f"TRUNCATE TABLE {FORECAST_TABLE}").collect()


# ── Usuarios y delegaciones ───────────────────────────────────────────────────

def load_users(session):
    """Devuelve dict {email: {password, comercial, role}}"""
    try:
        df = session.sql(f"SELECT EMAIL, PASSWORD, COMERCIAL, ROL FROM {USUARIOS_TABLE}").to_pandas()
        return {
            str(r['EMAIL']).strip().lower(): {
                'password':  str(r['PASSWORD']),
                'comercial': str(r['COMERCIAL']),
                'role':      str(r['ROL'])
            }
            for _, r in df.iterrows()
        }
    except Exception:
        return {}


def save_users_from_df(session, df):
    """Carga masiva desde DataFrame con columnas Email|Contraseña|Comercial."""
    session.sql(f"TRUNCATE TABLE {USUARIOS_TABLE}").collect()
    rows = []
    for _, r in df.iterrows():
        email = str(r.iloc[0]).strip().lower()
        pwd   = str(r.iloc[1]).strip()
        com   = str(r.iloc[2]).strip() if len(df.columns) >= 3 else ''
        if email and '@' in email and email != 'nan':
            rows.append((email, pwd, com, 'comercial'))
    # Insert admin always
    rows.append(('vbrrsg@gmail.com', 'Albope5@', '__ADMIN__', 'admin'))
    for email, pwd, com, rol in rows:
        session.sql(f"""
            INSERT INTO {USUARIOS_TABLE} (EMAIL, PASSWORD, COMERCIAL, ROL)
            SELECT '{email}','{pwd}','{com}','{rol}'
            WHERE NOT EXISTS (
                SELECT 1 FROM {USUARIOS_TABLE} WHERE EMAIL='{email}')
        """).collect()


def load_delegaciones(session):
    try:
        df = session.sql(f"SELECT TITULAR, GESTOR FROM {DELEGACIONES_TABLE}").to_pandas()
        df.columns = ['Comercial_Titular', 'Comercial_Gestor']
        return df
    except Exception:
        return pd.DataFrame(columns=['Comercial_Titular', 'Comercial_Gestor'])


def save_delegaciones_from_df(session, df):
    session.sql(f"TRUNCATE TABLE {DELEGACIONES_TABLE}").collect()
    for _, r in df.iterrows():
        t = str(r.iloc[0]).strip()
        g = str(r.iloc[1]).strip()
        if t and g and t != 'nan':
            session.sql(
                f"INSERT INTO {DELEGACIONES_TABLE} (TITULAR, GESTOR) VALUES ('{t}','{g}')"
            ).collect()


def get_managed_comerciales(session, my_comercial):
    result = [my_comercial]
    df_del = load_delegaciones(session)
    if not df_del.empty:
        rows = df_del[df_del['Comercial_Gestor'].str.strip() == my_comercial]
        for _, r in rows.iterrows():
            t = str(r['Comercial_Titular']).strip()
            if t and t != my_comercial:
                result.append(t)
    return result


# ── Parsers de archivos de subida ─────────────────────────────────────────────

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
    df['SAP']    = df['Clientes'].apply(_extract_sap)
    df['Mercado'] = df['Mercado'].astype(str).str.strip()
    return (df.dropna(subset=['SAP'])
              .drop_duplicates(subset=['SAP'])
              .set_index('SAP')['Mercado']
              .to_dict())


def load_and_merge(session, activity_path, market_path):
    df      = load_activity_csv(activity_path)
    sap_map = load_market_excel(market_path)
    df['Mercado'] = df['SAP'].map(sap_map).fillna('Sin asignar')
    priority = ['Planta', 'Actividad', 'Mercado', 'SAP', 'Clientes', 'Comercial',
                'Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']
    df = df[[c for c in priority if c in df.columns]]
    return recalc(df)


# ── Recálculo de columnas derivadas ──────────────────────────────────────────

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
