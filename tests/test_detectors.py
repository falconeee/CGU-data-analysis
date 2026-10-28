import json

import numpy as np
import pandas as pd
import pytest

from cgu import cnpj, db, pipeline, schema
from cgu.detectors import benford, redflags
from cgu.scoring.score import contract_scores
from conftest import tmp_config

A, B, C = (cnpj.make(b) for b in ("ZAAAAAA1", "ZBBBBBB2", "ZCCCCCC3"))


def empty_tables() -> dict[str, pd.DataFrame]:
    return {name: pd.DataFrame(columns=list(s.columns)) for name, s in schema.SCHEMAS.items()}


def contract(
    cid, cnpj_, signed, value, modality="dispensa", agency="AG1", category="MAT", tender=None
):
    return {
        "contract_id": cid,
        "tender_id": tender,
        "agency_id": agency,
        "cnpj": cnpj_,
        "modality": modality,
        "category": category,
        "object": "x",
        "signed_at": pd.Timestamp(signed),
        "published_at": None,
        "start_date": None,
        "end_date": None,
        "value_initial": value,
        "value_final": value,
        "n_amendments": 0,
    }


@pytest.fixture
def con_factory(tmp_path):
    def make(**tables):
        t = empty_tables()
        t["agency"] = pd.DataFrame(
            [
                {
                    "agency_id": "AG1",
                    "name": "Órgão",
                    "sphere": "municipal",
                    "uf": "ES",
                    "municipality": "X",
                }
            ]
        )
        t["category"] = pd.DataFrame(
            [{"category_id": "MAT", "name": "Material", "engineering": False}]
        )
        t["supplier"] = pd.DataFrame(
            [
                {
                    "cnpj": x,
                    "cnpj_base": x[:8],
                    "name": n,
                    "opened_at": pd.Timestamp("2010-01-01"),
                    "uf": "ES",
                    "size": "ME",
                }
                for x, n in ((A, "A"), (B, "B"), (C, "C"))
            ]
        )
        t.update({k: pd.DataFrame(v) for k, v in tables.items()})
        cfg = tmp_config(tmp_path)
        pipeline.store_canonical(cfg, t, source="test")
        return cfg, db.connect(cfg.warehouse)

    return make


def test_splitting_positive_and_negative(con_factory):
    limit = 62725.59  # 2025, demais compras
    positive = [contract(f"P{i}", A, f"2025-03-{1 + 10 * i:02d}", limit * 0.9) for i in range(3)]
    # mesma soma, mas espalhada no ano: fora da janela de 90 dias
    negative = [
        contract(
            f"N{i}", B, f"2025-{1 + 4 * i:02d}-15", limit * 0.9, agency="AG1", category="OUTRA"
        )
        for i in range(3)
    ]
    cfg, ctx = con_factory(contract=positive + negative)
    with ctx as con:
        flags = redflags.splitting(con, cfg)
    assert set(flags["contract_id"]) == {"P0", "P1", "P2"}
    ev = json.loads(flags["evidence"].iloc[0])
    assert ev["soma"] > ev["limite"]


def test_shared_partners_and_new_company(con_factory):
    bidders = [
        {"tender_id": "T1", "cnpj": x, "bid_value": v, "is_winner": w}
        for x, v, w in ((A, 100.0, True), (B, 110.0, False), (C, 120.0, False))
    ]
    partners = [
        {
            "cnpj_base": A[:8],
            "partner_name": "FULANO",
            "partner_doc": "***111111**",
            "joined_at": None,
        },
        {
            "cnpj_base": B[:8],
            "partner_name": "FULANO",
            "partner_doc": "***111111**",
            "joined_at": None,
        },
        {
            "cnpj_base": C[:8],
            "partner_name": "OUTRA PESSOA",
            "partner_doc": "***2**",
            "joined_at": None,
        },
    ]
    tender = [
        {
            "tender_id": "T1",
            "agency_id": "AG1",
            "modality": "pregao",
            "category": "MAT",
            "object": "x",
            "published_at": pd.Timestamp("2025-01-01"),
            "estimated_value": 100.0,
        }
    ]
    cfg, ctx = con_factory(
        tender=tender,
        bidder=bidders,
        partner=partners,
        contract=[contract("K1", A, "2025-02-01", 100.0, "pregao", tender="T1")],
    )
    with ctx as con:
        sp = redflags.shared_partners(con, cfg)
        con.execute("UPDATE supplier SET opened_at = DATE '2024-12-01' WHERE cnpj = ?", [A])
        nc = redflags.new_company(con, cfg)
    pairs = json.loads(sp["evidence"].iloc[0])["pares"]
    assert sp["contract_id"].tolist() == ["K1"]
    assert {pairs[0]["empresa_a"], pairs[0]["empresa_b"]} == {A, B}
    assert nc["contract_id"].tolist() == ["K1"]
    assert 0.8 < nc["score"].iloc[0] < 1


