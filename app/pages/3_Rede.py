"""Rede de fornecedores: comunidades Louvain e vizinhança de um CNPJ."""

import json

import streamlit as st
from pyvis.network import Network

import common as c
from cgu import cnpj as cnpj_mod

c.page("Rede de fornecedores", "🕸️")
st.caption(
    "Empresas ligadas por disputarem as mesmas licitações (espessura = nº de "
    "co-participações) e por sócios em comum (aresta tracejada). Comunidades detectadas "
    "com Louvain sobre as ligações fortes."
)

comm = c.query("SELECT * FROM community ORDER BY flag DESC, score DESC")
names = c.query("SELECT cnpj, name FROM supplier").set_index("cnpj")["name"].to_dict()
GRAY = c.MUTED


def render(net: Network, height: int = 560) -> None:
    net.set_options(
        json.dumps(
            {
                "physics": {
                    "barnesHut": {
                        "gravitationalConstant": -12000,
                        "springLength": 220,
                        "avoidOverlap": 0.6,
                    },
                    "stabilization": {"iterations": 300},
                },
                "edges": {"scaling": {"min": 1, "max": 6}, "smooth": False},
                "interaction": {"hover": True, "tooltipDelay": 80},
                "nodes": {"font": {"face": "system-ui", "size": 13, "color": c.INK}},
            }
        )
    )
    # HTML gerado localmente pelo pyvis; tooltips do vis-network são texto puro.
    st.iframe(net.generate_html(notebook=False), height=height + 20)


def node_title(cnpj: str, extra: str = "") -> str:
    return f"{names.get(cnpj, '')}\n{cnpj_mod.fmt(cnpj)}{extra}"


tab_comm, tab_ego = st.tabs(["Comunidades", "Vizinhança de um CNPJ"])

with tab_comm:
    if comm.empty:
        st.info("Nenhuma comunidade com o tamanho mínimo foi encontrada.")
    else:
        view = comm.assign(
            situacao=comm["flag"].map({True: "⚠️ suspeita", False: "—"}),
        )[
            [
                "community_id",
                "situacao",
                "size",
                "n_joint_tenders",
                "cohesion",
                "rotation",
                "shared_partner_links",
                "score",
            ]
        ]
        st.dataframe(
            view,
            hide_index=True,
            width="stretch",
            column_config={
                "community_id": "Comunidade",
                "situacao": "Situação",
                "size": "Empresas",
                "n_joint_tenders": "Licitações conjuntas",
                "cohesion": st.column_config.NumberColumn(
                    "Coesão",
                    format="%.2f",
                    help="Fração das licitações com algum membro em que ≥ 2 membros disputaram",
                ),
                "rotation": st.column_config.NumberColumn(
                    "Rodízio",
                    format="%.2f",
                    help="Fração dos membros que venceram alguma disputa conjunta",
                ),
                "shared_partner_links": "Vínculos societários",
                "score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=1, format="%.2f"
                ),
            },
        )
        cid = st.selectbox(
            "Comunidade",
            comm["community_id"],
            format_func=lambda x: (
                f"{x} {'⚠️' if comm.set_index('community_id').at[x, 'flag'] else ''}"
            ),
        )
        members = json.loads(comm.set_index("community_id").at[cid, "members"])
        ph = ", ".join("?" * len(members))
        edges = c.query(
            f"SELECT * FROM graph_edge WHERE src IN ({ph}) AND dst IN ({ph})", members + members
        )
        wins = c.query(
            f"""SELECT cnpj, count(*) FILTER (WHERE is_winner) AS wins,
                                  count(*) AS bids
                           FROM bidder WHERE cnpj IN ({ph}) GROUP BY cnpj""",
            members,
        )
        wins = wins.set_index("cnpj")
        net = Network(
            height="560px",
            width="100%",
            bgcolor=c.SURFACE,
            font_color=c.INK,
            cdn_resources="remote",
        )
        for m in members:
            w = wins.loc[m] if m in wins.index else {"wins": 0, "bids": 0}
            net.add_node(
                m,
                label=names.get(m, m)[:28],
                color=c.SERIES[1],
                size=12 + 2 * int(w["wins"]) ** 0.5 * 3,
                title=node_title(m, f"\nVitórias: {int(w['wins'])} de {int(w['bids'])}"),
            )
        for e in edges.itertuples():
            title = f"{e.co_bids} co-participações"
            if e.shared_partners:
                title += f"\nSócio(s) em comum: {e.partner_names}"
            net.add_edge(
                e.src,
                e.dst,
                value=float(e.weight),
                title=title,
                color=c.SERIES[2] if e.shared_partners else c.AXIS,
                dashes=bool(e.shared_partners),
            )
        render(net)
        st.markdown(
            "Nó laranja = empresa da comunidade (tamanho cresce com as vitórias). "
            "Aresta verde tracejada = sócio em comum; cinza = só co-participação."
        )
        with st.expander("Ligações (tabela)"):
            st.dataframe(edges, hide_index=True, width="stretch")

