"""Normalização e validação de CNPJ, numérico ou alfanumérico.

Desde 2026 a Receita emite CNPJs alfanuméricos: as 12 primeiras posições aceitam [A-Z0-9]
e os 2 dígitos verificadores continuam numéricos. O valor de cada caractere no cálculo
do DV é ord(c) - 48 (dígitos 0-9; A=17 ... Z=42). Por isso CNPJ é sempre texto, nunca int.
"""

from __future__ import annotations

import re

_STRIP = re.compile(r"[\s./-]")
_FULL = re.compile(r"^[A-Z0-9]{12}[0-9]{2}$")
_W1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_W2 = [6, *_W1]


def _dv(chars: str, weights: list[int]) -> int:
    total = sum((ord(c) - 48) * w for c, w in zip(chars, weights, strict=True))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def check_digits(first12: str) -> str:
    """Calcula os 2 DVs a partir das 12 primeiras posições."""
    first12 = first12.upper()
    d1 = _dv(first12, _W1)
    d2 = _dv(first12 + str(d1), _W2)
    return f"{d1}{d2}"


def clean(value: object) -> str:
    return _STRIP.sub("", str(value or "")).upper()


def normalize(value: object) -> str | None:
    """Retorna o CNPJ com 14 posições (sem máscara) ou None se o formato não for de CNPJ.

    CNPJs numéricos que perderam 1-2 zeros à esquerda (lidos como número) são completados.
    """
    s = clean(value)
    if s.isdigit() and len(s) in (12, 13):  # 11 dígitos é CPF, não CNPJ sem zeros
        s = s.zfill(14)
    return s if _FULL.match(s) else None


def is_valid(value: object) -> bool:
    s = normalize(value)
    return s is not None and check_digits(s[:12]) == s[12:]


def base(value: object) -> str | None:
    """CNPJ básico (8 primeiras posições): identifica a empresa (matriz + filiais)."""
    s = normalize(value)
    return s[:8] if s else None


def make(base8: str, branch: str = "0001") -> str:
    first12 = (base8 + branch).upper()
    return first12 + check_digits(first12)


def fmt(value: object) -> str:
    s = normalize(value)
    if not s:
        return str(value or "")
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"
