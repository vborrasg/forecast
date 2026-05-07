import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import io, os
from data import (load_forecast, save_forecast, delete_forecast,
                  load_and_merge, recalc,
                  load_users, load_delegaciones,
                  save_users_from_df, save_delegaciones_from_df)

DATA_DIR = "datos"
MIME_XL  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ACTIVITY_FILE = os.path.join(DATA_DIR, "_upload_actividad.csv")
MARKET_FILE   = os.path.join(DATA_DIR, "_upload_mercado.xlsx")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_excel(df):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine='openpyxl')
    return buf.getvalue()


def _summary(df, group_cols, key_suffix=""):
    """Generic grouped summary returning styled dataframe + raw df."""
    grp = df.groupby(group_cols).agg(
        Previsión_EUR =('Actual',    'sum'),
        Budget_EUR    =('Budget',    'sum'),
        LY_EUR        =('Actual LY', 'sum'),
        Qty_Actual_Tn =('Qty Actual','sum'),
        Qty_Budget_Tn =('Qty Budget','sum'),
    ).reset_index()
    grp['% vs Budget'] = (
        (grp['Previsión_EUR'] - grp['Budget_EUR']) /
        grp['Budget_EUR'].replace(0, float('nan')) * 100
    ).round(1).fillna(0)
    grp['% vs N-1'] = (
        (grp['Previsión_EUR'] - grp['LY_EUR']) /
        grp['LY_EUR'].replace(0, float('nan')) * 100
    ).round(1).fillna(0)

    fmt = {
        'Previsión_EUR': '{:,.0f} €', 'Budget_EUR': '{:,.0f} €',
        'LY_EUR': '{:,.0f} €', 'Qty_Actual_Tn': '{:,.1f}',
        'Qty_Budget_Tn': '{:,.1f}', '% vs Budget': '{:+.1f}%', '% vs N-1': '{:+.1f}%'
    }
    styled = grp.style.format(fmt).applymap(
        lambda v: ('color:#16a34a;font-weight:bold' if isinstance(v, float) and v >= 0
                   else 'color:#dc2626;font-weight:bold' if isinstance(v, float) and v < 0 else ''),
        subset=['% vs Budget', '% vs N-1']
    )
    return grp, styled


def _bar_chart(grp, x_col, title):
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Previsión €", x=grp[x_col], y=grp['Previsión_EUR'], marker_color="#3b82f6"))
    fig.add_trace(go.Bar(name="Budget €",    x=grp[x_col], y=grp['Budget_EUR'],    marker_color="#94a3b8"))
    fig.add_trace(go.Bar(name="N-1 €",       x=grp[x_col], y=grp['LY_EUR'],        marker_color="#f59e0b"))
    fig.update_layout(barmode="group", title=title, height=400, xaxis_tickangle=-30)
    return fig


