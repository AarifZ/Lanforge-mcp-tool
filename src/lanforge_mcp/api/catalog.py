"""Offline catalogs of LANforge CLI commands and JSON GET endpoints.

The JSON files in ``lanforge_mcp/data`` are generated from the official
``lanforge_client/lanforge_api.py`` by ``tools/generate_catalog.py``. They are
advisory: discovery/search/validation hints for the LLM. Unknown commands are
still forwarded to the GUI, so a newer LANforge keeps working unchanged.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any, ClassVar


def _load(name: str) -> dict[str, Any]:
    with resources.files("lanforge_mcp.data").joinpath(name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


class Catalog:
    def __init__(self) -> None:
        self._commands: dict[str, Any] = _load("commands.json")["commands"]
        self._endpoints: dict[str, Any] = _load("endpoints.json")["endpoints"]

    # ------------------------------------------------------------- commands

    @property
    def command_names(self) -> list[str]:
        return sorted(self._commands)

    def has_command(self, name: str) -> bool:
        return name in self._commands

    def command(self, name: str) -> dict[str, Any] | None:
        return self._commands.get(name)

    def search_commands(self, search: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """Substring search over command names, parameter names and descriptions."""
        needle = search.strip().lower()
        hits: list[dict[str, Any]] = []
        for name in sorted(self._commands):
            info = self._commands[name]
            if needle and not (
                needle in name.lower()
                or needle in info.get("description", "").lower()
                or any(needle in p["name"].lower() for p in info.get("parameters", []))
            ):
                continue
            hits.append(
                {
                    "command": name,
                    "description": info.get("description", ""),
                    "parameters": [p["name"] for p in info.get("parameters", [])],
                    "doc_url": info.get("doc_url", ""),
                }
            )
            if len(hits) >= limit:
                break
        return hits

    def command_schema(self, name: str) -> dict[str, Any] | None:
        """JSON-Schema-ish description of one command's parameters."""
        info = self._commands.get(name)
        if info is None:
            return None
        properties = {
            p["name"]: {
                "type": p.get("type", "string"),
                "description": p.get("description", ""),
            }
            for p in info.get("parameters", [])
        }
        return {
            "command": name,
            "description": info.get("description", ""),
            "doc_url": info.get("doc_url", ""),
            "endpoint": f"/cli-json/{name}",
            "properties": properties,
        }

    # ------------------------------------------------------------ endpoints

    @property
    def endpoint_names(self) -> list[str]:
        return sorted(self._endpoints)

    def endpoint(self, name: str) -> dict[str, Any] | None:
        return self._endpoints.get(name.strip("/").split("/")[0])

    #: Endpoints documented by the API client but missing on some GUI builds,
    #: with the working alternative (verified live on LANforge 5.5.2.1).
    ENDPOINT_NOTES: ClassVar[dict[str, str]] = {
        "stations": "404s on some LANforge builds; query 'port' instead (WiFi stations are port rows).",
    }

    def search_endpoints(self, search: str = "", limit: int = 60) -> list[dict[str, Any]]:
        needle = search.strip().lower()
        hits = []
        for name in sorted(self._endpoints):
            info = self._endpoints[name]
            if needle and needle not in name.lower() and not any(
                needle in c.lower() for c in info.get("columns", [])
            ):
                continue
            hit = {
                "endpoint": name,
                "url": info.get("url", f"/{name}"),
                "columns": info.get("columns", []),
            }
            if name in self.ENDPOINT_NOTES:
                hit["note"] = self.ENDPOINT_NOTES[name]
            hits.append(hit)
            if len(hits) >= limit:
                break
        return hits


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog()
