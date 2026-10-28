"""Utilitários compartilhados pelas páginas do dashboard."""

from __future__ import annotations

import json

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cgu.config import load_config
from cgu.scoring.score import DETECTOR_LABELS

CFG = load_config()

# Paleta (validada com o validador da skill de dataviz: slots 1-3, modo claro).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
CRITICAL = "#d03b3b"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

MODALITY_LABELS = {
    "pregao": "Pregão",
    "concorrencia": "Concorrência",
    "dispensa": "Dispensa",
    "inexigibilidade": "Inexigibilidade",
    "outra": "Outra",
}


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    return _query(sql, tuple(params or ()))


@st.cache_data(show_spinner=False, ttl=300)
def _query(sql: str, params: tuple) -> pd.DataFrame:
    con = duckdb.connect(str(CFG.warehouse), read_only=True)
    try:
        return con.execute(sql, list(params)).df()
    finally:
        con.close()


def has_data() -> bool:
    if not CFG.warehouse.exists():
        return False
    t = query("SELECT table_name FROM information_schema.tables")["table_name"]
    return "contract_score" in set(t)


def meta() -> dict[str, str]:
    df = query("SELECT key, value FROM meta")
    return dict(zip(df["key"], df["value"], strict=True))


def page(title: str, icon: str = "🔎") -> None:
    st.set_page_config(page_title=f"{title} · CGU", page_icon=icon, layout="wide")
    if not has_data():
        st.title(title)
        st.error(
            "Nenhum dado encontrado. Rode `uv run cgu all` para gerar a base sintética "
            "e calcular os indícios."
        )
        st.stop()
    m = meta()
    with st.sidebar:
        if m.get("source") == "synthetic":
            st.warning(
                "**Dados sintéticos**: órgãos, empresas e pessoas são fictícios, "
                "com fraudes plantadas para demonstração.",
                icon="🧪",
            )
        else:
            st.info(
                f"**Dados reais**: {m.get('uf', '')} · {m.get('start', '')} a {m.get('end', '')}",
                icon="🏛️",
            )
        st.caption(f"Gerado em {m.get('generated_at', '?')}")
        st.caption(
            "Os scores são **indícios** para priorizar análise, não prova de irregularidade."
        )
    st.title(title)


def brl(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "—"
    s = f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {s}"


def brl_short(v: float) -> str:
    for div, suf in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(v) >= div:
            return f"R$ {v / div:.1f} {suf}".replace(".", ",")
    return brl(v)


def pct(v: float | None, digits: int = 1) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.{digits}f}%".replace(".", ",")


def detector_label(d: str) -> str:
    return DETECTOR_LABELS.get(d, d)


def flags_label(s: str) -> str:
    return ", ".join(detector_label(d.strip()) for d in s.split(",") if d.strip()) if s else ""


def parse_json(s: str | None):
    return json.loads(s) if s else None


def style(fig: go.Figure, height: int = 360, **layout) -> go.Figure:
    """Tema do projeto: superfície clara, grade discreta, tipografia do sistema."""
    fig.update_layout(
        height=height,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": FONT, "color": INK_2, "size": 13},
        margin={"l": 10, "r": 30, "t": 30, "b": 10},
        hoverlabel={"bgcolor": "#ffffff", "font": {"color": INK, "family": FONT}},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "font": {"color": INK_2},
        },
        bargap=0.25,
        **layout,
    )
    axis = {
        "gridcolor": GRID,
        "linecolor": AXIS,
        "zerolinecolor": AXIS,
        "automargin": True,
        "tickfont": {"color": MUTED},
        "title": {"standoff": 12},
    }
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, config={"displaylogo": False})


def open_contract_button(contract_id: str | None, key: str) -> None:
    if contract_id and st.button(f"Abrir contrato {contract_id}", key=key, type="primary"):
        st.session_state["contract_id"] = contract_id
        st.switch_page("pages/2_Contrato.py")
