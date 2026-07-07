"""Layer 2 — the JSON API wrapper.

Everything the LANforge GUI can do flows through here:

* ``query()``      — any GET endpoint, with row normalization.
* ``command()``    — any of the 600+ CLI commands via ``POST /cli-json/<cmd>``.
* ``raw()``        — a raw one-line CLI command via ``POST /cli-json/raw``.
* ``help_text()``  — live per-command documentation from ``GET /help/<cmd>``.

Mutations are gated by the :class:`~lanforge_mcp.safety.SafetyGuard`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..connection.http_client import LFHttpClient
from ..errors import CommandError, translate_lanforge_message
from ..models import CommandResult
from ..safety import SafetyGuard
from .catalog import Catalog

logger = logging.getLogger(__name__)

#: Response keys that are metadata, not data rows.
META_KEYS = {"handler", "uri", "warnings", "errors", "empty", "text", "timestamp"}


def normalize_rows(payload: Any) -> list[dict[str, Any]]:
    """Flatten LANforge's quirky GET responses into a list of row dicts.

    LANforge returns either ``{"interfaces": [{"1.1.eth0": {...}}, ...]}``
    (list of single-key dicts), ``{"endpoint": {...}}`` (a single row), or a
    dict keyed by EID. Each row gains an ``"eid"`` key when it was keyed.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return rows

    def add_row(key: str | None, value: Any) -> None:
        if isinstance(value, dict):
            row = dict(value)
            if key is not None and "eid" not in row:
                row["eid"] = key
            rows.append(row)

    for section, value in payload.items():
        if section in META_KEYS:
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and len(item) == 1:
                    k, v = next(iter(item.items()))
                    add_row(k, v)
                elif isinstance(item, dict):
                    add_row(None, item)
        elif isinstance(value, dict):
            # Either a single row, or a dict keyed by EID.
            if value and all(isinstance(v, dict) for v in value.values()):
                for k, v in value.items():
                    add_row(k, v)
            else:
                add_row(None, value)
    return rows


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = _TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return _WS_RE.sub("\n\n", text).strip()


class JsonApi:
    def __init__(self, http: LFHttpClient, catalog: Catalog, safety: SafetyGuard):
        self.http = http
        self.catalog = catalog
        self.safety = safety

    # --------------------------------------------------------------- query

    async def query(
        self,
        endpoint: str,
        columns: list[str] | None = None,
        eids: list[str] | None = None,
        normalize: bool = True,
    ) -> dict[str, Any]:
        """GET any LANforge JSON endpoint.

        ``endpoint`` may be a bare table name (``port``) or a full path
        (``/port/1/1/eth0``). ``eids`` are appended as a comma list, which
        LANforge accepts for row selection. ``columns`` become ``?fields=``.
        """
        url = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        if eids:
            url = url.rstrip("/") + "/" + _eids_to_path(eids)
        params: dict[str, Any] = {}
        if columns:
            params["fields"] = ",".join(columns)
        payload = await self.http.get_json(url, params=params or None)
        out: dict[str, Any] = {"endpoint": url, "raw": payload}
        if normalize:
            rows = normalize_rows(payload)
            out["rows"] = rows
            out["row_count"] = len(rows)
        return out

    # ------------------------------------------------------------- command

    async def command(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        confirm: bool = False,
        system_id: str = "",
    ) -> CommandResult:
        """POST any CLI command to /cli-json/<command>.

        Unknown commands are forwarded anyway (newer LANforge versions add
        commands this build has never seen) — the GUI is the authority.
        """
        command = command.strip()
        if not command or " " in command:
            raise CommandError(
                f"'{command}' is not a valid command name; use raw_cli for full command lines."
            )
        params = dict(params or {})
        dry = self.safety.check_command(command, params, confirm=confirm, system=system_id)
        known = self.catalog.has_command(command)
        if dry:
            return CommandResult(
                command=command,
                params=params,
                ok=True,
                dry_run=True,
                status="dry-run: request not sent",
                warnings=[] if known else [f"'{command}' is not in the local catalog (may still be valid)"],
                response={"would_post": f"/cli-json/{command}", "body": params},
            )
        status, body = await self.http.post_json(f"/cli-json/{command}", params)
        return self._to_result(command, params, status, body, known)

    async def raw(self, line: str, *, confirm: bool = False, system_id: str = "") -> CommandResult:
        """Execute a raw one-line CLI command via /cli-json/raw."""
        line = line.strip()
        if not line:
            raise CommandError("Empty CLI line.")
        first_word = line.split()[0]
        dry = self.safety.check_command(first_word, {"raw": line}, confirm=confirm, system=system_id)
        if dry:
            return CommandResult(
                command=first_word,
                params={"cmd": line},
                ok=True,
                dry_run=True,
                status="dry-run: request not sent",
                response={"would_post": "/cli-json/raw", "body": {"cmd": line}},
            )
        status, body = await self.http.post_json("/cli-json/raw", {"cmd": line})
        return self._to_result(first_word, {"cmd": line}, status, body, known=True)

    def _to_result(
        self, command: str, params: dict[str, Any], status: int, body: Any, known: bool
    ) -> CommandResult:
        warnings: list[str] = []
        errors: list[str] = []
        if isinstance(body, dict):
            for key in ("warnings",):
                if body.get(key):
                    warnings.extend(str(w) for w in _as_list(body[key]))
            for key in ("errors", "error"):
                if body.get(key):
                    errors.extend(translate_lanforge_message(str(e)) for e in _as_list(body[key]))
        if not known:
            warnings.append(
                f"'{command}' is not in the local catalog; it was forwarded as-is. "
                "If it failed, check list_commands / command_help."
            )
        ok = status < 400 and not errors
        if status >= 400 and not errors:
            errors.append(f"HTTP {status} from LANforge GUI: {str(body)[:400]}")
        return CommandResult(
            command=command,
            params=params,
            ok=ok,
            status=f"HTTP {status}",
            warnings=warnings,
            errors=errors,
            response=body,
        )

    # ---------------------------------------------------------------- help

    async def help_text(self, command: str) -> str:
        """Fetch live CLI documentation for a command from the GUI."""
        html = await self.http.get_text(f"/help/{command.strip()}")
        return strip_html(html)[:8000]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _eids_to_path(eids: list[str]) -> str:
    """Map EIDs onto a LANforge URL path.

    ``["1", "1", "eth0"]``                  -> ``1/1/eth0`` (path components)
    ``["1.1.sta0000", "1.1.sta0001"]``      -> ``1/1/sta0000,sta0001``
    ``["sta0000"]``                          -> ``1/1/sta0000``
    LANforge selects rows per shelf/resource, so all EIDs must share one; the
    first shelf/resource group wins.
    """
    if len(eids) == 3 and all("." not in e for e in eids):
        return "/".join(str(e) for e in eids)
    groups: dict[tuple[str, str], list[str]] = {}
    for eid in eids:
        seg = str(eid).split(".")
        if len(seg) >= 3:
            key, port = (seg[0], seg[1]), ".".join(seg[2:])
        elif len(seg) == 2:
            key, port = ("1", seg[0]), seg[1]
        else:
            key, port = ("1", "1"), seg[0]
        groups.setdefault(key, []).append(port)
    (shelf, resource), ports = next(iter(groups.items()))
    return f"{shelf}/{resource}/{','.join(ports)}"
