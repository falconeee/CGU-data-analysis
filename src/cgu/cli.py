"""CLI: `cgu all` roda o pipeline completo (por padrão sobre a base sintética)."""

from __future__ import annotations

from typing import Annotated

import typer

from cgu import pipeline
from cgu.config import Config, load_config

app = typer.Typer(
    help="Detecção de anomalias e indícios de fraude em contratações públicas.",
    no_args_is_help=True,
)

Fonte = Annotated[str | None, typer.Option("--fonte", help="synthetic | real (padrão: config)")]
Uf = Annotated[str | None, typer.Option("--uf", help="UF do recorte (modo real)")]
Inicio = Annotated[str | None, typer.Option("--inicio", help="AAAA-MM-DD (modo real)")]
Fim = Annotated[str | None, typer.Option("--fim", help="AAAA-MM-DD (modo real)")]
Orgao = Annotated[str | None, typer.Option("--orgao", help="CNPJ do órgão (modo real)")]
Amostra = Annotated[bool, typer.Option("--amostra", help="só o primeiro mês (modo real)")]


def _cfg(
    fonte: str | None = None,
    uf: str | None = None,
    inicio: str | None = None,
    fim: str | None = None,
    orgao: str | None = None,
) -> Config:
    cfg = load_config().with_overrides(
        **{
            "source": fonte,
            "real.uf": uf,
            "real.start": inicio,
            "real.end": fim,
            "real.orgao": orgao,
        }
    )
    if cfg.source not in {"synthetic", "real"}:
        raise typer.BadParameter("--fonte deve ser 'synthetic' ou 'real'")
    return cfg


@app.command()
def generate() -> None:
    """Gera a base sintética e grava o modelo canônico."""
    pipeline.generate_synthetic(_cfg())


@app.command()
def ingest(
    uf: Uf = None,
    inicio: Inicio = None,
    fim: Fim = None,
    orgao: Orgao = None,
    amostra: Amostra = False,
) -> None:
    """Baixa os dados públicos (modo real) para data/raw."""
    from cgu.ingest.run import ingest_all

    ingest_all(_cfg("real", uf, inicio, fim, orgao), sample=amostra)


@app.command()
def build(uf: Uf = None, inicio: Inicio = None, fim: Fim = None) -> None:
    """Converte os dados brutos (modo real) no modelo canônico."""
    pipeline.build_real(_cfg("real", uf, inicio, fim))


@app.command()
def detect() -> None:
    """Roda todos os detectores sobre o modelo canônico."""
    pipeline.detect(_cfg())


@app.command()
def score() -> None:
    """Calcula o score de risco por contrato, órgão e fornecedor."""
    pipeline.run_score(_cfg())


@app.command()
def validate() -> None:
    """Valida o score contra sanções (e contra o gabarito, no modo sintético)."""
    pipeline.run_validate(_cfg())


@app.command(name="all")
def run_all(
    fonte: Fonte = None,
    uf: Uf = None,
    inicio: Inicio = None,
    fim: Fim = None,
    orgao: Orgao = None,
    amostra: Amostra = False,
) -> None:
    """Pipeline completo: fonte -> detectores -> score -> validação."""
    cfg = _cfg(fonte, uf, inicio, fim, orgao)
    if cfg.source == "synthetic":
        pipeline.generate_synthetic(cfg)
    else:
        from cgu.ingest.run import ingest_all

        ingest_all(cfg, sample=amostra)
        pipeline.build_real(cfg)
    pipeline.detect(cfg)
    pipeline.run_score(cfg)
    pipeline.run_validate(cfg)


if __name__ == "__main__":
    app()
