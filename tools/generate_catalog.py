#!/usr/bin/env python3
"""Generate command/endpoint catalogs from the official LANforge API client.

Parses ``lanforge_client/lanforge_api.py`` from a lanforge-scripts checkout with
the ``ast`` module (no import, no execution) and emits:

* ``src/lanforge_mcp/data/commands.json``  — every CLI command reachable via
  ``POST /cli-json/<command>`` with its parameters, types and help text.
* ``src/lanforge_mcp/data/endpoints.json`` — every GET endpoint with its URL
  variants and queryable column names.

The catalogs are advisory: lanforge-mcp forwards unknown commands unchanged, so
a newer LANforge keeps working without regeneration. Regenerate with:

    python tools/generate_catalog.py --repo /path/to/lanforge-scripts
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ANNOTATION_TYPES = {
    "str": "string",
    "int": "integer",
    "bool": "boolean",
    "float": "number",
    "list": "array",
    "dict": "object",
}

SKIP_PARAMS = {"self", "response_json_list", "debug", "suppress_related_commands", "errors_warnings"}

# Doc lines in the generated client look like:  ":param alias: Name of endpoint."
PARAM_DOC_RE = re.compile(r":param\s+(\w+):\s*(.*)")
URL_LINE_RE = re.compile(r"^\s*(/[\w$/\-]+)\s*$")


def annotation_to_type(node: ast.expr | None) -> str:
    if node is None:
        return "string"
    if isinstance(node, ast.Name):
        return ANNOTATION_TYPES.get(node.id, "string")
    if isinstance(node, ast.Attribute):
        return "string"
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return ANNOTATION_TYPES.get(node.value.id, "string")
    return "string"


def extract_param_docs(docstring: str | None) -> dict[str, str]:
    if not docstring:
        return {}
    return {m.group(1): m.group(2).strip() for m in PARAM_DOC_RE.finditer(docstring)}


def first_doc_sentence(docstring: str | None) -> str:
    """Pull a usable one-line description out of a generated docstring."""
    if not docstring:
        return ""
    for line in docstring.splitlines():
        line = line.strip()
        if not line or set(line) <= {"-", " "}:
            continue
        if line.startswith((":param", "Example", "https://", "http://", "*")):
            continue
        # Skip code-example lines (assignments, calls, comments).
        if "=" in line or "(" in line or line.startswith("#"):
            continue
        if not line[0].isupper():
            continue
        return line[:300]
    return ""


def extract_commands(tree: ast.Module) -> dict[str, Any]:
    """Collect post_* methods of LFJsonCommand -> CLI command catalog."""
    commands: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "LFJsonCommand"):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if not item.name.startswith("post_") or item.name.endswith("_map"):
                continue
            cmd = item.name[len("post_"):]
            doc = ast.get_docstring(item)
            param_docs = extract_param_docs(doc)
            params = []
            args = item.args
            defaults_offset = len(args.args) - len(args.defaults)
            for i, arg in enumerate(args.args):
                if arg.arg in SKIP_PARAMS:
                    continue
                params.append(
                    {
                        "name": arg.arg,
                        "type": annotation_to_type(arg.annotation),
                        "description": param_docs.get(arg.arg, ""),
                        "has_default": i >= defaults_offset,
                    }
                )
            commands[cmd] = {
                "description": first_doc_sentence(doc)
                or f"LANforge CLI command '{cmd}' (POST /cli-json/{cmd})",
                "doc_url": f"https://www.candelatech.com/lfcli_ug.php#{cmd}",
                "parameters": params,
            }
    return commands


def extract_endpoints(tree: ast.Module) -> dict[str, Any]:
    """Collect get_* methods of LFJsonQuery -> GET endpoint catalog.

    URL variants and column names live in the block docstrings that precede each
    method inside the class body, e.g. lines like ``/port/$shelf_id/...`` and a
    'When requesting specific column names' section.
    """
    endpoints: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "LFJsonQuery"):
            continue
        pending_doc = ""
        for item in node.body:
            # Bare string expressions are the notes blocks preceding methods.
            if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                pending_doc = item.value.value
                continue
            if not (isinstance(item, ast.FunctionDef) and item.name.startswith("get_")):
                continue
            name = item.name[len("get_"):]
            urls = URL_LINE_RE.findall(pending_doc)
            columns: list[str] = []
            in_cols = False
            for line in pending_doc.splitlines():
                stripped = line.strip()
                if stripped.startswith("When requesting specific column names"):
                    in_cols = True
                    continue
                if in_cols:
                    if stripped.startswith("Example URL") or not stripped:
                        if stripped.startswith("Example URL"):
                            in_cols = False
                        continue
                    columns.extend(c.strip() for c in stripped.split(",") if c.strip())
            base_url = urls[0] if urls else f"/{name}/"
            endpoints[name] = {
                "url": base_url.rstrip("/") or f"/{name}",
                "url_variants": urls,
                "columns": sorted(set(columns)),
                "description": f"LANforge JSON GET endpoint {base_url}",
            }
            pending_doc = ""
    return endpoints


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to a lanforge-scripts checkout")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "src" / "lanforge_mcp" / "data"),
        help="Output directory for the JSON catalogs",
    )
    ns = parser.parse_args()

    api_py = Path(ns.repo) / "lanforge_client" / "lanforge_api.py"
    if not api_py.is_file():
        print(f"error: {api_py} not found", file=sys.stderr)
        return 2

    tree = ast.parse(api_py.read_text(encoding="utf-8"))
    commands = extract_commands(tree)
    endpoints = extract_endpoints(tree)

    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "commands.json").write_text(
        json.dumps({"source": "lanforge_client/lanforge_api.py", "commands": commands}, indent=1),
        encoding="utf-8",
    )
    (out / "endpoints.json").write_text(
        json.dumps({"source": "lanforge_client/lanforge_api.py", "endpoints": endpoints}, indent=1),
        encoding="utf-8",
    )
    print(f"wrote {len(commands)} commands and {len(endpoints)} endpoints to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
