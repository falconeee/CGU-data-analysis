"""Busca por CNPJ, razão social, contrato ou órgão, com filtros."""

import pandas as pd
import streamlit as st

import common as c
from cgu import cnpj as cnpj_mod

c.page("Busca", "🔎")

bounds = c.query("SELECT min(signed_at) AS lo, max(signed_at) AS hi FROM contract_score").iloc[0]
detectors = c.query("SELECT DISTINCT detector FROM flags ORDER BY 1")["detector"].tolist()

q = st.text_input(
    "CNPJ, razão social, nº do contrato ou órgão",
    placeholder="ex.: Z3HOOYGW000149, Construtora, CT000123, Prefeitura",
)
f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
period = f1.date_input(
    "Período de assinatura",
    (bounds.lo.date(), bounds.hi.date()),
    min_value=bounds.lo.date(),
    max_value=bounds.hi.date(),
    format="DD/MM/YYYY",
)
modalities = f2.multiselect(
    "Modalidade", list(c.MODALITY_LABELS), format_func=c.MODALITY_LABELS.get
)
risk_min = f3.slider("Risco mínimo", 0.0, 1.0, 0.0, 0.05)
flag_sel = f4.multiselect("Indício", detectors, format_func=c.detector_label)

where, params = ["1=1"], []
if q.strip():
    term = q.strip()
    norm = cnpj_mod.clean(term)
    where.append(
        "(cnpj ILIKE ? OR supplier_name ILIKE ? OR contract_id ILIKE ? "
        "OR agency_name ILIKE ? OR agency_id ILIKE ?)"
    )
    params += [f"%{norm}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%"]
if isinstance(period, tuple) and len(period) == 2:
    where.append("signed_at BETWEEN ? AND ?")
    params += [str(period[0]), str(period[1])]
if modalities:
    where.append(f"modality IN ({', '.join('?' * len(modalities))})")
    params += modalities
if risk_min > 0:
    where.append("risk >= ?")
    params.append(risk_min)
for d in flag_sel:
    where.append(f"s_{d} > 0")

res = c.query(
    f"""
    SELECT contract_id, agency_name, supplier_name, cnpj, modality, category, signed_at,
           value_final, risk, n_flags, flags
    FROM contract_score WHERE {" AND ".join(where)}
    ORDER BY risk DESC, value_final DESC LIMIT 2000
""",
    params,
)

# Resumo do fornecedor quando a busca é um CNPJ completo.
norm = cnpj_mod.normalize(q) if q.strip() else None
if norm:
    sup = c.query(
        """SELECT s.*, ss.n_contracts, ss.total_value, ss.max_risk, ss.mean_risk
                     FROM supplier s LEFT JOIN supplier_score ss USING (cnpj)
                     WHERE s.cnpj = ?""",
        [norm],
    )
    if not sup.empty:
        s = sup.iloc[0]
        st.subheader(f"{s['name']} — {cnpj_mod.fmt(s.cnpj)}")
        m = st.columns(5)
        m[0].metric("Abertura", s.opened_at.strftime("%d/%m/%Y") if pd.notna(s.opened_at) else "—")
        m[1].metric("Contratos", int(s.n_contracts or 0))
        m[2].metric("Valor total", c.brl_short(s.total_value or 0))
        m[3].metric("Risco máximo", f"{(s.max_risk or 0):.2f}")
        sanc = c.query("SELECT * FROM sanction WHERE cnpj = ?", [norm])
        m[4].metric("Sanções (CEIS/CNEP)", len(sanc))
        partners = c.query(
            "SELECT partner_name, partner_doc, joined_at FROM partner WHERE cnpj_base = ?",
            [norm[:8]],
        )
        with st.expander(f"Quadro societário ({len(partners)})"):
            st.dataframe(partners, hide_index=True, width="stretch")
        if not sanc.empty:
            with st.expander("Sanções"):
                st.dataframe(sanc, hide_index=True, width="stretch")

st.caption(
    f"{len(res)} contratos encontrados" + (" (limitado a 2.000)" if len(res) == 2000 else "")
)
res["flags"] = res["flags"].map(c.flags_label)
res["modality"] = res["modality"].map(c.MODALITY_LABELS)
sel = st.dataframe(
    res,
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
        "category": "Categoria",
        "signed_at": st.column_config.DateColumn("Assinatura", format="DD/MM/YYYY"),
        "value_final": st.column_config.NumberColumn("Valor final (R$)", format="%.2f"),
        "risk": st.column_config.ProgressColumn("Risco", min_value=0, max_value=1, format="%.2f"),
        "n_flags": "Nº indícios",
        "flags": "Indícios",
    },
)
rows = sel.selection.rows
c.open_contract_button(res.iloc[rows[0]]["contract_id"] if rows else None, "search_open")
st.download_button(
    "Baixar resultados (CSV)", res.to_csv(index=False).encode("utf-8"), "contratos.csv", "text/csv"
)
