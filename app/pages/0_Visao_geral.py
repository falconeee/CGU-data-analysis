"""Visão geral: KPIs, ranking de órgãos e contratos por risco."""

import plotly.graph_objects as go
import streamlit as st

import common as c

c.page("Visão geral — risco em contratações públicas", "🏛️")

kpi = c.query("""
    SELECT count(*) AS n, sum(value_final) AS total,
           avg(CASE WHEN n_flags > 0 THEN 1.0 ELSE 0 END) AS share_flag,
           count(*) FILTER (WHERE risk >= 0.5) AS n_high,
           sum(value_at_risk) AS var
    FROM contract_score
""").iloc[0]
cols = st.columns(5)
cols[0].metric("Contratos", f"{int(kpi.n):,}".replace(",", "."))
cols[1].metric("Valor contratado", c.brl_short(kpi.total))
cols[2].metric("Com algum indício", c.pct(kpi.share_flag))
cols[3].metric("Risco alto (≥ 0,5)", f"{int(kpi.n_high):,}".replace(",", "."))
cols[4].metric(
    "Valor ponderado pelo risco",
    c.brl_short(kpi["var"]),
    help="Σ valor do contrato × risco: aproxima quanto do gasto está sob suspeita.",
)

left, right = st.columns(2)
with left:
    st.subheader("Órgãos com maior valor em risco")
    ag = c.query("""SELECT agency_name, value_at_risk, mean_risk, n_contracts, n_high_risk
                    FROM agency_score ORDER BY value_at_risk DESC LIMIT 10""")
    ag = ag.iloc[::-1]
    fig = go.Figure(
        go.Bar(
            x=ag["value_at_risk"],
            y=ag["agency_name"],
            orientation="h",
            marker={"color": c.SERIES[0], "cornerradius": 4},
            customdata=ag[["mean_risk", "n_contracts", "n_high_risk"]],
            hovertemplate="<b>%{y}</b><br>Valor em risco: R$ %{x:,.0f}<br>Risco médio: "
            "%{customdata[0]:.2f}<br>Contratos: %{customdata[1]} "
            "(%{customdata[2]} de risco alto)<extra></extra>",
        )
    )
    c.chart(c.style(fig, 400, xaxis_title="Valor ponderado pelo risco (R$)"))

with right:
    st.subheader("Contratos sinalizados por indício")
    det = c.query("""SELECT detector, count(DISTINCT contract_id) AS n FROM flags
                     WHERE flag GROUP BY detector ORDER BY n""")
    det["label"] = det["detector"].map(c.detector_label)
    fig = go.Figure(
        go.Bar(
            x=det["n"],
            y=det["label"],
            orientation="h",
            text=det["n"],
            textposition="outside",
            marker={"color": c.SERIES[0], "cornerradius": 4},
            textfont={"color": c.INK_2},
            hovertemplate="<b>%{y}</b><br>%{x} contratos<extra></extra>",
        )
    )
    c.chart(c.style(fig, 400, xaxis_title="Contratos", xaxis_range=[0, det["n"].max() * 1.15]))

st.subheader("Distribuição do risco")
dist = c.query("SELECT risk FROM contract_score WHERE n_flags > 0")
fig = go.Figure(
    go.Histogram(
        x=dist["risk"],
        xbins={"start": 0, "end": 1, "size": 0.05},
        marker={"color": c.SERIES[0], "line": {"color": c.SURFACE, "width": 2}},
        hovertemplate="Risco %{x}<br>%{y} contratos<extra></extra>",
    )
)
c.chart(
    c.style(
        fig, 260, xaxis_title="Risco (contratos com ao menos um indício)", yaxis_title="Contratos"
    )
)
st.caption(
    f"{int(kpi.n) - len(dist):,} contratos sem nenhum indício (risco 0) "
    "foram omitidos do histograma.".replace(",", ".")
)

st.subheader("Contratos de maior risco")
top = c.query("""
    SELECT contract_id, agency_name, supplier_name, cnpj, modality, signed_at, value_final,
           risk, n_flags, flags
    FROM contract_score ORDER BY risk DESC, value_final DESC LIMIT 50
""")
top["flags"] = top["flags"].map(c.flags_label)
top["modality"] = top["modality"].map(c.MODALITY_LABELS)
sel = st.dataframe(
    top,
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "contract_id": "Contrato",
        "agency_name": "Órgão",
        "supplier_name": "Fornecedor",
        "cnpj": "CNPJ",
        "modality": "Modalidade",
        "signed_at": st.column_config.DateColumn("Assinatura", format="DD/MM/YYYY"),
        "value_final": st.column_config.NumberColumn("Valor final (R$)", format="%.2f"),
        "risk": st.column_config.ProgressColumn("Risco", min_value=0, max_value=1, format="%.2f"),
        "n_flags": "Nº indícios",
        "flags": "Indícios",
    },
)
rows = sel.selection.rows
c.open_contract_button(top.iloc[rows[0]]["contract_id"] if rows else None, "home_open")
if not rows:
    st.caption("Selecione uma linha para abrir o detalhe do contrato.")
