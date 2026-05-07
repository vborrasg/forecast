import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import io
from data import load_forecast, save_forecast, recalc, get_managed_comerciales

MIME_XL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _to_excel(df):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine='openpyxl')
    return buf.getvalue()


def _summary_block(df, group_col, title, key_prefix, show_chart=True):
    """Render grouped summary with download."""
    if group_col not in df.columns:
        return
    st.subheader(title)
    grp = df.groupby(group_col).agg(
        Previsión=('Actual', 'sum'), Budget=('Budget', 'sum'),
        N1=('Actual LY', 'sum'), Qty_Tn=('Qty Actual', 'sum')
    ).reset_index()
    grp['% vs Budget'] = (
        (grp['Previsión'] - grp['Budget']) /
        grp['Budget'].replace(0, float('nan')) * 100
    ).round(1).fillna(0)
    grp['% vs N-1'] = (
        (grp['Previsión'] - grp['N1']) /
        grp['N1'].replace(0, float('nan')) * 100
    ).round(1).fillna(0)

    st.dataframe(grp.style.format({
        'Previsión': '{:,.0f} €', 'Budget': '{:,.0f} €', 'N1': '{:,.0f} €',
        'Qty_Tn': '{:,.1f}', '% vs Budget': '{:+.1f}%', '% vs N-1': '{:+.1f}%'
    }), use_container_width=True)

    col1, col2 = st.columns([3, 1])
    with col2:
        st.download_button("📥 Descargar", _to_excel(grp),
                           file_name=f"resumen_{group_col.lower()}_{key_prefix}.xlsx",
                           mime=MIME_XL, key=f"dl_{key_prefix}_{group_col}")
    if show_chart:
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Previsión", x=grp[group_col], y=grp['Previsión'], marker_color="#3b82f6"))
        fig.add_trace(go.Bar(name="Budget",    x=grp[group_col], y=grp['Budget'],    marker_color="#94a3b8"))
        fig.add_trace(go.Bar(name="N-1",       x=grp[group_col], y=grp['N1'],        marker_color="#f59e0b"))
        fig.update_layout(barmode="group", height=360, xaxis_tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)


