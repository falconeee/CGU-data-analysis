import pandas as pd

from cgu import cnpj, schema
from cgu.config import load_config
from cgu.synthetic.generate import generate


def small_cfg(seed=7):
    return load_config().with_overrides(
        **{"synthetic.seed": seed, "synthetic.n_tenders": 800, "synthetic.n_suppliers": 400}
    )


def test_schema_and_scenarios():
    tables = schema.validate(generate(small_cfg()))
    gt = tables["ground_truth"]
    expected = {
        "cartel",
        "new_company",
        "splitting",
        "overprice",
        "single_supplier",
        "benford",
        "atypical",
    }
    assert expected <= set(gt["scenario"])
    # todos os CNPJs sintéticos são alfanuméricos válidos começando com "Z"
    sup = tables["supplier"]["cnpj"]
    assert sup.str.startswith("Z").all()
    assert sup.map(cnpj.is_valid).all()


def test_deterministic():
    a, b = generate(small_cfg(3)), generate(small_cfg(3))
    pd.testing.assert_frame_equal(a["contract"], b["contract"])
    c = generate(small_cfg(4))
    assert not a["contract"]["value_initial"].equals(c["contract"]["value_initial"])


def test_planted_splitting_respects_limits():
    cfg = small_cfg()
    t = generate(cfg)
    gt = t["ground_truth"]
    ids = set(gt[(gt.scenario == "splitting") & (gt.entity_type == "contract")]["entity_id"])
    c = t["contract"][t["contract"]["contract_id"].isin(ids)]
    limits = c["signed_at"].map(lambda d: cfg.dispensa_limit(d.year, engineering=False))
    assert (c["modality"] == "dispensa").all()
    assert (c["value_initial"] < limits).all()
