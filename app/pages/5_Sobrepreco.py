"""Sobrepreço: itens com preço unitário acima da referência por item/UF/ano."""

import plotly.graph_objects as go
import streamlit as st

import common as c

c.page("Sobrepreço", "💰")
p = c.CFG["detectors"]["overprice"]
st.caption(
    f"Um item é sinalizado quando o preço unitário passa de "
    f"{p['ratio_threshold']}× a mediana de referência **e** de Q3 + {p['iqr_k']}·IQR. "
    "A referência é externa (pesquisa de preços) quando disponível; senão, a "
    "distribuição dos próprios itens do mesmo código/UF/ano."
)

kpi = c.query("""SELECT count(*) AS n, count(*) FILTER (WHERE flag) AS n_flag,
                        sum(excess_value) AS excess,
                        count(DISTINCT contract_id) FILTER (WHERE flag) AS n_contracts
                 FROM item_overprice""").iloc[0]
m = st.columns(4)
m[0].metric("Itens com referência", f"{int(kpi.n):,}".replace(",", "."))
m[1].metric("Itens sinalizados", f"{int(kpi.n_flag):,}".replace(",", "."))
m[2].metric("Contratos afetados", f"{int(kpi.n_contracts):,}".replace(",", "."))
m[3].metric(
    "Sobrepreço estimado",
    c.brl_short(kpi.excess or 0),
    help="Σ (preço − mediana de referência) × quantidade nos itens sinalizados.",
)

codes = c.query("""SELECT item_code, any_value(description) AS d, count(*) FILTER (WHERE flag) AS f
                   FROM item_overprice GROUP BY item_code ORDER BY f DESC, d""")
code = st.selectbox(
    "Item do catálogo",
    ["(todos)"] + codes["item_code"].tolist(),
    format_func=lambda x: (
        x if x == "(todos)" else f"{x} — {codes.set_index('item_code').at[x, 'd']}"
    ),
)
where, params = "", []
if code != "(todos)":
    where, params = "WHERE item_code = ?", [code]
df = c.query(f"SELECT * FROM item_overprice {where}", params)

st.subheader("Preço pago vs referência")
fig = go.Figure()
for flagged, name, color in (
    (False, "Dentro do limiar", c.SERIES[0]),
    (True, "Acima do limiar", c.SERIES[1]),
):
    d = df[df["flag"] == flagged]
    fig.add_scatter(
        x=d["ref_median"],
        y=d["unit_price"],
        mode="markers",
        name=name,
        marker={
            "color": color,
            "size": 8,
            "opacity": 0.75,
            "line": {"color": c.SURFACE, "width": 1},
        },
        customdata=d[["description", "ratio", "contract_id"]],
        hovertemplate="<b>%{customdata[0]}</b><br>Pago: R$ %{y:,.2f}<br>Referência: "
        "R$ %{x:,.2f}<br>Razão: %{customdata[1]:.2f}×<br>Contrato "
        "%{customdata[2]}<extra></extra>",
    )
lo, hi = df["ref_median"].min(), df["ref_median"].max()
fig.add_scatter(
    x=[lo, hi],
    y=[lo, hi],
    mode="lines",
    name="Preço = referência",
    line={"color": c.MUTED, "width": 1, "dash": "dot"},
    hoverinfo="skip",
)
c.chart(
    c.style(
        fig,
        440,
        xaxis={"type": "log", "title": "Mediana de referência (R$, log)"},
        yaxis={"type": "log", "title": "Preço unitário pago (R$, log)"},
    )
)

st.subheader("Itens com maior desvio")
top = df[df["flag"]].sort_values("excess_value", ascending=False).head(200)
sel = st.dataframe(
    top[
        [
            "contract_id",
            "item_code",
            "description",
            "unit",
            "quantity",
            "unit_price",
            "ref_median",
            "ratio",
            "ref_source",
            "excess_value",
        ]
    ],
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "contract_id": "Contrato",
        "item_code": "Código",
        "description": "Descrição",
        "unit": "Unidade",
        "quantity": st.column_config.NumberColumn("Qtd", format="%.0f"),
        "unit_price": st.column_config.NumberColumn("Preço (R$)", format="%.2f"),
        "ref_median": st.column_config.NumberColumn("Referência (R$)", format="%.2f"),
        "ratio": st.column_config.NumberColumn("Razão", format="%.2f×"),
        "ref_source": "Fonte da ref.",
        "excess_value": st.column_config.NumberColumn("Sobrepreço (R$)", format="%.2f"),
    },
)
rows = sel.selection.rows
c.open_contract_button(top.iloc[rows[0]]["contract_id"] if rows else None, "op_open")
