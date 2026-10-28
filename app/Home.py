"""Entrada do dashboard: `uv run streamlit run app/Home.py`."""

import streamlit as st

st.set_page_config(page_title="CGU · Risco em contratações", page_icon="🏛️", layout="wide")

st.navigation(
    [
        st.Page(
            "pages/0_Visao_geral.py", title="Visão geral", icon=":material/dashboard:", default=True
        ),
        st.Page("pages/1_Busca.py", url_path="busca", title="Busca", icon=":material/search:"),
        st.Page(
            "pages/2_Contrato.py",
            url_path="contrato",
            title="Contrato",
            icon=":material/description:",
        ),
        st.Page(
            "pages/3_Rede.py", url_path="rede", title="Rede de fornecedores", icon=":material/hub:"
        ),
        st.Page(
            "pages/4_Benford.py",
            url_path="benford",
            title="Lei de Benford",
            icon=":material/bar_chart:",
        ),
        st.Page(
            "pages/5_Sobrepreco.py",
            url_path="sobrepreco",
            title="Sobrepreço",
            icon=":material/paid:",
        ),
        st.Page(
            "pages/6_Validacao.py",
            url_path="validacao",
            title="Validação",
            icon=":material/verified:",
        ),
    ]
).run()
