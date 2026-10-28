"""Detalhe de um contrato: decomposição do risco e evidências de cada indício."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c
from cgu import cnpj as cnpj_mod

c.page("Detalhe do contrato", "📄")

ids = c.query("SELECT contract_id FROM contract_score ORDER BY risk DESC, contract_id")
options = ids["contract_id"].tolist()
current = st.session_state.get("contract_id") or st.query_params.get("id") or options[0]
cid = st.selectbox(
    "Contrato (ordenado por risco)",
    options,
    index=options.index(current) if current in options else 0,
)
st.session_state["contract_id"] = cid
st.query_params["id"] = cid

k = c.query(
    """SELECT cs.*, c.start_date, c.end_date, c.published_at, c.n_amendments,
                      c.value_initial AS vi, s.opened_at, s.size
               FROM contract_score cs JOIN contract c USING (contract_id)
               LEFT JOIN supplier s ON s.cnpj = cs.cnpj
               WHERE contract_id = ?""",
    [cid],
).iloc[0]

st.markdown(f"**{k.object}**")
m = st.columns(5)
m[0].metric("Risco", f"{k.risk:.2f}")
m[1].metric(
    "Valor final",
    c.brl_short(k.value_final),
    delta=(
        f"{(k.value_final / k.vi - 1) * 100:+.0f}% aditivos".replace(".", ",") if k.vi else None
    ),
    delta_color="inverse",
)
m[2].metric("Modalidade", c.MODALITY_LABELS.get(k.modality, k.modality))
m[3].metric("Assinatura", k.signed_at.strftime("%d/%m/%Y"))
m[4].metric("Aditivos", int(k.n_amendments))
st.markdown(
    f"**Órgão:** {k.agency_name} &nbsp;·&nbsp; **Fornecedor:** {k.supplier_name} "
    f"({cnpj_mod.fmt(k.cnpj)}) &nbsp;·&nbsp; **Abertura da empresa:** "
    f"{k.opened_at.strftime('%d/%m/%Y') if pd.notna(k.opened_at) else '—'}"
)

weights = c.CFG["scoring"]["weights"]
contrib = pd.DataFrame(
    [
        {
            "detector": d,
            "label": c.detector_label(d),
            "score": k[f"s_{d}"],
            "peso": w,
            "contrib": k[f"s_{d}"] * w,
        }
        for d, w in weights.items()
    ]
)
active = contrib[contrib["score"] > 0].sort_values("contrib")

left, right = st.columns([2, 3])
with left:
    st.subheader("Composição do risco")
    if active.empty:
        st.success("Nenhum indício para este contrato.", icon="✅")
    else:
        fig = go.Figure(
            go.Bar(
                x=active["contrib"],
                y=active["label"],
                orientation="h",
                marker={"color": c.SERIES[0], "cornerradius": 4},
                text=[f"{v:.2f}".replace(".", ",") for v in active["contrib"]],
                textposition="outside",
                textfont={"color": c.INK_2},
                customdata=active[["score", "peso"]],
                hovertemplate="<b>%{y}</b><br>score %{customdata[0]:.2f} × peso "
                "%{customdata[1]:.2f} = %{x:.2f}<extra></extra>",
            )
        )
        c.chart(
            c.style(fig, 80 + 50 * len(active), xaxis_range=[0, 1.1], xaxis_title="peso × score")
        )
        st.caption(
            "Risco = 1 − ∏(1 − peso × score). Indícios independentes se acumulam sem passar de 1."
        )


def describe(detector: str, ev: dict) -> list[str]:
    """Texto legível da evidência de cada detector."""
    if detector == "shared_partners":
        by_link: dict[str, set[str]] = {}
        for p in ev["pares"]:
            by_link.setdefault(p["vinculo"], set()).update((p["empresa_a"], p["empresa_b"]))
        return [
            f"**{link}** liga {len(cos)} concorrentes da licitação {ev['licitacao']}: "
            + ", ".join(sorted(cos))
            for link, cos in by_link.items()
        ]
    if detector == "cartel":
        return [
            f"Vencedor pertence à comunidade **{ev['comunidade']}** "
            f"({ev['tamanho']} empresas), coesão {c.pct(ev['coesao'])}, "
            f"rodízio {c.pct(ev['rodizio'])}, {ev['socios_em_comum']} vínculo(s) societário(s).",
            f"Membros nesta licitação: {', '.join(ev['membros_na_licitacao'])}",
        ]
    if detector == "splitting":
        return [
            f"{ev['n_dispensas']} dispensas ({ev['criterio']}) entre {ev['inicio']} e "
            f"{ev['fim']} somam **{c.brl(ev['soma'])}**, acima do limite de "
            f"{c.brl(ev['limite'])}, cada uma abaixo dele.",
            f"Contratos: {', '.join(ev['contratos'])}",
        ]
    if detector == "overprice":
        it = ev["item_mais_caro"]
        return [
            f"{ev['itens_com_sobrepreco']} item(ns) acima da referência; sobrepreço "
            f"estimado **{c.brl(ev['sobrepreco_estimado'])}**.",
            f"Item mais caro: {it['descricao']}: {c.brl(it['preco'])} vs referência "
            f"{c.brl(it['referencia'])} ({it['razao']:.1f}×, ref. {it['fonte_ref']}).",
        ]
    if detector == "single_supplier":
        return [
            f"{ev['n_contratos']} contratos com o órgão, **{c.pct(ev['participacao_no_valor'])}"
            f"** do valor contratado; {c.pct(ev['proporcao_licitante_unico'])} com "
            "licitante único."
        ]
    if detector == "new_company":
        return [
            f"Empresa aberta em {ev['abertura']}, contrato assinado em {ev['assinatura']}: "
            f"**{ev['idade_dias']} dias** de existência."
        ]
    if detector == "isolation":
        out = [f"Percentil de anomalia: **{ev['percentil_anomalia']}**."]
        out += [
            f"{d['atributo']}: {d['valor']} (mediana {d['mediana']})"
            for d in ev["principais_desvios"]
        ]
        return out
    if detector == "benford":
        return [
            f"O órgão reprova na Lei de Benford: MAD {ev['mad']:.4f} ({ev['classe']}), "
            f"p-valor {ev['p_valor']:.1e}, {ev['n_valores']} valores."
        ]
    return [str(ev)]


with right:
    st.subheader("Evidências")
    ev = c.query(
        "SELECT detector, score, evidence FROM flags WHERE contract_id = ? AND flag "
        "ORDER BY score DESC",
        [cid],
    )
    if ev.empty:
        st.caption("Sem evidências.")
    for r in ev.itertuples():
        with st.expander(f"{c.detector_label(r.detector)} (score {r.score:.2f})", expanded=True):
            for line in describe(r.detector, c.parse_json(r.evidence)):
                st.markdown("- " + line.replace("$", r"\$"))

st.subheader("Licitantes")
bid = c.query(
    """SELECT b.cnpj, s.name, b.bid_value, b.is_winner, s.opened_at,
                        cm.community_id
                 FROM bidder b LEFT JOIN supplier s USING (cnpj)
                 LEFT JOIN community_member cm USING (cnpj)
                 WHERE b.tender_id = ? ORDER BY b.bid_value""",
    [k.tender_id],
)
st.dataframe(
    bid,
    hide_index=True,
    width="stretch",
    column_config={
        "cnpj": "CNPJ",
        "name": "Empresa",
        "bid_value": st.column_config.NumberColumn("Proposta (R$)", format="%.2f"),
        "is_winner": "Vencedora",
        "opened_at": st.column_config.DateColumn("Abertura", format="DD/MM/YYYY"),
        "community_id": "Comunidade",
    },
)

st.subheader("Itens")
items = c.query(
    """SELECT i.description, i.unit, i.quantity, i.unit_price, o.ref_median,
                          o.ratio, o.flag AS sobrepreco
                   FROM item i LEFT JOIN item_overprice o USING (item_id)
                   WHERE i.contract_id = ?""",
    [cid],
)
st.dataframe(
    items,
    hide_index=True,
    width="stretch",
    column_config={
        "description": "Descrição",
        "unit": "Unidade",
        "quantity": st.column_config.NumberColumn("Quantidade", format="%.2f"),
        "unit_price": st.column_config.NumberColumn("Preço unitário (R$)", format="%.2f"),
        "ref_median": st.column_config.NumberColumn("Referência (R$)", format="%.2f"),
        "ratio": st.column_config.NumberColumn("Preço / referência", format="%.2f"),
        "sobrepreco": "Sobrepreço",
    },
)

st.subheader("Sócios do fornecedor")
partners = c.query(
    "SELECT partner_name, partner_doc, joined_at FROM partner WHERE cnpj_base = ?", [k.cnpj[:8]]
)
st.dataframe(
    partners,
    hide_index=True,
    width="stretch",
    column_config={
        "partner_name": "Nome",
        "partner_doc": "CPF (mascarado)",
        "joined_at": st.column_config.DateColumn("Entrada", format="DD/MM/YYYY"),
    },
)
