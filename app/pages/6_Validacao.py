"""Validação do score contra sanções (CEIS/CNEP) e, no modo sintético, contra o gabarito."""

import plotly.graph_objects as go
import streamlit as st

import common as c

c.page("Validação", "✅")
st.caption(
    "As sanções do CEIS/CNEP entram só como **rótulo**, nunca como entrada dos "
    "detectores. O rótulo é imperfeito: sanção depende de fiscalização e processo, e "
    "muita fraude nunca é sancionada. Por isso as métricas são indicativas."
)

summary = c.query("SELECT * FROM validation_summary")
names = {
    "sancoes": "Sanções posteriores ao contrato (CEIS/CNEP)",
    "gabarito": "Gabarito sintético (fraudes plantadas)",
}
for r in summary.to_dict("records"):
    st.subheader(names.get(r["rotulo"], r["rotulo"]))
    m = st.columns(5)
    m[0].metric(
        "AUC",
        f"{r.get('auc', float('nan')):.3f}".replace(".", ","),
        help="Probabilidade de um contrato positivo ter risco maior que um negativo.",
    )
    m[1].metric("Taxa base", c.pct(r["taxa_base"]))
    m[2].metric("Precisão nos 50 maiores", c.pct(r.get("precision@50")))
    m[3].metric("Precisão nos 100 maiores", c.pct(r.get("precision@100")))
    lift = r.get("lift@100")
    m[4].metric(
        "Lift nos 100 maiores",
        f"{lift:.1f}×".replace(".", ",") if lift else "—",
        help="Quantas vezes a precisão supera a taxa base.",
    )

roc = c.query("SELECT * FROM validation_roc")
fig = go.Figure()
for i, (label, g) in enumerate(roc.groupby("label", sort=False)):
    fig.add_scatter(
        x=g["fpr"],
        y=g["tpr"],
        mode="lines",
        name=label,
        line={"color": c.SERIES[i % len(c.SERIES)], "width": 2},
        hovertemplate="FPR %{x:.2f} · TPR %{y:.2f}<extra>" + label + "</extra>",
    )
fig.add_scatter(
    x=[0, 1],
    y=[0, 1],
    mode="lines",
    name="Aleatório",
    line={"color": c.MUTED, "width": 1, "dash": "dot"},
    hoverinfo="skip",
)
st.subheader("Curva ROC")
c.chart(
    c.style(
        fig,
        400,
        xaxis_title="Taxa de falsos positivos",
        yaxis_title="Taxa de verdadeiros positivos",
        xaxis_range=[0, 1],
        yaxis_range=[0, 1.02],
    )
)

sc = c.query("SELECT * FROM validation_scenario")
if not sc.empty:
    st.subheader("Acerto por cenário plantado")
    sc["label"] = sc["cenario"] + " · " + sc["detector"].map(c.detector_label)
    fig = go.Figure()
    for i, (col, name) in enumerate((("recall", "Recall"), ("precisao", "Precisão"))):
        fig.add_bar(
            y=sc["label"],
            x=sc[col],
            name=name,
            orientation="h",
            marker={"color": c.SERIES[i], "cornerradius": 4},
            hovertemplate="%{y}<br>" + name + ": %{x:.0%}<extra></extra>",
        )
    c.chart(
        c.style(
            fig,
            120 + 45 * len(sc),
            barmode="group",
            xaxis={"tickformat": ".0%", "range": [0, 1.05]},
            yaxis={"autorange": "reversed"},
        )
    )
    st.dataframe(
        sc.drop(columns="label"),
        hide_index=True,
        width="stretch",
        column_config={
            "recall": st.column_config.NumberColumn("Recall", format="%.2f"),
            "precisao": st.column_config.NumberColumn("Precisão", format="%.2f"),
        },
    )
    st.caption(
        "Os cenários sintéticos são mais 'limpos' que a realidade; estas métricas "
        "mostram que cada detector encontra o padrão que deveria, não o desempenho "
        "esperado em dados reais."
    )

st.subheader("Cada indício vs sanções")
det = c.query("SELECT * FROM validation_detector ORDER BY lift DESC NULLS LAST")
det["detector"] = det["detector"].map(c.detector_label)
st.dataframe(
    det,
    hide_index=True,
    width="stretch",
    column_config={
        "detector": "Indício",
        "contratos": "Contratos sinalizados",
        "taxa_sancao_com_flag": st.column_config.NumberColumn(
            "Taxa de sanção (com)", format="%.3f"
        ),
        "taxa_sancao_sem_flag": st.column_config.NumberColumn(
            "Taxa de sanção (sem)", format="%.3f"
        ),
        "lift": st.column_config.NumberColumn("Lift", format="%.1f×"),
    },
)
