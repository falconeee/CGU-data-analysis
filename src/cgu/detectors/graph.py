"""Grafo de fornecedores e detecção de comunidades (Louvain) para possíveis cartéis.

Nós são fornecedores que participaram de licitações. Arestas ligam empresas que disputaram
as mesmas licitações (peso = nº de co-participações) e recebem um bônus por sócio em comum.
Arestas fracas são podadas antes do Louvain; cada comunidade recebe métricas de conluio:
- coesão: fração das licitações com algum membro em que >= 2 membros disputaram;
- rodízio: fração dos membros que venceram ao menos uma dessas disputas conjuntas;
- sócios em comum entre membros.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd

from cgu import db
from cgu.config import Config
from cgu.detectors.common import flags_frame, to_json

CO_BID_SQL = """
SELECT a.cnpj AS src, b.cnpj AS dst, count(*) AS co_bids
FROM bidder a JOIN bidder b ON a.tender_id = b.tender_id AND a.cnpj < b.cnpj
GROUP BY ALL
"""

SHARED_PARTNER_SQL = """
WITH bidders AS (SELECT DISTINCT cnpj, substr(cnpj, 1, 8) AS base FROM bidder),
p AS (
    SELECT b.cnpj, pa.partner_name, pa.partner_doc
    FROM bidders b JOIN partner pa ON pa.cnpj_base = b.base
)
SELECT p1.cnpj AS src, p2.cnpj AS dst, count(*) AS shared_partners,
       string_agg(DISTINCT p1.partner_name, '; ') AS partner_names
FROM p p1 JOIN p p2
  ON p1.partner_name = p2.partner_name
 AND p1.partner_doc IS NOT DISTINCT FROM p2.partner_doc
 AND p1.cnpj < p2.cnpj
GROUP BY ALL
UNION ALL
SELECT a.cnpj, b.cnpj, 1, 'mesmo CNPJ básico'
FROM bidders a JOIN bidders b ON a.base = b.base AND a.cnpj < b.cnpj
"""


def build_edges(con, cfg: Config) -> pd.DataFrame:
    p = cfg["detectors"]["graph"]
    co = db.read(con, CO_BID_SQL)
    sp = db.read(con, SHARED_PARTNER_SQL)
    sp = sp.groupby(["src", "dst"], as_index=False).agg(
        shared_partners=("shared_partners", "sum"),
        partner_names=("partner_names", lambda s: "; ".join(sorted(set(s)))),
    )
    edges = co.merge(sp, on=["src", "dst"], how="outer")
    edges["co_bids"] = edges["co_bids"].fillna(0).astype(int)
    edges["shared_partners"] = edges["shared_partners"].fillna(0).astype(int)
    edges["weight"] = edges["co_bids"] + p["shared_partner_bonus"] * edges["shared_partners"]
    return edges


def run(con, cfg: Config) -> dict[str, pd.DataFrame]:
    p = cfg["detectors"]["graph"]
    edges = build_edges(con, cfg)
    strong = edges[edges["weight"] >= p["min_edge_weight"]].reset_index(drop=True)

    G = nx.Graph()
    for e in strong.itertuples():
        G.add_edge(e.src, e.dst, weight=float(e.weight))
    communities = (
        nx.community.louvain_communities(G, weight="weight", resolution=p["resolution"], seed=0)
        if G.number_of_edges()
        else []
    )

    bidders = db.read(con, "SELECT tender_id, cnpj, is_winner FROM bidder")
    names = db.read(con, "SELECT cnpj, name FROM supplier").set_index("cnpj")["name"]
    comm_rows, member_rows, joint_tenders = [], [], {}
    for k, members in enumerate(sorted(communities, key=len, reverse=True)):
        if len(members) < p["min_community_size"]:
            continue
        cid = f"C{k + 1:03d}"
        sub = G.subgraph(members)
        b = bidders[bidders["cnpj"].isin(members)]
        per_tender = b.groupby("tender_id")["cnpj"].nunique()
        joint = per_tender[per_tender >= 2].index
        cohesion = len(joint) / len(per_tender) if len(per_tender) else 0.0
        winners = b[b["tender_id"].isin(joint) & b["is_winner"]]["cnpj"].nunique()
        rotation = winners / len(members)
        sp_links = int(
            strong[strong["src"].isin(members) & strong["dst"].isin(members)]["shared_partners"]
            .gt(0)
            .sum()
        )
        score = cohesion * (0.6 + 0.4 * rotation) + (0.2 if sp_links else 0.0)
        flag = cohesion >= p["cohesion_threshold"] and len(joint) >= 5
        score = min(score, 1.0) if flag else min(score, 1.0) * 0.5
        comm_rows.append(
            {
                "community_id": cid,
                "size": len(members),
                "density": nx.density(sub),
                "n_tenders": len(per_tender),
                "n_joint_tenders": len(joint),
                "cohesion": cohesion,
                "rotation": rotation,
                "shared_partner_links": sp_links,
                "score": score,
                "flag": flag,
                "members": to_json(sorted(members)),
            }
        )
        for m in members:
            member_rows.append(
                {
                    "cnpj": m,
                    "name": names.get(m),
                    "community_id": cid,
                    "degree": sub.degree(m),
                    "community_score": score,
                    "community_flag": flag,
                }
            )
        if flag:
            joint_tenders[cid] = (set(members), set(joint), comm_rows[-1])

    community = pd.DataFrame(
        comm_rows,
        columns=[
            "community_id",
            "size",
            "density",
            "n_tenders",
            "n_joint_tenders",
            "cohesion",
            "rotation",
            "shared_partner_links",
            "score",
            "flag",
            "members",
        ],
    )
    members = pd.DataFrame(
        member_rows,
        columns=["cnpj", "name", "community_id", "degree", "community_score", "community_flag"],
    )

    # Contrato herda o indício quando o vencedor é membro e a licitação teve >= 2 membros.
    contracts = db.read(con, "SELECT contract_id, tender_id, cnpj FROM contract")
    rows = []
    for cid, (mem, joint, info) in joint_tenders.items():
        hit = contracts[contracts["tender_id"].isin(joint) & contracts["cnpj"].isin(mem)]
        for r in hit.itertuples():
            rivals = bidders[(bidders.tender_id == r.tender_id) & bidders.cnpj.isin(mem)]
            rows.append(
                {
                    "contract_id": r.contract_id,
                    "score": info["score"],
                    "flag": True,
                    "evidence": to_json(
                        {
                            "comunidade": cid,
                            "membros_na_licitacao": rivals["cnpj"].tolist(),
                            "tamanho": info["size"],
                            "coesao": info["cohesion"],
                            "rodizio": info["rotation"],
                            "socios_em_comum": info["shared_partner_links"],
                        }
                    ),
                }
            )
    flags = flags_frame(rows, "cartel")
    if not flags.empty:
        flags = flags.sort_values("score", ascending=False).drop_duplicates("contract_id")
    return {
        "flags": flags,
        "community": community,
        "community_member": members,
        "graph_edge": strong,
    }
