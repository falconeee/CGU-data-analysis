"""Gera a base sintética no modelo canônico, com cenários de fraude plantados.

Tudo é fictício: órgãos, municípios, empresas, sócios e sanções. Os CNPJs começam com "Z"
(formato alfanumérico válido, com DV), o que impede colisão com qualquer CNPJ numérico real.
A tabela `ground_truth` registra cada entidade plantada e o cenário correspondente.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from faker import Faker

from cgu import cnpj as cnpj_mod
from cgu.config import Config
from cgu.synthetic.catalog import (
    CATEGORIES,
    CITIES,
    FEDERAL_AGENCIES,
    SANCTION_AUTHORITIES,
    SANCTION_TYPES,
    STATE_AREAS,
    CategorySpec,
)

INFLATION = {2024: 1.0, 2025: 1.05, 2026: 1.09}
PRICE_SIGMA = 0.15  # dispersão do preço unitário em torno da referência
BIDDER_SIGMA = 0.12  # dispersão entre licitantes
_ALNUM = string.digits + string.ascii_uppercase
_MODALITY_TEXT = {
    "pregao": "Pregão eletrônico",
    "concorrencia": "Concorrência",
    "dispensa": "Dispensa de licitação",
    "inexigibilidade": "Inexigibilidade",
}


@dataclass
class _Supplier:
    cnpj: str
    name: str
    opened_at: pd.Timestamp
    categories: list[str]
    size: str


@dataclass
class _State:
    agencies: list[dict] = field(default_factory=list)
    suppliers: dict[str, _Supplier] = field(default_factory=dict)
    partners: list[dict] = field(default_factory=list)
    tenders: list[dict] = field(default_factory=list)
    bidders: list[dict] = field(default_factory=list)
    contracts: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    truth: list[dict] = field(default_factory=list)


class SyntheticGenerator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.p = cfg["synthetic"]
        self.rng = np.random.default_rng(self.p["seed"])
        self.fake = Faker("pt_BR")
        self.fake.seed_instance(self.p["seed"])
        self.start = pd.Timestamp(self.p["start"])
        self.end = pd.Timestamp(self.p["end"])
        self.uf = self.p["uf"]
        self.cats = {c.category_id: c for c in CATEGORIES}
        self.s = _State()
        self._build_catalog()

    # ------------------------------------------------------------------ helpers
    def _catalog_items(self, cat: CategorySpec) -> list[str]:
        return self.items_by_cat[cat.category_id]

    def _build_catalog(self) -> None:
        self.item_info: dict[str, dict] = {}
        self.items_by_cat: dict[str, list[str]] = {}
        code = 900001
        for cat in CATEGORIES:
            codes = []
            for desc, unit in cat.items:
                base = cat.price_scale * self.rng.lognormal(0, 0.6)
                self.item_info[str(code)] = {
                    "description": desc,
                    "unit": unit,
                    "base": base,
                    "category": cat.category_id,
                }
                codes.append(str(code))
                code += 1
            self.items_by_cat[cat.category_id] = codes

    def _ref_price(self, code: str, date: pd.Timestamp) -> float:
        return self.item_info[code]["base"] * INFLATION.get(date.year, 1.0)

    def _limit(self, date: pd.Timestamp, category: str) -> float:
        return self.cfg.dispensa_limit(date.year, self.cats[category].engineering)

    def _rand_date(self, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.Timestamp:
        span = max((hi - lo).days, 1)
        return lo + pd.Timedelta(days=int(self.rng.integers(0, span)))

    def _new_cnpj(self) -> str:
        while True:
            base8 = "Z" + "".join(self.rng.choice(list(_ALNUM), 7))
            value = cnpj_mod.make(base8)
            if value not in self.s.suppliers:
                return value

    def _masked_cpf(self) -> str:
        return f"***{self.rng.integers(0, 1_000_000):06d}**"

    def _person(self) -> dict:
        return {"partner_name": self.fake.name().upper(), "partner_doc": self._masked_cpf()}

    def _add_partner(self, supplier_cnpj: str, person: dict, joined: pd.Timestamp) -> None:
        self.s.partners.append({"cnpj_base": supplier_cnpj[:8], **person, "joined_at": joined})

    def _truth(self, entity_type: str, entity_id: str, scenario: str) -> None:
        self.s.truth.append(
            {"entity_type": entity_type, "entity_id": entity_id, "scenario": scenario}
        )

    # ------------------------------------------------------------------ entities
    def _gen_agencies(self) -> None:
        rows = []
        for name in FEDERAL_AGENCIES:
            rows.append({"name": name, "sphere": "federal", "municipality": CITIES[0]})
        for area in STATE_AREAS:
            rows.append(
                {
                    "name": f"Secretaria de Estado de {area} (fictícia)",
                    "sphere": "estadual",
                    "municipality": "Capital Fictícia",
                }
            )
        for city in CITIES:
            rows.append(
                {
                    "name": f"Prefeitura Municipal de {city}",
                    "sphere": "municipal",
                    "municipality": city,
                }
            )
            rows.append(
                {
                    "name": f"Secretaria Municipal de Saúde de {city}",
                    "sphere": "municipal",
                    "municipality": city,
                }
            )
        rows = rows[: self.p["n_agencies"]]
        weights = self.rng.lognormal(0, 0.8, len(rows))
        for i, r in enumerate(rows):
            cat_w = self.rng.dirichlet(np.full(len(CATEGORIES), 0.8))
            self.s.agencies.append(
                {
                    "agency_id": f"AG{i + 1:03d}",
                    "uf": self.uf,
                    **r,
                    "_weight": weights[i],
                    "_cat_w": cat_w,
                }
            )
        w = np.array([a["_weight"] for a in self.s.agencies])
        self.agency_p = w / w.sum()

    def _new_supplier(
        self,
        categories: list[str],
        opened_at: pd.Timestamp,
        n_partners: int | None = None,
        reuse_prob: float = 0.02,
    ) -> _Supplier:
        value = self._new_cnpj()
        word = self.cats[categories[0]].supplier_word
        suffix = self.rng.choice(
            ["Ltda", "S.A.", "Ltda - ME", "Ltda - EPP"], p=[0.6, 0.1, 0.15, 0.15]
        )
        name = f"{self.fake.last_name()} {word} {suffix}".upper()
        size = str(self.rng.choice(["ME", "EPP", "DEMAIS"], p=[0.45, 0.3, 0.25]))
        sup = _Supplier(value, name, opened_at, categories, size)
        self.s.suppliers[value] = sup
        for _ in range(n_partners or int(self.rng.integers(1, 4))):
            if self.s.partners and self.rng.random() < reuse_prob:
                old = self.s.partners[int(self.rng.integers(0, len(self.s.partners)))]
                person = {"partner_name": old["partner_name"], "partner_doc": old["partner_doc"]}
            else:
                person = self._person()
            self._add_partner(value, person, opened_at)
        return sup

    def _gen_suppliers(self) -> None:
        cat_ids = list(self.cats)
        for _ in range(self.p["n_suppliers"]):
            cats = [str(self.rng.choice(cat_ids))]
            if self.rng.random() < 0.3:
                cats.append(str(self.rng.choice(cat_ids)))
            if self.rng.random() < 0.03:  # empresas novas legítimas (geram falso positivo)
                opened = self._rand_date(pd.Timestamp("2023-06-01"), pd.Timestamp("2026-06-01"))
            else:
                opened = self._rand_date(pd.Timestamp("1995-01-01"), pd.Timestamp("2022-12-31"))
            self._new_supplier(cats, opened)
        self.pool = {
            c: [s.cnpj for s in self.s.suppliers.values() if c in s.categories] for c in cat_ids
        }

    # ------------------------------------------------------------------ tenders
    def _pick_items(self, cat: CategorySpec, n: int, date: pd.Timestamp) -> list[list]:
        codes = self.rng.choice(
            self._catalog_items(cat), size=min(n, len(cat.items)), replace=False
        )
        out = []
        for code in codes:
            qty = max(1, round(cat.qty_scale * self.rng.lognormal(0, 0.7)))
            est = self._ref_price(code, date) * self.rng.lognormal(0, 0.1)
            out.append([str(code), float(qty), est])
        return out

    @staticmethod
    def _scale_items(items: list[list], target: float) -> None:
        """Ajusta quantidades para o total ficar perto (e abaixo) de `target`."""
        total = sum(q * p for _, q, p in items)
        if total <= 0:
            return
        f = target / total
        for it in items:
            it[1] = max(1.0, float(np.floor(it[1] * f)))

    def _create(
        self,
        agency: dict,
        cat: CategorySpec,
        modality: str,
        date: pd.Timestamp,
        items: list[list],
        bidders: list[str],
        factors: list[float] | None = None,
        winner: int | None = None,
    ) -> dict:
        """Cria licitação + licitantes + itens + contrato do vencedor. Retorna o contrato."""
        tid = f"LC{len(self.s.tenders) + 1:06d}"
        n_b = len(bidders)
        if factors is None:
            factors = list(self.rng.lognormal(0, BIDDER_SIGMA, n_b))
        prices = np.array(
            [[p * f * self.rng.lognormal(0, 0.05) for _, _, p in items] for f in factors]
        )
        qty = np.array([q for _, q, _ in items])
        bids = prices @ qty
        w = int(np.argmin(bids)) if winner is None else winner
        if modality == "dispensa":
            # dispensa por valor nunca passa do limite legal (o ruído de preço poderia passar)
            limit = self._limit(date, cat.category_id)
            if bids[w] >= limit:
                f = limit * self.rng.uniform(0.9, 0.98) / bids[w]
                qty, bids = qty * f, bids * f
                items = [[code, float(qty[j]), p] for j, (code, _, p) in enumerate(items)]
        if winner is not None:  # propostas de cobertura sempre acima da vencedora
            for i in range(n_b):
                if i != w and bids[i] <= bids[w]:
                    bids[i] = bids[w] * self.rng.uniform(1.01, 1.05)
        est_total = float(sum(q * p for _, q, p in items))
        self.s.tenders.append(
            {
                "tender_id": tid,
                "agency_id": agency["agency_id"],
                "modality": modality,
                "category": cat.category_id,
                "object": f"{_MODALITY_TEXT[modality]} — {cat.name.lower()}",
                "published_at": date,
                "estimated_value": est_total,
            }
        )
        for i, b in enumerate(bidders):
            self.s.bidders.append(
                {"tender_id": tid, "cnpj": b, "bid_value": float(bids[i]), "is_winner": i == w}
            )
        contract = self._contract(tid, agency, cat, modality, date, bidders[w])
        value = 0.0
        for j, (code, q, _) in enumerate(items):
            unit_price = float(prices[w, j])
            value += q * unit_price
            self.s.items.append(
                {
                    "item_id": f"{tid}-{j + 1:02d}",
                    "tender_id": tid,
                    "contract_id": contract["contract_id"],
                    "item_code": code,
                    "description": self.item_info[code]["description"],
                    "unit": self.item_info[code]["unit"],
                    "quantity": q,
                    "unit_price": unit_price,
                    "uf": agency["uf"],
                    "date": date,
                }
            )
        contract["value_initial"] = value
        n_am = contract["n_amendments"]
        bump = sum(self.rng.uniform(0, 0.08) for _ in range(n_am))
        contract["value_final"] = value * (1 + min(bump, 0.25))
        return contract

    def _contract(
        self,
        tid: str,
        agency: dict,
        cat: CategorySpec,
        modality: str,
        date: pd.Timestamp,
        winner: str,
    ) -> dict:
        lag = {
            "pregao": (20, 60),
            "concorrencia": (30, 90),
            "dispensa": (3, 15),
            "inexigibilidade": (5, 20),
        }[modality]
        signed = min(date + pd.Timedelta(days=int(self.rng.integers(*lag))), self.end)
        published = signed + pd.Timedelta(days=int(self.rng.integers(1, 21)))
        start = signed + pd.Timedelta(days=int(self.rng.integers(0, 11)))
        months = {"material": (3, 13), "service": (12, 13), "works": (6, 25)}[cat.kind]
        duration = int(self.rng.integers(*months))
        am_rate = {"material": 0.2, "service": 0.8, "works": 1.2}[cat.kind]
        c = {
            "contract_id": f"CT{len(self.s.contracts) + 1:06d}",
            "tender_id": tid,
            "agency_id": agency["agency_id"],
            "cnpj": winner,
            "modality": modality,
            "category": cat.category_id,
            "object": f"Contratação de {cat.name.lower()} ({agency['name']})",
            "signed_at": signed,
            "published_at": published,
            "start_date": start,
            "end_date": start + pd.DateOffset(months=duration),
            "value_initial": 0.0,
            "value_final": 0.0,
            "n_amendments": int(self.rng.poisson(am_rate)),
        }
        self.s.contracts.append(c)
        return c

    def _eligible(self, category: str, date: pd.Timestamp, exclude: set[str]) -> list[str]:
        return [
            c
            for c in self.pool[category]
            if c not in exclude and self.s.suppliers[c].opened_at < date
        ]

    def _gen_normal_tenders(self) -> None:
        reserved = self.reserved
        for _ in range(self.p["n_tenders"]):
            agency = self.s.agencies[int(self.rng.choice(len(self.s.agencies), p=self.agency_p))]
            cat = CATEGORIES[int(self.rng.choice(len(CATEGORIES), p=agency["_cat_w"]))]
            if cat.kind == "works":
                modality = self.rng.choice(
                    ["concorrencia", "pregao", "dispensa", "inexigibilidade"],
                    p=[0.4, 0.2, 0.3, 0.1],
                )
            else:
                modality = self.rng.choice(
                    ["pregao", "dispensa", "inexigibilidade", "concorrencia"],
                    p=[0.4, 0.38, 0.17, 0.05],
                )
            modality = str(modality)
            date = self._rand_date(self.start, self.end - pd.Timedelta(days=30))
            n_items = {
                "pregao": 1 + self.rng.geometric(0.3),
                "concorrencia": 1 + self.rng.geometric(0.4),
                "dispensa": self.rng.integers(1, 5),
                "inexigibilidade": self.rng.integers(1, 3),
            }
            items = self._pick_items(cat, int(min(n_items[modality], 10)), date)
            if modality == "dispensa":
                limit = self._limit(date, cat.category_id)
                total = sum(q * p for _, q, p in items)
                if total > 0.8 * limit:
                    self._scale_items(items, limit * self.rng.uniform(0.05, 0.75))
            n_bid = {
                "pregao": 2 + min(self.rng.poisson(2.5), 8),
                "concorrencia": 2 + min(self.rng.poisson(2), 6),
                "dispensa": 1 + min(self.rng.poisson(1), 2),
                "inexigibilidade": 1,
            }[modality]
            pool = self._eligible(cat.category_id, date, reserved)
            bidders = list(self.rng.choice(pool, size=min(n_bid, len(pool)), replace=False))
            self._create(agency, cat, modality, date, items, [str(b) for b in bidders])

    # ------------------------------------------------------------------ scenarios
    def _scenario_cartels(self) -> None:
        cat_ids = list(
            self.rng.choice(
                ["OBRAS", "LIMP", "ALIM", "MANUT", "VEIC"], size=self.p["cartels"], replace=False
            )
        )
        lo, hi = self.p["cartel_size"]
        for cat_id in cat_ids:
            cat = self.cats[str(cat_id)]
            size = int(self.rng.integers(lo, hi + 1))
            members = [
                self._new_supplier(
                    [cat.category_id],
                    self._rand_date(pd.Timestamp("2005-01-01"), pd.Timestamp("2020-12-31")),
                    n_partners=1,
                )
                for _ in range(size)
            ]
            # sócios-laranja ligando as empresas do grupo
            fronts = [self._person(), self._person()]
            for m in members[: size // 2 + 1]:
                self._add_partner(m.cnpj, fronts[0], m.opened_at)
            for m in members[size // 2 :]:
                self._add_partner(m.cnpj, fronts[1], m.opened_at)
            for m in members:
                self.pool[cat.category_id].append(m.cnpj)
                self._truth("supplier", m.cnpj, "cartel")
            self.fraud_suppliers.update(m.cnpj for m in members)
            agencies = self.rng.choice(len(self.s.agencies), size=3, replace=False)
            modality = "concorrencia" if cat.kind == "works" else "pregao"
            for t in range(self.p["cartel_tenders"]):
                agency = self.s.agencies[int(agencies[t % 3])]
                date = self._rand_date(self.start, self.end - pd.Timedelta(days=60))
                items = self._pick_items(cat, int(self.rng.integers(2, 6)), date)
                n_part = int(self.rng.integers(3, size + 1))
                part = [m.cnpj for m in self.rng.permutation(members)[:n_part]]
                winner_cnpj = members[t % size].cnpj  # rodízio de vencedores
                if winner_cnpj not in part:
                    part[0] = winner_cnpj
                w = part.index(winner_cnpj)
                fw = self.rng.uniform(1.15, 1.35)
                factors = [
                    fw if i == w else fw * self.rng.uniform(1.02, 1.10) for i in range(len(part))
                ]
                if self.rng.random() < 0.3:
                    outsider = self._eligible(cat.category_id, date, self.reserved)
                    part.append(str(self.rng.choice(outsider)))
                    factors.append(fw * self.rng.uniform(1.05, 1.2))
                c = self._create(agency, cat, modality, date, items, part, factors, winner=w)
                self._truth("tender", c["tender_id"], "cartel")
                self._truth("contract", c["contract_id"], "cartel")
            self.cartel_groups.append([m.cnpj for m in members])

    def _scenario_shells(self) -> None:
        cats = [c for c in CATEGORIES if not c.engineering]
        existing = list(self.s.suppliers.values())
        for _ in range(self.p["shell_companies"]):
            cat = cats[int(self.rng.integers(0, len(cats)))]
            first = self._rand_date(
                self.start + pd.Timedelta(days=60), self.end - pd.Timedelta(days=200)
            )
            opened = first - pd.Timedelta(days=int(self.rng.integers(20, 150)))
            sup = self._new_supplier([cat.category_id], opened, n_partners=1, reuse_prob=0)
            if self.rng.random() < 0.5:  # sócio que também é sócio de outra empresa
                other = existing[int(self.rng.integers(0, len(existing)))]
                p = next(p for p in self.s.partners if p["cnpj_base"] == other.cnpj[:8])
                self._add_partner(
                    sup.cnpj,
                    {"partner_name": p["partner_name"], "partner_doc": p["partner_doc"]},
                    opened,
                )
            self._truth("supplier", sup.cnpj, "new_company")
            self.fraud_suppliers.add(sup.cnpj)
            date = first
            for _ in range(int(self.rng.integers(2, 5))):
                agency = self.s.agencies[
                    int(self.rng.choice(len(self.s.agencies), p=self.agency_p))
                ]
                if self.rng.random() < 0.6:
                    modality = "dispensa"
                    items = self._pick_items(cat, int(self.rng.integers(1, 3)), date)
                    self._scale_items(
                        items, self._limit(date, cat.category_id) * self.rng.uniform(0.6, 0.95)
                    )
                    bidders = [sup.cnpj]
                else:
                    modality = "pregao"
                    items = self._pick_items(cat, int(self.rng.integers(2, 6)), date)
                    others = self._eligible(cat.category_id, date, self.reserved)
                    bidders = [sup.cnpj, *map(str, self.rng.choice(others, 2, replace=False))]
                factors = [self.rng.uniform(0.85, 0.95)] + [
                    self.rng.uniform(1.0, 1.2) for _ in bidders[1:]
                ]
                c = self._create(agency, cat, modality, date, items, bidders, factors, winner=0)
                self._truth("contract", c["contract_id"], "new_company")
                date = date + pd.Timedelta(days=int(self.rng.integers(20, 60)))

    def _scenario_splitting(self) -> None:
        cats = [c for c in CATEGORIES if not c.engineering]
        for _ in range(self.p["splitting_series"]):
            agency = self.s.agencies[int(self.rng.integers(0, len(self.s.agencies)))]
            cat = cats[int(self.rng.integers(0, len(cats)))]
            start = self._rand_date(self.start, self.end - pd.Timedelta(days=90))
            pool = self._eligible(cat.category_id, start, self.reserved)
            n_sup = 1 if self.rng.random() < 0.6 else int(self.rng.integers(2, 4))
            sups = [str(s) for s in self.rng.choice(pool, size=n_sup, replace=False)]
            limit = self._limit(start, cat.category_id)
            date = start
            for j in range(int(self.rng.integers(3, 8))):
                items = self._pick_items(cat, int(self.rng.integers(1, 3)), date)
                self._scale_items(items, limit * self.rng.uniform(0.75, 0.97))
                sup = sups[j % n_sup]
                c = self._create(agency, cat, "dispensa", date, items, [sup], [1.0], winner=0)
                self._truth("contract", c["contract_id"], "splitting")
                self.fraud_suppliers.add(sup)
                date = date + pd.Timedelta(days=int(self.rng.integers(3, 12)))

    def _scenario_favored(self) -> None:
        idx = self.rng.choice(len(self.s.agencies), size=self.p["favored_suppliers"], replace=False)
        for i in idx:
            agency = self.s.agencies[int(i)]
            cat = CATEGORIES[int(np.argmax(agency["_cat_w"]))]
            sup = self._new_supplier(
                [cat.category_id],
                self._rand_date(pd.Timestamp("2008-01-01"), pd.Timestamp("2019-12-31")),
            )
            self._truth("supplier", sup.cnpj, "single_supplier")
            self.fraud_suppliers.add(sup.cnpj)
            for _ in range(int(self.rng.integers(12, 21))):
                date = self._rand_date(self.start, self.end - pd.Timedelta(days=60))
                modality = "inexigibilidade" if self.rng.random() < 0.5 else "pregao"
                items = self._pick_items(cat, int(self.rng.integers(1, 4)), date)
                self._scale_items(items, self.rng.uniform(150_000, 900_000))
                c = self._create(
                    agency,
                    cat,
                    modality,
                    date,
                    items,
                    [sup.cnpj],
                    [self.rng.uniform(1.0, 1.2)],
                    winner=0,
                )
                self._truth("contract", c["contract_id"], "single_supplier")

    def _scenario_benford(self) -> None:
        """Valores 'inventados': 1º dígito uniforme e números redondos, via quantidade."""
        top = np.argsort(-self.agency_p)[:10]
        chosen = self.rng.choice(top, size=self.p["benford_agencies"], replace=False)
        ids = {self.s.agencies[int(i)]["agency_id"] for i in chosen}
        tenders = {
            t["tender_id"]
            for t in self.s.tenders
            if t["agency_id"] in ids and t["tender_id"] not in self.scenario_tenders
        }
        for it in self.s.items:
            if it["tender_id"] not in tenders:
                continue
            total = it["quantity"] * it["unit_price"]
            e = int(np.floor(np.log10(max(total, 1))))
            d = int(self.rng.integers(1, 10))
            new_total = round(d * 10**e * self.rng.uniform(1.0, 1.1), -max(e - 1, 0))
            it["quantity"] = new_total / it["unit_price"]
        self._recompute_contract_values(tenders)
        for a in ids:
            self._truth("agency", a, "benford")
        self.benford_agencies = ids

    def _scenario_overprice(self) -> None:
        blocked = self.scenario_tenders | {
            t["tender_id"] for t in self.s.tenders if t["agency_id"] in self.benford_agencies
        }
        candidates = [
            i
            for i, it in enumerate(self.s.items)
            if it["tender_id"] not in blocked and self._modality[it["tender_id"]] != "dispensa"
        ]
        chosen = self.rng.choice(candidates, size=self.p["overpriced_items"], replace=False)
        touched = set()
        for i in chosen:
            it = self.s.items[int(i)]
            it["unit_price"] *= self.rng.uniform(1.8, 3.0)
            touched.add(it["tender_id"])
            self._truth("item", it["item_id"], "overprice")
            self._truth("contract", it["contract_id"], "overprice")
        self._recompute_contract_values(touched)

    def _scenario_atypical(self) -> None:
        blocked = self.scenario_tenders
        candidates = [c for c in self.s.contracts if c["tender_id"] not in blocked]
        for j in self.rng.choice(len(candidates), size=self.p["atypical_contracts"], replace=False):
            c = candidates[int(j)]
            c["n_amendments"] = int(self.rng.integers(6, 13))
            c["value_final"] = c["value_initial"] * self.rng.uniform(1.5, 2.5)
            c["end_date"] = c["start_date"] + pd.DateOffset(months=int(self.rng.integers(48, 61)))
            c["published_at"] = c["signed_at"] + pd.Timedelta(days=int(self.rng.integers(60, 200)))
            self._truth("contract", c["contract_id"], "atypical")
            self.fraud_suppliers.add(c["cnpj"])

    def _recompute_contract_values(self, tender_ids: set[str]) -> None:
        totals: dict[str, float] = {}
        for it in self.s.items:
            if it["tender_id"] in tender_ids and it["contract_id"]:
                totals[it["contract_id"]] = (
                    totals.get(it["contract_id"], 0.0) + it["quantity"] * it["unit_price"]
                )
        for c in self.s.contracts:
            if c["contract_id"] in totals:
                ratio = c["value_final"] / c["value_initial"] if c["value_initial"] else 1.0
                c["value_initial"] = totals[c["contract_id"]]
                c["value_final"] = c["value_initial"] * ratio
        winners = {b["tender_id"]: b for b in self.s.bidders if b["is_winner"]}
        by_tender = {c["tender_id"]: c for c in self.s.contracts}
        for tid in tender_ids:
            if tid in winners and tid in by_tender:
                winners[tid]["bid_value"] = by_tender[tid]["value_initial"]

    def _gen_sanctions(self) -> pd.DataFrame:
        first_contract: dict[str, pd.Timestamp] = {}
        for c in self.s.contracts:
            cur = first_contract.get(c["cnpj"])
            if cur is None or c["signed_at"] < cur:
                first_contract[c["cnpj"]] = c["signed_at"]
        today = pd.Timestamp("2026-10-27")
        rows = []
        for cnpj in self.s.suppliers:
            rate = (
                self.p["sanction_rate_fraud"]
                if cnpj in self.fraud_suppliers
                else self.p["sanction_rate_normal"]
            )
            if self.rng.random() >= rate:
                continue
            lo = first_contract.get(cnpj, self.start) + pd.Timedelta(days=30)
            start = self._rand_date(min(lo, today - pd.Timedelta(days=2)), today)
            rows.append(
                {
                    "cnpj": cnpj,
                    "source": "CEIS" if self.rng.random() < 0.7 else "CNEP",
                    "start_date": start,
                    "end_date": start + pd.DateOffset(years=int(self.rng.integers(1, 6))),
                    "sanction_type": str(self.rng.choice(SANCTION_TYPES)),
                    "authority": str(self.rng.choice(SANCTION_AUTHORITIES)),
                }
            )
        return pd.DataFrame(rows)

    def _ref_prices(self) -> pd.DataFrame:
        rows = []
        z = 0.674 * PRICE_SIGMA
        for code, info in self.item_info.items():
            for year, infl in INFLATION.items():
                median = info["base"] * infl
                rows.append(
                    {
                        "item_code": code,
                        "uf": self.uf,
                        "year": year,
                        "median": median,
                        "q1": median * np.exp(-z),
                        "q3": median * np.exp(z),
                        "n_obs": int(self.rng.integers(2, 200)),
                    }
                )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ main
    def generate(self) -> dict[str, pd.DataFrame]:
        self.fraud_suppliers: set[str] = set()
        self.cartel_groups: list[list[str]] = []
        self.benford_agencies: set[str] = set()
        self._gen_agencies()
        self._gen_suppliers()

        n0 = len(self.s.tenders)
        # empresas plantadas ficam fora do sorteio de licitantes "normais"
        self.reserved = self.fraud_suppliers
        self._scenario_cartels()
        self._scenario_shells()
        self._scenario_favored()
        self._scenario_splitting()
        self.scenario_tenders = {t["tender_id"] for t in self.s.tenders[n0:]}
        self._gen_normal_tenders()
        self._modality = {t["tender_id"]: t["modality"] for t in self.s.tenders}
        self._scenario_benford()
        self._scenario_overprice()
        self._scenario_atypical()

        agencies = pd.DataFrame(self.s.agencies).drop(columns=["_weight", "_cat_w"])
        suppliers = pd.DataFrame(
            [
                {
                    "cnpj": s.cnpj,
                    "cnpj_base": s.cnpj[:8],
                    "name": s.name,
                    "opened_at": s.opened_at,
                    "uf": self.uf,
                    "size": s.size,
                }
                for s in self.s.suppliers.values()
            ]
        )
        categories = pd.DataFrame(
            [
                {"category_id": c.category_id, "name": c.name, "engineering": c.engineering}
                for c in CATEGORIES
            ]
        )
        truth = pd.DataFrame(self.s.truth).drop_duplicates()
        return {
            "agency": agencies,
            "category": categories,
            "supplier": suppliers,
            "partner": pd.DataFrame(self.s.partners).drop_duplicates(
                subset=["cnpj_base", "partner_doc", "partner_name"]
            ),
            "tender": pd.DataFrame(self.s.tenders),
            "bidder": pd.DataFrame(self.s.bidders),
            "contract": pd.DataFrame(self.s.contracts),
            "item": pd.DataFrame(self.s.items),
            "ref_price": self._ref_prices(),
            "sanction": self._gen_sanctions(),
            "ground_truth": truth,
        }


def generate(cfg: Config) -> dict[str, pd.DataFrame]:
    return SyntheticGenerator(cfg).generate()
