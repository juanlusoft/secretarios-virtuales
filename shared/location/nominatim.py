from __future__ import annotations

import httpx

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_HEADERS = {"User-Agent": "secretarios-virtuales/1.0 (contact@example.com)"}


class NominatimClient:
    async def reverse_geocode(self, lat: float, lon: float) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "json"},
                headers=_HEADERS,
            )
        if resp.status_code != 200:
            return f"Error geocodificando: HTTP {resp.status_code}"
        data = resp.json()
        return data.get("display_name", f"{lat},{lon}")

    async def nearby(self, lat: float, lon: float, query: str, radius_m: int = 1000) -> str:
        overpass_q = f"""
[out:json][timeout:15];
(
  node(around:{radius_m},{lat},{lon})[name][amenity];
  node(around:{radius_m},{lat},{lon})[name][shop];
  node(around:{radius_m},{lat},{lon})[name][tourism];
);
out body 20;
"""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(_OVERPASS_URL, data={"data": overpass_q}, headers=_HEADERS)
        if resp.status_code != 200:
            return f"Error consultando Overpass: HTTP {resp.status_code}"
        data = resp.json()
        elements = data.get("elements", [])
        if not elements:
            return f"No encontré lugares cerca ({radius_m}m)."

        q_lower = query.lower()
        if q_lower:
            filtered = [e for e in elements if q_lower in (e.get("tags", {}).get("name", "") + " " + e.get("tags", {}).get("amenity", "") + " " + e.get("tags", {}).get("shop", "")).lower()]
            elements = filtered or elements

        lines = [f"Lugares cercanos ({radius_m}m) a tu ubicación:"]
        for e in elements[:10]:
            tags = e.get("tags", {})
            name = tags.get("name", "Sin nombre")
            kind = tags.get("amenity") or tags.get("shop") or tags.get("tourism") or "lugar"
            e_lat = e.get("lat", lat)
            e_lon = e.get("lon", lon)
            lines.append(f"• **{name}** ({kind}) — maps.google.com/?q={e_lat},{e_lon}")
        return "\n".join(lines)
