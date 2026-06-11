"""OQMD provider — public REST API (~1M structures), no key required.

NOTE: this still uses blocking ``urllib``. The whole `search_materials` tool
runs in a worker thread (`run_in_executor`), so the event loop is not blocked
today. A follow-up (redesign §8) should move OQMD behind an async `httpx`
client or into the job worker.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from app.core.logging import get_logger
from app.domain.material_card import MaterialCard, Source
from app.services.search.base import MaterialQuery
from app.services.search.mappers import oqmd_item_to_card

logger = get_logger(__name__)

OQMD_BASE = "https://oqmd.org/oqmdapi/formationenergy"
OQMD_TIMEOUT = int(os.environ.get("OQMD_TIMEOUT", "120"))


def _oqmd_get(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Materia/1.0 (materials search)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=OQMD_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


class OQMDProvider:
    source = Source.OQMD

    def is_available(self) -> bool:
        # No key/file needed; treat as always available (network checked at call).
        return True

    def search(self, query: MaterialQuery) -> list[MaterialCard]:
        limit = min(int(query.limit), 50)
        params: dict[str, str] = {
            "limit": str(limit),
            "offset": "0",
            "fields": "name,entry_id,composition,delta_e,stability,band_gap,spacegroup",
        }

        if query.formula:
            params["composition"] = query.formula
        elif query.elements:
            params["composition"] = "-".join(query.elements)
        elif query.element:
            params["composition"] = query.element

        if query.max_formation_e is not None:
            params["delta_e__lte"] = str(float(query.max_formation_e))

        url = f"{OQMD_BASE}?{urllib.parse.urlencode(params)}"
        data = _oqmd_get(url)
        if "error" in data:
            logger.warning("OQMD search error: %s", data["error"])
            return []

        raw = data.get("data") or data.get("results") or []
        return [oqmd_item_to_card(item, fallback_formula=query.formula) for item in raw]

    def get_structure(self, source_id: str):
        try:
            from pymatgen.core import Lattice, Structure
        except ImportError:
            logger.warning("pymatgen not installed")
            return None

        entry_id = str(source_id).replace("oqmd-", "").replace("oqmd:", "")
        data = _oqmd_get(f"https://oqmd.org/oqmdapi/entry/{entry_id}")
        if "error" in data:
            logger.warning("OQMD error: %s", data["error"])
            return None

        try:
            lattice = Lattice(data["unit_cell"])
            species: list = []
            coords: list = []
            for site in data["sites"]:
                left, right = site.split("@")
                species.append(left.strip())
                coords.append([float(x) for x in right.strip().split()])
            return Structure(lattice, species, coords, coords_are_cartesian=False)
        except Exception as e:
            logger.warning("OQMD structure parse error: %s", e)
            return None
