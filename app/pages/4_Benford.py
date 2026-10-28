"""Lei de Benford por órgão ou fornecedor."""

import json

import numpy as np
import plotly.graph_objects as go
import streamlit as st

import common as c
from cgu.detectors.benford import FIRST, SECOND

c.page("Lei de Benford", "🔢")
st.caption(
    "Em valores que se espalham por várias ordens de grandeza, o 1º dígito segue "
    "log₁₀(1 + 1/d): o '1' aparece ~30% das vezes, o '9' menos de 5%. Desvios fortes "
    "podem indicar valores fabricados ou arredondados. Também surgem quando os valores "
    "são naturalmente concentrados (ex.: um órgão que compra só um tipo de item), por "
    "isso este indício tem peso baixo no score."
)

level = st.radio(
    "Nível",
    ["agency", "supplier"],
    horizontal=True,
    format_func={"agency": "Órgão", "supplier": "Fornecedor"}.get,
)
bf = c.query(
    """
    SELECT b.*, coalesce(a.name, s.name) AS name
    FROM benford b
    LEFT JOIN agency a ON b.entity_type = 'agency' AND a.agency_id = b.entity_id
    LEFT JOIN supplier s ON b.entity_type = 'supplier' AND s.cnpj = b.entity_id
    WHERE b.entity_type = ? ORDER BY b.enough_data DESC, b.flag DESC, b.mad DESC
""",
    [level],
)
min_n = c.CFG["detectors"]["benford"]["min_n"]
only_enough = st.toggle(f"Somente com amostra suficiente (n ≥ {min_n})", value=True)
if only_enough:
    bf = bf[bf["enough_data"]]
if bf.empty:
    st.info("Nenhuma entidade com dados suficientes.")
    st.stop()

table = bf[["entity_id", "name", "n", "mad", "mad_class", "p_value", "round_share", "flag"]]
sel = st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "entity_id": "ID",
        "name": "Nome",
        "n": "Nº valores",
        "mad": st.column_config.NumberColumn("MAD (1º dígito)", format="%.4f"),
        "mad_class": "Classe (Nigrini)",
        "p_value": st.column_config.NumberColumn("p-valor (χ²)", format="%.2e"),
        "round_share": st.column_config.NumberColumn(
            "Valores redondos", format="%.2f", help="Fração múltipla de R$ 100"
        ),
        "flag": "Reprovado",
    },
)
row = bf.iloc[sel.selection.rows[0]] if sel.selection.rows else bf.iloc[0]
st.subheader(f"{row['name']}: {row['mad_class']}" + (" ⚠️ reprovado" if row["flag"] else ""))

left, right = st.columns(2)
for col, title, obs, exp, digits in (
    (left, "1º dígito", json.loads(row["observed"]), FIRST, list(range(1, 10))),
    (right, "2º dígito", json.loads(row["observed2"]), SECOND, list(range(10))),
):
    with col:
        st.markdown(f"**{title}**")
        fig = go.Figure()
        fig.add_bar(
            x=digits,
            y=obs,
            name="Observado",
            marker={"color": c.SERIES[0], "cornerradius": 4},
            hovertemplate="Dígito %{x}: %{y:.1%}<extra>Observado</extra>",
        )
        fig.add_scatter(
            x=digits,
            y=exp,
            name="Esperado (Benford)",
            mode="lines+markers",
            line={"color": c.INK_2, "width": 2, "dash": "dot"},
            marker={"size": 8, "color": c.INK_2, "line": {"color": c.SURFACE, "width": 2}},
            hovertemplate="Dígito %{x}: %{y:.1%}<extra>Esperado</extra>",
        )
        c.chart(
            c.style(
                fig,
                340,
                xaxis={"tickmode": "array", "tickvals": digits},
                yaxis={"tickformat": ".0%"},
            )
        )

with st.expander("Proporções (tabela)"):
    obs1 = json.loads(row["observed"])
    st.dataframe(
        {
            "dígito": list(range(1, 10)),
            "observado": obs1,
            "esperado": FIRST,
            "diferença": np.array(obs1) - FIRST,
        },
        hide_index=True,
    )
