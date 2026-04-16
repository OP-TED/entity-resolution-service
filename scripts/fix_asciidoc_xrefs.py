"""Post-process generated AsciiDoc to fix broken cross-references.

The openapi-generator asciidoc backend sanitizes model names for anchors
(stripping dashes, underscores, etc.) but leaves $ref-derived xrefs
unsanitized. This script reconciles the two by rewriting <<xref>> targets
to match their corresponding [#anchor] ids.

Additionally, every model xref is given explicit display text
(``<<id,Title>>``) so that Asciidoctor does not fall back to
"Section X.X" rendering when ``:numbered:`` / ``:sectnums:`` is active.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PRIMITIVE_TYPES = frozenset(
    {
        "string",
        "String",
        "integer",
        "Integer",
        "number",
        "Number",
        "boolean",
        "Boolean",
        "object",
        "Object",
        "Map",
        "AnyType",
        "Date",
        "BigDecimal",
        "oas_any_type_not_mapped",
        "anyOf",
    }
)

_ANCHOR_HEADING_RE = re.compile(r"\[#(\w+)\]\n=== (.+)")
_XREF_RE = re.compile(r"<<([^,>]*?)(?:,([^>]*?))?>>")


def _sanitize(name: str) -> str:
    """Reproduce the generator's classname sanitization: strip non-alnum."""
    return re.sub(r"[^a-zA-Z0-9]", "", name)


def _strip_html_entities(name: str) -> str:
    return name.replace("&lt;", "").replace("&gt;", "")


def fix_file(path: Path) -> int:
    """Fix broken xrefs in a single AsciiDoc file. Returns number of fixes."""
    text = path.read_text(encoding="utf-8")

    # Single pass: collect anchor ids and their heading titles.
    anchor_titles: dict[str, str] = {}
    anchor_lookup: dict[str, str] = {}
    for m in _ANCHOR_HEADING_RE.finditer(text):
        anchor_id, title = m.group(1), m.group(2).strip()
        anchor_titles[anchor_id] = title
        anchor_lookup[anchor_id] = anchor_id
        anchor_lookup[_sanitize(anchor_id)] = anchor_id

    fixes = 0

    def _replace_xref(m: re.Match) -> str:
        nonlocal fixes
        ref, existing_label = m.group(1), m.group(2)

        if not ref.strip():
            fixes += 1
            return "-"

        clean_ref = _strip_html_entities(ref)

        if clean_ref in PRIMITIVE_TYPES:
            fixes += 1
            return f"`{clean_ref}`"

        # Resolve target: try exact match, then sanitized form.
        target = anchor_lookup.get(ref) or anchor_lookup.get(_sanitize(ref))
        if target is None:
            return m.group(0)

        label = existing_label or anchor_titles.get(target, target)
        fixes += 1
        return f"<<{target},{label}>>"

    text = _XREF_RE.sub(_replace_xref, text)
    path.write_text(text, encoding="utf-8")
    return fixes


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.adoc> [file2.adoc ...]", file=sys.stderr)
        sys.exit(1)

    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"  SKIP {p} (not found)", file=sys.stderr)
            continue
        n = fix_file(p)
        print(f"  {p.name}: {n} xrefs fixed")


if __name__ == "__main__":
    main()
