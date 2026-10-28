"""Orquestra a coleta do modo real e grava as tabelas de staging em data/raw/staging.

Ordem: PNCP (contratações, itens, contratos, resultados) -> Portal (participantes das
licitações federais) -> CEIS/CNEP -> CNPJ da Receita (se a URL estiver configurada)
-> preços de referência. Tudo passa pelo cache em disco; rodar de novo retoma de onde parou.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from cgu.config import Config
from cgu.ingest import cnpj_receita, pncp, precos, sancoes, transparencia
from cgu.ingest.http import ApiClient, ensure_free_space

# Modalidade PNCP -> código de modalidade no Portal da Transparência
PNCP_TO_PORTAL = {4: 3, 5: 3, 6: 5, 7: 5, 8: 6, 9: 7}


def _log(msg: str) -> None:
    print(f"[ingest] {msg}", flush=True)


def period(cfg: Config, sample: bool) -> tuple[date, date]:
    start = pd.Timestamp(cfg["real"]["start"]).date()
    end = pd.Timestamp(cfg["real"]["end"]).date()
    if sample:
        months = cfg["real"]["sample_months"]
        end = min(
            end, (pd.Timestamp(start) + pd.DateOffset(months=months)).date() - timedelta(days=1)
        )
    return start, end


def portal_numero(numero_compra: str | None, ano: int | None) -> str | None:
    """PNCP numeroCompra "90051" + ano 2024 -> número da licitação no Portal "900512024"."""
    if not numero_compra or not ano or not str(numero_compra).isdigit():
        return None
    return f"{int(numero_compra):05d}{ano}"


def ingest_all(cfg: Config, sample: bool = False) -> None:
    r = cfg["real"]
    raw = cfg.path("raw_dir")
    staging = raw / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    ensure_free_space(raw, r["min_free_disk_gb"])
    uf, (start, end) = r["uf"], period(cfg, sample)
    _log(f"recorte: UF={uf}, {start} a {end}" + (" (amostra)" if sample else ""))

    def save(name: str, rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
        df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        df.to_parquet(staging / f"{name}.parquet", index=False)
        _log(f"{name}: {len(df)} registros")
        return df

    # --- PNCP
    cons = ApiClient(pncp.CONSULTA, raw / "cache" / "pncp", r["pncp_rate_per_min"])
    api = ApiClient(pncp.PNCP, raw / "cache" / "pncp", r["pncp_rate_per_min"])
    compras = pd.DataFrame(pncp.fetch_compras(cons, uf, start, end))
    if r.get("orgao") and not compras.empty:
        compras = compras[compras["orgao_cnpj"] == r["orgao"]]
    compras = save("pncp_compra", compras)
    if compras.empty:
        _log("nenhuma contratação encontrada; encerrando")
        return
    by_id = {c["compra_id"]: c for c in compras.to_dict("records")}
    itens = []
    for i, c in enumerate(by_id.values(), 1):
        itens += pncp.fetch_itens(api, c)
        if i % 500 == 0:
            _log(f"itens: {i}/{len(by_id)} contratações")
    itens = save("pncp_item", itens)
    contratos = pd.DataFrame(
        pncp.fetch_contratos(cons, uf, start, end, raw / "cache" / "pncp_contratos")
    )
    if r.get("orgao") and not contratos.empty:
        contratos = contratos[contratos["orgao_cnpj"] == r["orgao"]]
    contratos = save("pncp_contrato", contratos)

    # Resultados: itens dos códigos mais frequentes (referência de preço) e todos os itens
    # de contratações sem contrato publicado (para saber quem venceu, ex.: dispensas).
    top_codes = set(itens["item_code"].dropna().value_counts().head(r["top_item_codes"]).index)
    with_contract = set(contratos["compra_id"].dropna()) if not contratos.empty else set()
    wanted = itens[
        itens["tem_resultado"]
        & (itens["item_code"].isin(top_codes) | ~itens["compra_id"].isin(with_contract))
    ]
    resultados = []
    for i, it in enumerate(wanted.itertuples(), 1):
        resultados += pncp.fetch_resultados(api, by_id[it.compra_id], int(it.numero_item))
        if i % 2000 == 0:
            _log(f"resultados: {i}/{len(wanted)} itens")
    save("pncp_resultado", resultados)

    # --- Portal da Transparência: participantes das licitações federais (PNCP -> Portal)
    participantes = []
    if cfg.api_key:
        portal = transparencia.client(cfg)
        fed = compras[
            (compras["esfera"] == "federal") & compras["modalidade_id"].isin([4, 5, 6, 7])
        ]
        for c in fed.itertuples():
            numero = portal_numero(c.numero_compra, c.ano)
            if numero and c.unidade_codigo:
                participantes += transparencia.fetch_participantes(
                    portal,
                    c.compra_id,
                    c.unidade_codigo,
                    numero,
                    PNCP_TO_PORTAL[int(c.modalidade_id)],
                )
        save("portal_participante", participantes)
        sanc = sancoes.fetch_sancoes(portal, "CEIS") + sancoes.fetch_sancoes(portal, "CNEP")
        save("sancao", sanc)
    else:
        _log("CGU_API_KEY ausente: sem participantes e sem CEIS/CNEP")

    # --- CNPJ da Receita (opcional; URL precisa ser configurada)
    docs = set(contratos.get("cnpj", pd.Series(dtype=str)))
    docs |= {x["cnpj"] for x in resultados} | {p["cnpj"] for p in participantes}
    if r.get("cnpj_dump_url"):
        bases = {d[:8] for d in docs}
        dump = cnpj_receita.fetch_filtered(
            r["cnpj_dump_url"], bases, raw / "tmp", staging / "cnpj", r["min_free_disk_gb"]
        )
        supplier, partner = cnpj_receita.to_canonical(
            dump["Empresas"], dump["Estabelecimentos"], dump["Socios"]
        )
        save("receita_supplier", supplier)
        save("receita_partner", partner)
    else:
        _log(
            "cnpj_dump_url não configurada: sem data de abertura e quadro societário "
            "(os indícios de empresa recém-criada e sócios em comum ficam vazios)"
        )

    # --- Preços de referência para os códigos mais frequentes
    cg = ApiClient(precos.BASE, raw / "cache" / "precos", r["pncp_rate_per_min"])
    kinds = itens.dropna(subset=["item_code"]).groupby("item_code")["material_servico"].first()
    obs = []
    for code in top_codes:
        obs += precos.fetch_precos(cg, code, kinds.get(code) == "M", uf)
    save(
        "ref_price",
        precos.summarize(pd.DataFrame(obs, columns=["item_code", "uf", "date", "price"])),
    )
    _log("coleta concluída")