def _summary_section(df, group_cols, title, chart_col, dl_key, dl_name, show_chart=True):
    """Render a complete summary section: table + optional chart + download."""
    st.subheader(title)
    if not all(c in df.columns for c in group_cols):
        st.info(f"Columnas necesarias no disponibles: {group_cols}")
        return
    grp, styled = _summary(df, group_cols)
    st.dataframe(styled, use_container_width=True, height=min(500, 55 + len(grp)*35))
    col1, col2 = st.columns([3, 1])
    with col2:
        st.download_button(f"📥 Descargar", _to_excel(grp),
                           file_name=dl_name, mime=MIME_XL, key=dl_key)
    if show_chart and chart_col and chart_col in grp.columns:
        st.plotly_chart(_bar_chart(grp, chart_col, title), use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main render
# ─────────────────────────────────────────────────────────────────────────────

def render_admin_tabs(session):
    df_master = load_forecast(session)
    tab_labels = ["📤 Cargar Datos", "📊 Vista Global", "✏️ Editar Datos",
                  "👥 Usuarios", "🔗 Delegaciones"]
    tabs = st.tabs(tab_labels)

    # ── TAB 0 ─ CARGAR DATOS ─────────────────────────────────────────────────
    with tabs[0]:
        st.header("📤 Cargar archivos del mes")
        st.info("""Sube **ambos archivos** cada mes:
- 📋 **Archivo de Actividad** — CSV UTF-16 con columnas: Planta, Actividad, SAP, Cliente, Comercial, Qty LY, Actual LY, Qty Budget, Budget
- 🗺️ **Archivo de Mercado** — Excel con columnas: Planta, Comercial, Mercado, Clientes (SAP en el prefijo del nombre de cliente)

La app cruza ambos por **código SAP** y genera el forecast unificado.""")

        col_a, col_m = st.columns(2)

        with col_a:
            st.subheader("📋 Archivo de Actividad (.csv)")
            f_act = st.file_uploader("Selecciona el CSV de actividad", type=["csv"], key="up_act")
            if f_act:
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(ACTIVITY_FILE, 'wb') as fh:
                    fh.write(f_act.getbuffer())
                st.success(f"✅ Guardado: {f_act.name}")

        with col_m:
            st.subheader("🗺️ Archivo de Mercado (.xlsx)")
            f_mkt = st.file_uploader("Selecciona el Excel de mercado", type=["xlsx", "xls"], key="up_mkt")
            if f_mkt:
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(MARKET_FILE, 'wb') as fh:
                    fh.write(f_mkt.getbuffer())
                st.success(f"✅ Guardado: {f_mkt.name}")

        act_ready = os.path.exists(ACTIVITY_FILE)
        mkt_ready = os.path.exists(MARKET_FILE)
        st.markdown("---")
        st.markdown(f"**Estado:** Actividad {'✅' if act_ready else '❌ pendiente'} | "
                    f"Mercado {'✅' if mkt_ready else '❌ pendiente'}")

        if act_ready and mkt_ready:
            if st.button("🔄 Procesar y generar forecast unificado", type="primary", use_container_width=True):
                try:
                    with st.spinner("Cruzando archivos por SAP..."):
                        df_merged = load_and_merge(session, ACTIVITY_FILE, MARKET_FILE)
                    # Diagnostics
                    sin_mercado = df_merged[df_merged['Mercado'] == 'Sin asignar']
                    save_forecast(session, df_merged)
                    st.success(f"✅ Forecast generado: {len(df_merged)} filas | "
                               f"{df_merged['Actividad'].nunique()} actividades | "
                               f"{df_merged['Mercado'].nunique()} mercados")
                    if len(sin_mercado) > 0:
                        st.warning(f"⚠️ {len(sin_mercado)} filas sin mercado asignado "
                                   f"(SAPs no encontrados en archivo de mercado): "
                                   f"{sin_mercado['SAP'].unique().tolist()}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al procesar: {e}")
        else:
            st.button("🔄 Procesar forecast", disabled=True,
                      help="Sube ambos archivos primero", use_container_width=True)

        # Current forecast info
        if not df_master.empty:
            st.markdown("---")
            st.subheader("📁 Forecast actual en memoria")
            has_act = 'Actividad' in df_master.columns
            has_mkt = 'Mercado' in df_master.columns
            coms    = sorted(df_master['Comercial'].dropna().unique()) if 'Comercial' in df_master.columns else []
            acts    = sorted(df_master['Actividad'].dropna().unique()) if has_act else []
            mkts    = sorted(df_master['Mercado'].dropna().unique()) if has_mkt else []

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Filas", len(df_master))
            m2.metric("Comerciales", len(coms))
            m3.metric("Actividades", len(acts))
            m4.metric("Mercados", len(mkts))

            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥 Descargar consolidado completo", _to_excel(df_master),
                                   file_name="forecast_consolidado.xlsx", mime=MIME_XL, key="dl_full")
            with c2:
                st.download_button("📥 Descargar con cálculos", _to_excel(recalc(df_master)),
                                   file_name="forecast_calculado.xlsx", mime=MIME_XL, key="dl_calc")

            st.markdown("---")
            if st.button("🗑️ Borrar forecast actual", type="secondary"):
                st.session_state["confirm_delete"] = True
            if st.session_state.get("confirm_delete"):
                st.warning("⚠️ ¿Seguro? Se eliminará el forecast cargado.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Sí, borrar", type="primary"):
                        delete_forecast(session)
                        st.session_state["confirm_delete"] = False
                        st.rerun()
                with c2:
                    if st.button("❌ Cancelar"):
                        st.session_state["confirm_delete"] = False
                        st.rerun()

    # ── TAB 1 ─ VISTA GLOBAL ─────────────────────────────────────────────────
    with tabs[1]:
        st.header("📊 Vista Global — Todos los Comerciales")
        if df_master.empty:
            st.warning("No hay datos cargados. Ve a la pestaña 'Cargar Datos'.")
        else:
            df_g = recalc(df_master)

            # KPIs globales
            t_act = df_g['Actual'].sum()
            t_bud = df_g['Budget'].sum()
            t_ly  = df_g['Actual LY'].sum()
            t_qty = df_g['Qty Actual'].sum()
            pct_b = ((t_act - t_bud) / t_bud * 100) if t_bud > 0 else 0
            pct_l = ((t_act - t_ly)  / t_ly  * 100) if t_ly  > 0 else 0

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Total Previsión €", f"{t_act:,.0f} €")
            k2.metric("Total Budget €",    f"{t_bud:,.0f} €")
            k3.metric("% vs Budget",       f"{pct_b:+.1f}%")
            k4.metric("% vs N-1",          f"{pct_l:+.1f}%", delta=f"{t_act - t_ly:,.0f} €")
            k5.metric("Qty Total (Tn)",    f"{t_qty:,.1f}")

            st.markdown("---")

            # Sub-tabs para las 6 vistas
            v_tabs = st.tabs(["👤 Comercial", "🏭 Planta", "⚙️ Actividad",
                               "🗺️ Mercado", "🏭×⚙️ Planta/Actividad", "🏭×🗺️ Planta/Mercado"])

            with v_tabs[0]:
                _summary_section(df_g, ['Comercial'], "Por Comercial",
                                 'Comercial', "dl_com", "totales_comercial.xlsx")

            with v_tabs[1]:
                _summary_section(df_g, ['Planta'], "Por Planta",
                                 'Planta', "dl_plt", "totales_planta.xlsx")

            with v_tabs[2]:
                _summary_section(df_g, ['Actividad'], "Por Actividad",
                                 'Actividad', "dl_act", "totales_actividad.xlsx")

            with v_tabs[3]:
                _summary_section(df_g, ['Mercado'], "Por Mercado",
                                 'Mercado', "dl_mkt", "totales_mercado.xlsx")

            with v_tabs[4]:
                _summary_section(df_g, ['Planta', 'Actividad'],
                                 "Por Planta × Actividad", None,
                                 "dl_pa", "totales_planta_actividad.xlsx", show_chart=False)

            with v_tabs[5]:
                _summary_section(df_g, ['Planta', 'Mercado'],
                                 "Por Planta × Mercado", None,
                                 "dl_pm", "totales_planta_mercado.xlsx", show_chart=False)

            st.markdown("---")
            with st.expander("📋 Ver detalle completo de todas las filas"):
                st.dataframe(df_g, use_container_width=True, height=400)

    # ── TAB 2 ─ EDITAR DATOS ─────────────────────────────────────────────────
    with tabs[2]:
        st.header("✏️ Editar Datos — Corrección de Previsiones")
        st.info("Solo el campo **Actual (€)** es editable. El resto se recalcula automáticamente.")

        if df_master.empty:
            st.warning("No hay datos cargados.")
        else:
            df_edit = recalc(df_master.copy())

            # Filtros
            fe1, fe2, fe3, fe4 = st.columns(4)
            with fe1:
                coms_all = sorted(df_edit['Comercial'].dropna().unique()) if 'Comercial' in df_edit.columns else []
                com_sel  = st.multiselect("Comercial", coms_all, default=coms_all, key="e_com")
            with fe2:
                pla_all  = sorted(df_edit['Planta'].dropna().unique()) if 'Planta' in df_edit.columns else []
                pla_sel  = st.multiselect("Planta", pla_all, default=pla_all, key="e_pla")
            with fe3:
                act_all  = sorted(df_edit['Actividad'].dropna().unique()) if 'Actividad' in df_edit.columns else []
                act_sel  = st.multiselect("Actividad", act_all, default=act_all, key="e_act")
            with fe4:
                mkt_all  = sorted(df_edit['Mercado'].dropna().unique()) if 'Mercado' in df_edit.columns else []
                mkt_sel  = st.multiselect("Mercado", mkt_all, default=mkt_all, key="e_mkt")

            mask = (df_edit['Comercial'].isin(com_sel) &
                    df_edit['Planta'].isin(pla_sel))
            if act_all:
                mask = mask & df_edit['Actividad'].isin(act_sel)
            if mkt_all:
                mask = mask & df_edit['Mercado'].isin(mkt_sel)

            df_show = df_edit[mask].copy()
            show_cols = [c for c in ['Planta', 'Actividad', 'Mercado', 'SAP', 'Clientes',
                                     'Comercial', 'Qty LY', 'Actual LY',
                                     'Qty Budget', 'Budget', 'Qty Actual', 'Actual']
                         if c in df_show.columns]

            st.write(f"Mostrando **{len(df_show)}** filas")

            col_cfg = {
                'Planta':     st.column_config.TextColumn("Planta",      disabled=True),
                'Actividad':  st.column_config.TextColumn("Actividad",   disabled=True),
                'Mercado':    st.column_config.TextColumn("Mercado",     disabled=True),
                'SAP':        st.column_config.TextColumn("SAP",         disabled=True),
                'Clientes':   st.column_config.TextColumn("Cliente",     disabled=True, width="large"),
                'Comercial':  st.column_config.TextColumn("Comercial",   disabled=True),
                'Qty LY':     st.column_config.NumberColumn("Qty N-1 (Tn)", disabled=True, format="%.1f"),
                'Actual LY':  st.column_config.NumberColumn("€ N-1",       disabled=True, format="%.0f €"),
                'Qty Budget': st.column_config.NumberColumn("Qty Budget (Tn)", disabled=True, format="%.1f"),
                'Budget':     st.column_config.NumberColumn("Budget (€)", disabled=True, format="%.0f €"),
                'Qty Actual': st.column_config.NumberColumn("📐 Qty Actual (Tn)", disabled=True, format="%.1f"),
                'Actual':     st.column_config.NumberColumn("✏️ Actual (€)", format="%.0f", min_value=0),
            }

            edited_admin = st.data_editor(
                df_show[show_cols],
                column_config=col_cfg,
                use_container_width=True,
                height=min(700, 55 + len(df_show) * 35),
                num_rows="fixed",
                key="admin_editor"
            )

            if st.button("💾 Guardar cambios", type="primary", use_container_width=True):
                df_updated = df_master.copy()
                for idx, row in edited_admin.iterrows():
                    df_updated.loc[idx, 'Actual'] = row['Actual']
                df_updated = recalc(df_updated)
                save_forecast(session, df_updated)
                st.success("✅ Cambios guardados")
                st.rerun()

            # ── Corrección de Mercado / Actividad faltantes ───────────────────
            st.markdown("---")
            missing_mkt = (df_edit['Mercado'].isin(['Sin asignar', '', 'nan'])
                           if 'Mercado' in df_edit.columns
                           else pd.Series(False, index=df_edit.index))
            missing_act = (df_edit['Actividad'].isin(['', 'nan', 'Sin actividad'])
                           if 'Actividad' in df_edit.columns
                           else pd.Series(False, index=df_edit.index))
            df_missing = df_edit[missing_mkt | missing_act].copy()

            if df_missing.empty:
                st.success("✅ Todos los clientes tienen Mercado y Actividad asignados.")
            else:
                with st.expander(
                    f"⚠️ {len(df_missing)} filas con Mercado o Actividad sin asignar — "
                    f"haz clic para corregir",
                    expanded=True
                ):
                    st.caption("Edita las columnas **Mercado** y **Actividad** "
                               "usando los desplegables. El resto de campos no son editables aquí.")

                    fix_cols = [c for c in ['SAP', 'Clientes', 'Comercial', 'Planta',
                                             'Actividad', 'Mercado']
                                if c in df_missing.columns]

                    known_mkts = sorted([m for m in df_edit['Mercado'].dropna().unique()
                                         if m not in ('Sin asignar', '', 'nan')]) \
                                 if 'Mercado' in df_edit.columns else []
                    known_acts = sorted([a for a in df_edit['Actividad'].dropna().unique()
                                         if a not in ('', 'nan', 'Sin actividad')]) \
                                 if 'Actividad' in df_edit.columns else []

                    fix_col_cfg = {
                        'SAP':       st.column_config.TextColumn("SAP",      disabled=True),
                        'Clientes':  st.column_config.TextColumn("Cliente",  disabled=True, width="large"),
                        'Comercial': st.column_config.TextColumn("Comercial",disabled=True),
                        'Planta':    st.column_config.TextColumn("Planta",   disabled=True),
                        'Actividad': (st.column_config.SelectboxColumn(
                                          "⚙️ Actividad", options=known_acts,
                                          help="Selecciona la actividad correcta")
                                      if known_acts
                                      else st.column_config.TextColumn("⚙️ Actividad")),
                        'Mercado':   (st.column_config.SelectboxColumn(
                                          "🗺️ Mercado", options=known_mkts,
                                          help="Selecciona el mercado correcto")
                                      if known_mkts
                                      else st.column_config.TextColumn("🗺️ Mercado")),
                    }

                    fixed_editor = st.data_editor(
                        df_missing[fix_cols],
                        column_config=fix_col_cfg,
                        use_container_width=True,
                        height=min(400, 55 + len(df_missing) * 40),
                        num_rows="fixed",
                        key="fix_editor"
                    )

                    if st.button("💾 Guardar correcciones Mercado/Actividad",
                                 type="primary", use_container_width=True, key="save_fix"):
                        df_updated = df_master.copy()
                        for idx, row in fixed_editor.iterrows():
                            if 'Mercado' in df_updated.columns:
                                df_updated.loc[idx, 'Mercado']   = row.get('Mercado', '')
                            if 'Actividad' in df_updated.columns:
                                df_updated.loc[idx, 'Actividad'] = row.get('Actividad', '')
                        df_updated = recalc(df_updated)
                        save_forecast(session, df_updated)
                        st.success("✅ Correcciones guardadas")
                        st.rerun()

    # ── TAB 3 ─ USUARIOS ─────────────────────────────────────────────────────
    with tabs[3]:
        st.header("👥 Gestión de Usuarios")
        st.info("""Sube `usuarios_forecast.xlsx` con **3 columnas**:
- **Email** | **Contraseña** | **Comercial** (exactamente como aparece en el archivo de actividad)""")

        st.subheader("📄 Plantilla de Usuarios")
        if not df_master.empty and 'Comercial' in df_master.columns:
            coms_fc = sorted(df_master['Comercial'].dropna().unique())
            tmpl_u = pd.DataFrame({
                'Email':      [f"{c.split()[-1].lower()}@empresa.com" for c in coms_fc],
                'Contraseña': ['Cambia1234'] * len(coms_fc),
                'Comercial':  coms_fc
            })
        else:
            tmpl_u = pd.DataFrame({
                'Email':      ['jalonso@empresa.com', 'cgallardo@empresa.com'],
                'Contraseña': ['Clave123', 'Clave456'],
                'Comercial':  ['ALONSO Jesus', 'GALLARDO Carlos']
            })
        buf_u = io.BytesIO()
        tmpl_u.to_excel(buf_u, index=False, engine='openpyxl')
        st.download_button("📥 Descargar plantilla usuarios_forecast.xlsx",
                           buf_u.getvalue(), file_name="usuarios_forecast.xlsx",
                           mime=MIME_XL)
        if not df_master.empty:
            st.caption("⚠️ Plantilla generada con los comerciales del forecast cargado.")

        st.markdown("---")
        st.subheader("📤 Subir archivo de usuarios")
        u_file = st.file_uploader("usuarios_forecast.xlsx", type=["xlsx"], key="usr_upload")
        if u_file:
            try:
                df_u = pd.read_excel(u_file)
                save_users_from_df(session, df_u)
                st.success("✅ Usuarios actualizados en Snowflake")
                st.rerun()
            except Exception as e:
                st.error(f"Error al cargar usuarios: {e}")

        st.markdown("---")
        users  = load_users(session)
        u_data = [{"Email": k, "Comercial": v["comercial"],
                   "Rol": v["role"], "Contraseña": "••••••"}
                  for k, v in users.items()]
        st.subheader("Usuarios registrados")
        st.dataframe(pd.DataFrame(u_data), use_container_width=True)

        if not df_master.empty and 'Comercial' in df_master.columns:
            st.subheader("Validación Comerciales ↔ Usuarios")
            mapped = {v["comercial"] for v in users.values()}
            for c in sorted(df_master['Comercial'].dropna().unique()):
                icon = "✅" if c in mapped else "⚠️ Sin usuario"
                st.write(f"- **{c}** → {icon}")

    # ── TAB 4 ─ DELEGACIONES ─────────────────────────────────────────────────
    with tabs[4]:
        st.header("🔗 Tabla de Delegaciones")
        st.info("""El **Gestor** verá y editará también los clientes del **Titular** (baja/ausencia).
Archivo con 2 columnas: **Comercial_Titular** | **Comercial_Gestor**""")

        st.subheader("📄 Plantilla de Delegaciones")
        if not df_master.empty and 'Comercial' in df_master.columns:
            coms_l = sorted(df_master['Comercial'].dropna().unique())
            ex_t = coms_l[0] if coms_l else "GALLARDO Carlos"
            ex_g = coms_l[1] if len(coms_l) > 1 else "ALONSO Jesus"
        else:
            ex_t, ex_g = "GALLARDO Carlos", "ALONSO Jesus"
        tmpl_d = pd.DataFrame({'Comercial_Titular': [ex_t], 'Comercial_Gestor': [ex_g]})
        buf_d = io.BytesIO()
        tmpl_d.to_excel(buf_d, index=False, engine='openpyxl')
        st.download_button("📥 Descargar plantilla delegaciones_forecast.xlsx",
                           buf_d.getvalue(), file_name="delegaciones_forecast.xlsx",
                           mime=MIME_XL)
        st.caption("⚠️ Añade una fila por cada sustitución activa.")

        st.markdown("---")
        st.subheader("📤 Subir tabla de delegaciones")
        del_file = st.file_uploader("delegaciones_forecast.xlsx", type=["xlsx"], key="del_upload")
        if del_file:
            try:
                df_d = pd.read_excel(del_file)
                save_delegaciones_from_df(session, df_d)
                st.success("✅ Delegaciones actualizadas en Snowflake")
                st.rerun()
            except Exception as e:
                st.error(f"Error al cargar delegaciones: {e}")

        st.markdown("---")
        df_del = load_delegaciones(session)
        if df_del.empty:
            st.info("Sin delegaciones. Cada comercial ve solo sus propios clientes.")
        else:
            st.subheader("Delegaciones activas")
            st.dataframe(df_del, use_container_width=True)
            if not df_master.empty and 'Comercial' in df_master.columns:
                all_coms = set(df_master['Comercial'].dropna().unique())
                st.markdown("**Validación:**")
                for _, r in df_del.iterrows():
                    t = str(r.get("Comercial_Titular", "")).strip()
                    g = str(r.get("Comercial_Gestor", "")).strip()
                    st.write(f"- **{g}** gestiona a **{t}** — "
                             f"Titular {'✅' if t in all_coms else '⚠️ no encontrado'} | "
                             f"Gestor {'✅' if g in all_coms else '⚠️ no encontrado'}")