def test_benford_conforming_vs_fabricated():
    rng = np.random.default_rng(0)
    natural = rng.lognormal(10, 2.5, 3000)  # várias ordens de grandeza
    fabricated = rng.integers(1, 10, 3000) * 1000.0  # 1º dígito uniforme e redondo
    a, b = benford.analyze(natural), benford.analyze(fabricated)
    assert a["mad"] < 0.012 and a["p_value"] > 0.001
    assert b["mad"] > 0.04 and b["p_value"] < 1e-10 and b["round_share"] == 1.0


def test_benford_digits_handle_powers_of_ten():
    d1, d2 = benford.digits(np.array([10.0, 100.0, 1000.0, 99.99, 12345.0]))
    assert d1.tolist() == [1, 1, 1, 9, 1]
    assert d2.tolist() == [0, 0, 0, 9, 2]


def test_noisy_or_score():
    flags = pd.DataFrame(
        [
            {"contract_id": "X", "detector": "a", "score": 1.0, "flag": True, "evidence": ""},
            {"contract_id": "X", "detector": "b", "score": 0.5, "flag": True, "evidence": ""},
            {"contract_id": "Y", "detector": "a", "score": 0.9, "flag": False, "evidence": ""},
        ]
    )
    contracts = pd.DataFrame({"contract_id": ["X", "Y", "Z"]})
    out = contract_scores(flags, contracts, {"a": 0.6, "b": 0.4}).set_index("contract_id")
    assert out.at["X", "risk"] == pytest.approx(1 - (1 - 0.6) * (1 - 0.2))
    assert out.at["Y", "risk"] == 0  # flag=False não conta
    assert out.at["Z", "risk"] == 0
    assert out.at["X", "n_flags"] == 2


def test_pipeline_recovers_planted_scenarios(synthetic_cfg):
    with db.connect(synthetic_cfg.warehouse, read_only=True) as con:
        sc = db.table(con, "validation_scenario").set_index(["cenario", "detector"])
        summary = db.table(con, "validation_summary").set_index("rotulo")
    for key in sc.index:
        assert sc.loc[key, "recall"] >= 0.7, key
    assert sc.loc[("cartel", "cartel"), "precisao"] >= 0.9
    assert summary.loc["gabarito", "auc"] > 0.9
    assert summary.loc["sancoes", "auc"] > 0.6


def test_pipeline_outputs_are_consistent(synthetic_cfg):
    with db.connect(synthetic_cfg.warehouse, read_only=True) as con:
        n_contracts = con.execute("SELECT count(*) FROM contract").fetchone()[0]
        n_scored = con.execute("SELECT count(*) FROM contract_score").fetchone()[0]
        bad = con.execute(
            "SELECT count(*) FROM contract_score WHERE risk < 0 OR risk > 1 "
            "OR (n_flags = 0 AND risk > 0)"
        ).fetchone()[0]
        unknown = con.execute(
            "SELECT count(*) FROM flags f LEFT JOIN contract c "
            "USING (contract_id) WHERE c.contract_id IS NULL"
        ).fetchone()[0]
    assert n_contracts == n_scored
    assert bad == 0
    assert unknown == 0
    assert (synthetic_cfg.path("reports_dir") / "validation.json").exists()
