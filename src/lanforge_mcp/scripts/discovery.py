"""Discover lanforge-scripts py-scripts and derive JSON schemas from argparse.

No manual work is needed when new scripts appear: discovery scans the
configured scripts directory (a local checkout of greearb/lanforge-scripts, or
``/home/lanforge/scripts/py-scripts`` on the LANforge box over SFTP), and the
schema for each script is extracted from its ``add_argument`` calls with the
``ast`` module — the script is never imported or executed during discovery.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..connection.ssh_client import LFSshClient
from ..errors import ScriptError
from ..models import ScriptsConfig

logger = logging.getLogger(__name__)

_PURPOSE_RE = re.compile(r"PURPOSE:?\s*(.+?)(?:\n\s*\n|\nNOTES|\nEXAMPLE|\Z)", re.S | re.I)

#: Scripts that are libraries/utilities rather than runnable tests.
_SKIP_NAMES = {"__init__.py", "lf_json_util.py", "lf_logger_config.py"}


@dataclass
class ScriptInfo:
    name: str
    path: str
    location: str  # "local" | "remote"
    summary: str = ""
    schema: dict[str, Any] | None = None  # lazily extracted
    source_loaded: bool = field(default=False, repr=False)


def _literal(node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _type_name(node: ast.expr | None) -> str:
    if isinstance(node, ast.Name):
        return {"int": "integer", "float": "number", "str": "string", "bool": "boolean"}.get(
            node.id, "string"
        )
    return "string"


def extract_argparse_schema(source: str) -> dict[str, Any]:
    """Build a JSON-Schema-like description of a script's CLI arguments."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ScriptError(f"Script has a syntax error and cannot be parsed: {exc}") from exc

    properties: dict[str, Any] = {}
    required: list[str] = []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        options = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        long_opts = [o for o in options if o.startswith("--")]
        if not long_opts:
            continue  # positional or short-only; py-scripts use long options
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        dest = None
        if "dest" in kw:
            dest = _literal(kw["dest"])
        if not dest:
            dest = long_opts[0].lstrip("-").replace("-", "_")

        action = _literal(kw["action"]) if "action" in kw else None
        prop: dict[str, Any] = {
            "flag": long_opts[0],
            "type": "boolean" if action in ("store_true", "store_false") else _type_name(kw.get("type")),
        }
        if action in ("store_true", "store_false"):
            prop["is_flag"] = True
        if "help" in kw:
            help_text = _literal(kw["help"])
            if isinstance(help_text, str):
                prop["description"] = " ".join(help_text.split())[:400]
        if "default" in kw:
            default = _literal(kw["default"])
            if default is not None:
                prop["default"] = default
        if "choices" in kw:
            choices = _literal(kw["choices"])
            if isinstance(choices, (list, tuple)):
                prop["choices"] = list(choices)
        if "action" in kw and action == "append":
            prop["type"] = "array"
        if _literal(kw.get("required", ast.Constant(value=False))) is True:
            required.append(dest)
        properties[dest] = prop

    return {"type": "object", "properties": properties, "required": required}


def extract_summary(source: str) -> str:
    """First PURPOSE paragraph of the module docstring, or its first line."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    doc = ast.get_docstring(tree) or ""
    m = _PURPOSE_RE.search(doc)
    if m:
        return " ".join(m.group(1).split())[:400]
    for line in doc.splitlines():
        line = line.strip()
        if line and not line.upper().startswith("NAME"):
            return line[:400]
    return ""


class ScriptRegistry:
    """Finds scripts and lazily extracts their schemas."""

    def __init__(self, config: ScriptsConfig, ssh: LFSshClient | None = None):
        self.config = config
        self.ssh = ssh
        self._scripts: dict[str, ScriptInfo] = {}
        self._discovered = False

    # ----------------------------------------------------------- discovery

    def _local_dir(self) -> Path | None:
        if not self.config.local_path:
            return None
        base = Path(self.config.local_path).expanduser()
        # Accept either the repo root or the py-scripts directory itself.
        if (base / "py-scripts").is_dir():
            return base / "py-scripts"
        return base if base.is_dir() else None

    async def discover(self, refresh: bool = False) -> list[ScriptInfo]:
        if self._discovered and not refresh:
            return sorted(self._scripts.values(), key=lambda s: s.name)
        self._scripts.clear()

        mode = self.config.mode
        local_dir = self._local_dir()
        if mode in ("auto", "local") and local_dir is not None:
            for path in sorted(local_dir.glob("*.py")):
                if path.name in _SKIP_NAMES:
                    continue
                self._scripts[path.stem] = ScriptInfo(
                    name=path.stem, path=str(path), location="local"
                )
        if not self._scripts and mode in ("auto", "remote") and self.ssh is not None:
            result = await self.ssh.exec(
                f"ls -1 {self.config.remote_path}/*.py 2>/dev/null", timeout=30
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.rsplit("/", 1)[-1] in _SKIP_NAMES:
                    continue
                name = line.rsplit("/", 1)[-1][:-3]
                self._scripts[name] = ScriptInfo(name=name, path=line, location="remote")
        self._discovered = True
        return sorted(self._scripts.values(), key=lambda s: s.name)

    async def get(self, name: str) -> ScriptInfo:
        await self.discover()
        name = name.removesuffix(".py")
        if name not in self._scripts:
            raise ScriptError(
                f"Script '{name}' not found.",
                details={"known_count": len(self._scripts)},
                hint="Call list_scripts to see available scripts; configure scripts.local_path "
                "to a lanforge-scripts checkout if none are found.",
            )
        return self._scripts[name]

    async def _read_source(self, info: ScriptInfo) -> str:
        if info.location == "local":
            return Path(info.path).read_text(encoding="utf-8", errors="replace")
        if self.ssh is None:
            raise ScriptError("Remote script access requires an SSH connection.")
        return await self.ssh.read_file(info.path)

    async def load_schema(self, name: str) -> ScriptInfo:
        info = await self.get(name)
        if not info.source_loaded:
            source = await self._read_source(info)
            info.schema = extract_argparse_schema(source)
            info.summary = extract_summary(source)
            info.source_loaded = True
        return info

    async def search(self, search: str = "", limit: int = 40) -> list[dict[str, Any]]:
        scripts = await self.discover()
        needle = search.strip().lower()
        out = []
        for info in scripts:
            if needle and needle not in info.name.lower():
                continue
            out.append({"script": info.name, "location": info.location, "path": info.path})
            if len(out) >= limit:
                break
        return out