def render_comercial_tabs(my_comercial):
    df_master = load_forecast()
    managed   = get_managed_comerciales(my_comercial)
    is_delegate = len(managed) > 1

    tabs = st.tabs(["📝 Mis Previsiones", "📊 Mi Resumen"])

    # ── TAB 0 ─ PREVISIONES ──────────────────────────────────────────────────
    with tabs[0]:
        others_str = ""
        if is_delegate:
            others = [c for c in managed if c != my_comercial]
            others_str = f"<br><small>También gestionas: <b>{', '.join(others)}</b></small>"

        st.markdown(f"""<div style='background:linear-gradient(135deg,#1e3a8a,#3b82f6);
            color:white;padding:20px;border-radius:12px;margin-bottom:16px'>
            <h2>📝 Previsiones — {my_comercial}</h2>
            <p>Introduce <b>Actual (€)</b> por cada línea cliente/actividad.
            <b>Qty Actual (Tn)</b> se calcula automáticamente con el ratio €/Tn del año anterior.
            {others_str}</p>
        </div>""", unsafe_allow_html=True)

        if df_master.empty:
            st.warning("⚠️ El administrador aún no ha cargado el forecast de este mes.")
            return
        if 'Comercial' not in df_master.columns:
            st.error("El archivo no tiene columna 'Comercial'.")
            return

        df_mine = df_master[df_master['Comercial'].isin(managed)].copy()
        if df_mine.empty:
            st.warning(f"No se encontraron clientes para: {', '.join(managed)}")
            st.info(f"Comerciales en el archivo: "
                    f"{', '.join(sorted(df_master['Comercial'].dropna().unique()))}")
            return

        for c in ['Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']:
            if c in df_mine.columns:
                df_mine[c] = pd.to_numeric(df_mine[c], errors='coerce').fillna(0)
        df_mine = recalc(df_mine)

        has_act = 'Actividad' in df_mine.columns
        has_mkt = 'Mercado'   in df_mine.columns

        # Info line
        info_parts = [f"**{len(df_mine)} filas**"]
        if 'Planta' in df_mine.columns:
            info_parts.append(f"Plantas: {', '.join(sorted(df_mine['Planta'].dropna().unique()))}")
        if has_act:
            info_parts.append(f"Actividades: {', '.join(sorted(df_mine['Actividad'].dropna().unique()))}")
        st.write(" | ".join(info_parts))

        # Filters
        n_filters = 2 + (1 if is_delegate else 0) + (1 if has_act else 0) + (1 if has_mkt else 0)
        filter_cols = st.columns(min(n_filters, 4))
        fi = 0
        coms_sel = managed
        if is_delegate:
            with filter_cols[fi]:
                coms_sel = st.multiselect("Comercial", managed, default=managed, key="f_com")
            fi += 1
        with filter_cols[fi]:
            pla_opts = sorted(df_mine['Planta'].dropna().unique()) if 'Planta' in df_mine.columns else []
            pla_sel  = st.multiselect("Planta", pla_opts, default=pla_opts, key="f_pla")
        fi += 1
        acts_sel = []
        if has_act:
            with filter_cols[fi]:
                act_opts = sorted(df_mine['Actividad'].dropna().unique())
                acts_sel = st.multiselect("Actividad", act_opts, default=act_opts, key="f_act")
            fi += 1
        mkts_sel = []
        if has_mkt:
            with filter_cols[fi]:
                mkt_opts = sorted(df_mine['Mercado'].dropna().unique())
                mkts_sel = st.multiselect("Mercado", mkt_opts, default=mkt_opts, key="f_mkt")

        mask = df_mine['Comercial'].isin(coms_sel)
        if pla_sel and 'Planta' in df_mine.columns:
            mask = mask & df_mine['Planta'].isin(pla_sel)
        if acts_sel and has_act:
            mask = mask & df_mine['Actividad'].isin(acts_sel)
        if mkts_sel and has_mkt:
            mask = mask & df_mine['Mercado'].isin(mkts_sel)
        df_filtered = df_mine[mask].copy()

        # Build display columns
        base_order = ['Planta', 'Actividad', 'Mercado', 'Clientes',
                      'Qty LY', 'Actual LY', 'Qty Budget', 'Budget', 'Qty Actual', 'Actual']
        if is_delegate:
            base_order.insert(0, 'Comercial')
        display_cols = [c for c in base_order if c in df_filtered.columns]

        st.markdown("##### ✏️ Edita **Actual (€)** — Qty Actual (Tn) se calcula automáticamente")

        col_cfg = {
            'Comercial':  st.column_config.TextColumn("Comercial",      disabled=True),
            'Planta':     st.column_config.TextColumn("Planta",         disabled=True),
            'Actividad':  st.column_config.TextColumn("Actividad",      disabled=True),
            'Mercado':    st.column_config.TextColumn("Mercado",        disabled=True),
            'Clientes':   st.column_config.TextColumn("Cliente",        disabled=True, width="large"),
            'Qty LY':     st.column_config.NumberColumn("Qty N-1 (Tn)",    disabled=True, format="%.1f"),
            'Actual LY':  st.column_config.NumberColumn("€ N-1",           disabled=True, format="%.0f €"),
            'Qty Budget': st.column_config.NumberColumn("Qty Budget (Tn)", disabled=True, format="%.1f"),
            'Budget':     st.column_config.NumberColumn("Budget (€)",      disabled=True, format="%.0f €"),
            'Qty Actual': st.column_config.NumberColumn("📐 Qty Actual (Tn)", disabled=True,
                                                         format="%.1f",
                                                         help="Calculado: Actual€ × QtyLY / ActualLY"),
            'Actual':     st.column_config.NumberColumn("🔵 Actual (€)", format="%.0f", min_value=0),
        }

        edited = st.data_editor(
            df_filtered[display_cols],
            column_config=col_cfg,
            use_container_width=True,
            height=min(650, 55 + len(df_filtered) * 35),
            num_rows="fixed",
            key="forecast_editor"
        )

        col_save, col_dl = st.columns(2)
        with col_save:
            if st.button("💾 Guardar previsiones", type="primary", use_container_width=True):
                df_updated = df_master.copy()
                for idx, row in edited.iterrows():
                    df_updated.loc[idx, 'Actual'] = row['Actual']
                df_updated = recalc(df_updated)
                save_forecast(df_updated)
                st.success("✅ Previsiones guardadas")
                st.rerun()
        with col_dl:
            df_dl = recalc(df_master[df_master['Comercial'].isin(managed)].copy())
            st.download_button("📥 Descargar mis datos", _to_excel(df_dl),
                               file_name=f"forecast_{my_comercial.replace(' ', '_')}.xlsx",
                               mime=MIME_XL, use_container_width=True)

        # Comparativas en tiempo real
        st.markdown("---")
        st.subheader("📊 Comparativas en Tiempo Real")
        rows_data = [(idx, row) for idx, row in edited.iterrows()
                     if float(row.get('Actual', 0) or 0) > 0]
        if not rows_data:
            st.info("Introduce valores en Actual (€) para ver las comparativas.")
        else:
            for idx, row in rows_data:
                act_eur    = float(row.get('Actual',    0) or 0)
                budget     = float(row.get('Budget',    0) or 0)
                ly         = float(row.get('Actual LY', 0) or 0)
                qty_ly     = float(row.get('Qty LY',    0) or 0)
                qty_budget = float(row.get('Qty Budget',0) or 0)
                cliente    = row.get('Clientes', '?')
                actividad  = row.get('Actividad', '')
                label      = f"{cliente}" + (f" [{actividad}]" if actividad else "")

                price_ton  = (ly / qty_ly) if qty_ly > 0 else 0
                qty_act    = (act_eur / price_ton) if price_ton > 0 else 0
                pct_b = ((act_eur - budget) / budget * 100) if budget > 0 else 0
                pct_l = ((act_eur - ly)     / ly     * 100) if ly     > 0 else 0

                icon = "🟢" if pct_b >= 0 else "🔴"
                with st.expander(f"{icon} {label}", expanded=False):
                    c1, c2, c3, c4 = st.columns(4)
                    def box(label_, val_str, ok):
                        color  = "#dcfce7" if ok else "#fef2f2"
                        border = "#16a34a" if ok else "#dc2626"
                        return (f"<div style='background:{color};border:2px solid {border};"
                                f"padding:10px;border-radius:8px;text-align:center'>"
                                f"<b>{label_}</b><br>{val_str}</div>")
                    c1.markdown(box("vs Budget (€)",    f"{pct_b:+.1f}%",           pct_b >= 0), unsafe_allow_html=True)
                    c2.markdown(box("vs N-1 (€)",       f"{pct_l:+.1f}%",           pct_l >= 0), unsafe_allow_html=True)
                    c3.markdown(box("Qty vs Budget (Tn)",f"{qty_act - qty_budget:+.1f} Tn", qty_act >= qty_budget), unsafe_allow_html=True)
                    c4.markdown(box("Qty vs N-1 (Tn)",  f"{qty_act - qty_ly:+.1f} Tn",    qty_act >= qty_ly),     unsafe_allow_html=True)

    # ── TAB 1 ─ MI RESUMEN ───────────────────────────────────────────────────
    with tabs[1]:
        st.header(f"📊 Mi Resumen — {my_comercial}")
        if df_master.empty or 'Comercial' not in df_master.columns:
            st.warning("No hay datos cargados.")
            return

        df_me = recalc(df_master[df_master['Comercial'].isin(managed)].copy())
        if df_me.empty:
            st.warning("Sin datos para tu perfil.")
            return

        t_act = df_me['Actual'].sum()
        t_bud = df_me['Budget'].sum()
        t_ly  = df_me['Actual LY'].sum()
        t_qty = df_me['Qty Actual'].sum()
        pct_b = ((t_act - t_bud) / t_bud * 100) if t_bud > 0 else 0
        pct_l = ((t_act - t_ly)  / t_ly  * 100) if t_ly  > 0 else 0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Mi Previsión €", f"{t_act:,.0f} €")
        m2.metric("Mi Budget €",    f"{t_bud:,.0f} €")
        m3.metric("% vs Budget",    f"{pct_b:+.1f}%")
        m4.metric("% vs N-1",       f"{pct_l:+.1f}%", delta=f"{t_act - t_ly:,.0f} €")
        m5.metric("Qty Total (Tn)", f"{t_qty:,.1f}")

        st.markdown("---")
        if pct_b >= 0:
            st.success(f"🟢 Tu previsión supera el Budget en **{pct_b:+.1f}%**")
        elif pct_b >= -10:
            st.warning(f"🟡 A **{pct_b:.1f}%** del Budget. ¡Casi!")
        else:
            st.error(f"🔴 **{pct_b:.1f}%** por debajo del Budget "
                     f"({t_bud - t_act:,.0f} € de diferencia)")
        if pct_l >= 0:
            st.success(f"📈 Crecimiento vs N-1: **{pct_l:+.1f}%**")
        else:
            st.error(f"📉 Caída vs N-1: **{pct_l:.1f}%**")

        st.markdown("---")
        safe_name = my_comercial.replace(' ', '_')
        _summary_block(df_me, 'Planta',    "🏭 Por Planta",    safe_name)
        if 'Actividad' in df_me.columns:
            st.markdown("---")
            _summary_block(df_me, 'Actividad', "⚙️ Por Actividad", safe_name)
        if 'Mercado' in df_me.columns:
            st.markdown("---")
            _summary_block(df_me, 'Mercado',   "🗺️ Por Mercado",   safe_name)
