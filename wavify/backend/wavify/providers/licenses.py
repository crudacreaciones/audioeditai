"""Interpretation of open licences declared by providers.

Creative Commons licences (all versions/variants) allow copying the work for personal use, so a download through the
source's official mechanism is allowed. Changing the file format is not an adaptation under CC (CC 4.0 §2(a)(4)
explicitly permits technical modifications such as format shifting), so conversion to MP3 is allowed even for -ND.
Anything else (no licence, "all rights reserved", unknown text) is treated as incompatible.
"""
from __future__ import annotations

import re

from .base import LicenseInfo

_CC = re.compile(r"creativecommons\.org/licenses/([a-z\-]+)/(\d(?:\.\d)?)", re.I)
_PD = re.compile(r"creativecommons\.org/publicdomain/(zero|mark)/(\d(?:\.\d)?)", re.I)


def from_url(url: str | None) -> LicenseInfo:
    url = (url or "").strip()
    if not url:
        return LicenseInfo(name="Sin licencia declarada", notes="La fuente no declara una licencia que permita la descarga.")
    m = _CC.search(url)
    if m:
        code, ver = m.group(1).lower(), m.group(2)
        return LicenseInfo(name=f"CC {code.upper()} {ver}", url=_https(url), allows_download=True, allows_conversion=True,
                           requires_attribution="by" in code.split("-"),
                           notes="Uso no comercial únicamente." if "nc" in code.split("-") else "")
    m = _PD.search(url)
    if m:
        name = "CC0 1.0 (dominio público)" if m.group(1).lower() == "zero" else "Marca de dominio público"
        return LicenseInfo(name=name, url=_https(url), allows_download=True, allows_conversion=True)
    return LicenseInfo(name="Licencia no reconocida", url=url,
                       notes="No se puede verificar que la licencia permita la descarga.")


def _https(url: str) -> str:
    return re.sub(r"^http://", "https://", url)