with tab_ego:
    q = st.text_input("CNPJ", placeholder="ex.: Z3HOOYGW000149")
    norm = cnpj_mod.normalize(q) if q else None
    if q and not norm:
        st.error("CNPJ inválido.")
    elif norm:
        nb = c.query(
            """
            SELECT b2.cnpj, count(*) AS co_bids,
                   count(*) FILTER (WHERE b2.is_winner) AS rival_wins
            FROM bidder b1 JOIN bidder b2 ON b1.tender_id = b2.tender_id AND b1.cnpj <> b2.cnpj
            WHERE b1.cnpj = ? GROUP BY b2.cnpj ORDER BY co_bids DESC LIMIT 40
        """,
            [norm],
        )
        if nb.empty:
            st.info("Esse CNPJ não disputou licitações com outras empresas.")
        else:
            cm = c.query("SELECT cnpj, community_id, community_flag FROM community_member")
            flagged = set(cm.loc[cm["community_flag"], "cnpj"])
            sp = c.query(
                """SELECT * FROM graph_edge WHERE (src = ? OR dst = ?)
                            AND shared_partners > 0""",
                [norm, norm],
            )
            linked = {r.dst if r.src == norm else r.src: r.partner_names for r in sp.itertuples()}
            net = Network(
                height="560px",
                width="100%",
                bgcolor=c.SURFACE,
                font_color=c.INK,
                cdn_resources="remote",
            )
            net.add_node(
                norm,
                label=names.get(norm, norm)[:28],
                color=c.SERIES[0],
                size=28,
                title=node_title(norm),
            )
            for r in nb.itertuples():
                color = c.SERIES[1] if r.cnpj in flagged else GRAY
                net.add_node(
                    r.cnpj,
                    label=names.get(r.cnpj, r.cnpj)[:28],
                    color=color,
                    size=12,
                    title=node_title(r.cnpj, f"\nCo-participações: {r.co_bids}"),
                )
                shared = r.cnpj in linked
                net.add_edge(
                    norm,
                    r.cnpj,
                    value=int(r.co_bids),
                    title=f"{r.co_bids} co-participações"
                    + (f"\nSócio(s) em comum: {linked[r.cnpj]}" if shared else ""),
                    color=c.SERIES[2] if shared else c.AXIS,
                    dashes=shared,
                )
            render(net)
            st.markdown(
                "Azul = CNPJ pesquisado; laranja = membro de comunidade suspeita; "
                "cinza = demais concorrentes. Aresta verde tracejada = sócio em comum."
            )
            nb["empresa"] = nb["cnpj"].map(names)
            nb["comunidade_suspeita"] = nb["cnpj"].isin(flagged)
            nb["socio_em_comum"] = nb["cnpj"].map(linked)
            st.dataframe(nb, hide_index=True, width="stretch")
