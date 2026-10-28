"""Dados abertos do CNPJ (Receita Federal): Empresas, Estabelecimentos e Sócios.

O dump completo passa de 20 GB descompactado. Para caber na máquina, cada ZIP é baixado,
lido em streaming (sem descompactar em disco), filtrado pelos CNPJs básicos que aparecem
nas contratações e apagado em seguida.

Os arquivos não têm cabeçalho; são separados por ';' em latin-1, com o layout abaixo.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable
from pathlib import Path

import httpx
import pandas as pd

from cgu.ingest.http import USER_AGENT, ensure_free_space

LAYOUTS = {
    "Empresas": [
        "cnpj_basico",
        "razao_social",
        "natureza_juridica",
        "qualificacao_responsavel",
        "capital_social",
        "porte_empresa",
        "ente_federativo",
    ],
    "Estabelecimentos": [
        "cnpj_basico",
        "cnpj_ordem",
        "cnpj_dv",
        "identificador_matriz_filial",
        "nome_fantasia",
        "situacao_cadastral",
        "data_situacao_cadastral",
        "motivo_situacao_cadastral",
        "nome_cidade_exterior",
        "pais",
        "data_inicio_atividade",
        "cnae_fiscal_principal",
        "cnae_fiscal_secundaria",
        "tipo_logradouro",
        "logradouro",
        "numero",
        "complemento",
        "bairro",
        "cep",
        "uf",
        "municipio",
        "ddd_1",
        "telefone_1",
        "ddd_2",
        "telefone_2",
        "ddd_fax",
        "fax",
        "correio_eletronico",
        "situacao_especial",
        "data_situacao_especial",
    ],
    "Socios": [
        "cnpj_basico",
        "identificador_socio",
        "nome_socio",
        "cpf_cnpj_socio",
        "qualificacao_socio",
        "data_entrada_sociedade",
        "pais",
        "representante_legal",
        "nome_representante",
        "qualificacao_representante",
        "faixa_etaria",
    ],
}
KEEP = {
    "Empresas": ["cnpj_basico", "razao_social", "porte_empresa"],
    "Estabelecimentos": [
        "cnpj_basico",
        "cnpj_ordem",
        "cnpj_dv",
        "data_inicio_atividade",
        "uf",
        "situacao_cadastral",
    ],
    "Socios": ["cnpj_basico", "nome_socio", "cpf_cnpj_socio", "data_entrada_sociedade"],
}
PORTE = {"01": "ME", "03": "EPP", "05": "DEMAIS", "00": None}


def filter_zip(zip_path: Path, kind: str, bases: set[str]) -> pd.DataFrame:
    """Lê um ZIP do dump em streaming e devolve só as linhas dos CNPJs básicos pedidos."""
    cols = LAYOUTS[kind]
    idx = [cols.index(c) for c in KEEP[kind]]
    rows = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            with zf.open(name) as raw:
                reader = csv.reader(
                    io.TextIOWrapper(raw, encoding="latin-1", newline=""),
                    delimiter=";",
                    quotechar='"',
                )
                for rec in reader:
                    if rec and rec[0] in bases:
                        rows.append([rec[i] if i < len(rec) else None for i in idx])
    return pd.DataFrame(rows, columns=KEEP[kind])


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=600, headers={"User-Agent": USER_AGENT}
    ) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def fetch_filtered(
    base_url: str,
    bases: set[str],
    work_dir: Path,
    out_dir: Path,
    min_free_gb: float,
    kinds: Iterable[str] = LAYOUTS,
) -> dict[str, pd.DataFrame]:
    """Baixa Empresas0..9, Estabelecimentos0..9 e Socios0..9, um por vez, filtrando.

    O resultado de cada ZIP é salvo em Parquet (checkpoint): ZIPs já processados são pulados.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for kind in kinds:
        parts = []
        for i in range(10):
            cp = out_dir / f"{kind}{i}.parquet"
            if not cp.exists():
                ensure_free_space(work_dir, min_free_gb)
                zpath = download(
                    f"{base_url.rstrip('/')}/{kind}{i}.zip", work_dir / f"{kind}{i}.zip"
                )
                try:
                    filter_zip(zpath, kind, bases).to_parquet(cp, index=False)
                finally:
                    zpath.unlink(missing_ok=True)
            parts.append(pd.read_parquet(cp))
        result[kind] = pd.concat(parts, ignore_index=True)
    return result


def to_canonical(
    emp: pd.DataFrame, est: pd.DataFrame, soc: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """-> (supplier parcial por CNPJ completo, partner)."""
    est = est.assign(cnpj=est["cnpj_basico"] + est["cnpj_ordem"] + est["cnpj_dv"])
    sup = est.merge(emp, on="cnpj_basico", how="left")
    supplier = pd.DataFrame(
        {
            "cnpj": sup["cnpj"],
            "cnpj_base": sup["cnpj_basico"],
            "name": sup["razao_social"],
            "opened_at": pd.to_datetime(
                sup["data_inicio_atividade"], format="%Y%m%d", errors="coerce"
            ),
            "uf": sup["uf"],
            "size": sup["porte_empresa"].map(PORTE),
        }
    )
    partner = pd.DataFrame(
        {
            "cnpj_base": soc["cnpj_basico"],
            "partner_name": soc["nome_socio"].str.strip(),
            "partner_doc": soc["cpf_cnpj_socio"].replace("", None),
            "joined_at": pd.to_datetime(
                soc["data_entrada_sociedade"], format="%Y%m%d", errors="coerce"
            ),
        }
    ).drop_duplicates()
    return supplier, partner
