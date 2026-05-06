import pandas as pd
import re
import os

DATA_DIR = "datos"
FORECAST_FILE    = os.path.join(DATA_DIR, "forecast_actual.xlsx")
ACTIVITY_FILE    = os.path.join(DATA_DIR, "_upload_actividad.csv")
MARKET_FILE      = os.path.join(DATA_DIR, "_upload_mercado.xlsx")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_es_number(val):
    """Convert Spanish-format number strings to float.
    Handles: '1.357,82', '19,50 €', ' -   ', ' -   € ', numbers as-is.
    """
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s or re.match(r'^\s*-\s*€?\s*$', s) or s in ('-', '—'):
        return 0.0
    s = s.replace('€', '').replace(' ', '')
    # Spanish: dot = thousands, comma = decimal
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _extract_sap(client_str):
    """Extract SAP code from strings like '777337 - FRUTAS ALDAMA, S.L.'"""
    if not client_str:
        return None
    m = re.match(r'^\s*(\d+)', str(client_str).strip())
    return m.group(1) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_activity_csv(path):
    """Load the V2 activity CSV (UTF-16, tab-separated, Spanish numbers).
    Columns: Planta | Actividad | SAP | Cliente | Comercial |
             Qty LY | Actual LY | Qty Budget | Budget | Qty Actual | Actual
    """
    for enc in ['utf-16', 'utf-16-le', 'utf-16-be']:
        try:
            df = pd.read_csv(path, sep='\t', encoding=enc, dtype=str)
            break
        except Exception:
            continue
    else:
        raise ValueError(f"No se pudo leer el CSV de actividad: {path}")

    df.columns = [c.strip() for c in df.columns]

    # Normalise column name Cliente → Clientes
    if 'Cliente' in df.columns and 'Clientes' not in df.columns:
        df = df.rename(columns={'Cliente': 'Clientes'})

    # Parse numeric columns
    for c in ['Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']:
        if c in df.columns:
            df[c] = df[c].apply(_parse_es_number)

    # Strip string columns
    for c in ['Planta', 'Actividad', 'SAP', 'Clientes', 'Comercial']:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    return df


def load_market_excel(path):
    """Load the market Excel file.
    Columns: Planta | Comercial | Mercado | Clientes | Qty LY | Actual LY | ...
    SAP is extracted from the Clientes prefix ('777337 - FRUTAS ALDAMA').
    Returns a mapping dict: SAP (str) -> Mercado (str)
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    if 'Clientes' not in df.columns:
        raise ValueError("El archivo de mercado no tiene columna 'Clientes'.")
    if 'Mercado' not in df.columns:
        raise ValueError("El archivo de mercado no tiene columna 'Mercado'.")

    df['SAP'] = df['Clientes'].apply(_extract_sap)
    df['Mercado'] = df['Mercado'].astype(str).str.strip()

    # Build SAP → Mercado map (one market per SAP; first occurrence wins)
    sap_map = (
        df.dropna(subset=['SAP'])
          .drop_duplicates(subset=['SAP'])
          .set_index('SAP')['Mercado']
          .to_dict()
    )
    return sap_map


def load_and_merge(activity_path, market_path):
    """Load both files and join Mercado into the activity DataFrame via SAP.
    Returns the enriched DataFrame ready to save as forecast_actual.xlsx.
    """
    df = load_activity_csv(activity_path)
    sap_map = load_market_excel(market_path)

    # Join Mercado by SAP
    df['Mercado'] = df['SAP'].map(sap_map).fillna('Sin asignar')

    # Reorder columns: put Mercado after Actividad
    priority = ['Planta', 'Actividad', 'Mercado', 'SAP', 'Clientes', 'Comercial',
                'Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']
    existing = [c for c in priority if c in df.columns]
    rest = [c for c in df.columns if c not in existing]
    df = df[existing + rest]

    return recalc(df)


# ─────────────────────────────────────────────────────────────────────────────
# Recalculate derived columns
# ─────────────────────────────────────────────────────────────────────────────

def recalc(df):
    """
    Recalculate:
      Qty Actual  = Actual(€) × Qty LY / Actual LY   (LY €/Tn ratio)
      Dif % 2026 vs 2025   = (Actual - Actual LY) / Actual LY × 100
      Dif Qty 2026 vs 2025 = Qty Actual - Qty LY
      Dif % Budget vs 2025 = (Budget - Actual LY) / Actual LY × 100
      Dif Qty Budget vs 2025 = Qty Budget - Qty LY
    """
    df = df.copy()
    num_cols = ['Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    if all(c in df.columns for c in ['Actual', 'Actual LY', 'Qty LY']):
        price_per_ton = df['Actual LY'] / df['Qty LY'].replace(0, float('nan'))
        df['Qty Actual'] = (df['Actual'] / price_per_ton).fillna(0).round(2)

    if all(c in df.columns for c in ['Actual', 'Actual LY']):
        df['Dif % 2026 vs 2025'] = (
            (df['Actual'] - df['Actual LY']) /
            df['Actual LY'].replace(0, float('nan')) * 100
        ).fillna(0).round(1)

    if all(c in df.columns for c in ['Qty Actual', 'Qty LY']):
        df['Dif Qty 2026 vs 2025'] = (df['Qty Actual'] - df['Qty LY']).round(2)

    if all(c in df.columns for c in ['Budget', 'Actual LY']):
        df['Dif % Budget vs 2025'] = (
            (df['Budget'] - df['Actual LY']) /
            df['Actual LY'].replace(0, float('nan')) * 100
        ).fillna(0).round(1)

    if all(c in df.columns for c in ['Qty Budget', 'Qty LY']):
        df['Dif Qty Budget vs 2025'] = (df['Qty Budget'] - df['Qty LY']).round(2)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

def load_forecast():
    if os.path.exists(FORECAST_FILE):
        try:
            return pd.read_excel(FORECAST_FILE)
        except Exception:
            pass
    return pd.DataFrame()


def save_forecast(df):
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_excel(FORECAST_FILE, index=False, engine='openpyxl')


def delete_forecast():
    if os.path.exists(FORECAST_FILE):
        os.remove(FORECAST_FILE)
