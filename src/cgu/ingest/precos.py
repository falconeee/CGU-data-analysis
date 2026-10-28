"""Preços de referência: módulo de pesquisa de preços da API de dados abertos do Compras.gov.br.

Para cada código de item (CATMAT/CATSER) e UF, calcula mediana e quartis do preço unitário
por ano. Sem resultado, o detector de sobrepreço usa a distribuição interna dos itens.
"""

from __future__ import annotations

import pandas as pd

from cgu.ingest.http import ApiClient

BASE = "https://dadosabertos.compras.gov.br"
MAX_PAGES = 10  # até 5 mil observações por item/UF bastam para mediana e quartis


def fetch_precos(c: ApiClient, item_code: str, material: bool, uf: str) -> list[dict]:
    if material:
        path = "modulo-pesquisa-preco/1_consultarMaterial"
        params = {"tipo": "codigoItemCatalogo", "codigo": item_code}
    else:
        path = "modulo-pesquisa-preco/3_consultarServico"
        params = {"codigoItemCatalogo": item_code}
    out = []
    for page in range(1, MAX_PAGES + 1):
        data = c.get_json(path, {**params, "estado": uf, "pagina": page, "tamanhoPagina": 500})
        rows = (data or {}).get("resultado") or []
        out += [
            {
                "item_code": str(item_code),
                "uf": r.get("estado") or uf,
                "date": r.get("dataCompra") or r.get("dataResultado"),
                "price": r.get("precoUnitario"),
            }
            for r in rows
        ]
        if len(rows) < 500:
            break
    return out


def summarize(obs: pd.DataFrame) -> pd.DataFrame:
    """Observações (item_code, uf, date, price) -> ref_price canônico."""
    cols = ["item_code", "uf", "year", "median", "q1", "q3", "n_obs"]
    obs = obs.dropna(subset=["price", "date"])
    obs = obs[obs["price"] > 0]
    if obs.empty:
        return pd.DataFrame(columns=cols)
    obs = obs.assign(year=pd.to_datetime(obs["date"]).dt.year)
    g = obs.groupby(["item_code", "uf", "year"])["price"]
    out = pd.DataFrame(
        {
            "median": g.median(),
            "q1": g.quantile(0.25),
            "q3": g.quantile(0.75),
            "n_obs": g.size(),
        }
    ).reset_index()
    return out[cols]
