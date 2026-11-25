"""Build static data/spot_traps.json from docs/spot_traps/*.md using Python stdlib only."""
from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "spot_traps"
OUT_PATH = REPO_ROOT / "data" / "spot_traps.json"

PILLAR_DEFS = [
    ("p1", "Pillar 1: Chart & Timeframe Traps", "Chart & Timeframe"),
    ("p2", "Pillar 2: Liquidity, Heatmap & Order-Book Traps", "Liquidity & Heatmap"),
    ("p3", "Pillar 3: Derivatives & Flow Illusion Traps", "Derivatives & Flow"),
    ("p4", "Pillar 4: Session, Calendar & Behavioral Spot Traps", "Session & Behavioral"),
    ("bonus", "Bonus Essay: Chart & Regime Mindset", "Bonus Essay"),
]
PILLAR_KEY_BY_LABEL = {label: key for key, label, _ in PILLAR_DEFS}

BONUS_SUMMARY = {
    "bonus_b1": {
        "core_mistake": (
            "Treating classical triangle/trendline targets ($19K crash / $150K moon) "
            "as guaranteed prophecies instead of conditional regime maps."
        ),
        "key_defense": (
            "Separate condition from target, demand an explicit invalidation level, "
            "and prepare 'If-Then' plans instead of predictions."
        ),
    }
}


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]
    return val


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Parse minimal YAML frontmatter (scalars + single-line/multi-line lists) and return (meta, body)."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", raw, re.DOTALL)
    if not m:
        raise ValueError("Missing YAML frontmatter")
    fm_text, body = m.group(1), m.group(2).strip()
    meta: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in fm_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if current_list_key and re.match(r"^\s*-\s+", line):
            item_val = re.sub(r"^\s*-\s+", "", line)
            meta[current_list_key].append(_strip_quotes(item_val))
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        key = key.strip()
        val = rest.strip()
        if val == "":
            meta[key] = []
            current_list_key = key
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                meta[key] = []
            else:
                meta[key] = [_strip_quotes(p) for p in inner.split(",") if p.strip()]
        else:
            meta[key] = _strip_quotes(val)
    return meta, body


def parse_master_index(index_path: pathlib.Path) -> tuple[dict[str, Any], str, list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Extract metadata, chain of command, 7 guardrails, and roadmap table from 00_Master_Index.md."""
    raw = index_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)

    chain_of_command = ""
    m_chain = re.search(r"^>\s*\*\*(.+?)\*\*\s*$", body, re.MULTILINE)
    if m_chain:
        chain_of_command = m_chain.group(1).replace("**", "").strip()
    else:
        m_alt = re.search(r"^>\s*(.+)$", body, re.MULTILINE)
        if m_alt:
            chain_of_command = m_alt.group(1).replace("**", "").strip()

    guardrails: list[dict[str, Any]] = []
    m_gr = re.search(
        r"###\s+Non-Negotiable 1\.0x Spot Guardrails\s*\r?\n(.*?)(?:\r?\n---|\Z)",
        body,
        re.DOTALL,
    )
    if m_gr:
        for line in m_gr.group(1).splitlines():
            gm = re.match(r"^(\d+)\.\s+\*\*(.+?)\*\*\s*(.+)$", line.strip())
            if gm:
                title = gm.group(2).rstrip(":").strip()
                guardrails.append({
                    "num": int(gm.group(1)),
                    "title": title,
                    "text": gm.group(3).strip(),
                })

    roadmap: dict[str, dict[str, str]] = {}
    for line in body.splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells: list[str] = []
        buf: list[str] = []
        in_code = False
        for ch in s[1:-1]:
            if ch == "`":
                in_code = not in_code
                buf.append(ch)
            elif ch == "|" and not in_code:
                cells.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        cells.append("".join(buf).strip())
        if len(cells) == 5:
            cm = re.match(r"^\*\*(\d{2})\*\*$", cells[0])
            if cm:
                code = cm.group(1)
                roadmap[code] = {
                    "core_mistake": cells[3],
                    "key_defense": cells[4],
                }

    return meta, chain_of_command, guardrails, roadmap


def extract_quick_steps(body: str, is_bonus: bool) -> list[dict[str, Any]]:
    """Extract numbered actionable protocol steps from Section 5 (traps) or final rules section (B1)."""
    if is_bonus:
        m_sec = re.search(r"^##\s+How to Read Extreme Projections.*?\r?\n(.*)$", body, re.DOTALL | re.MULTILINE)
    else:
        m_sec = re.search(r"^##\s+5\.\s+.*?\r?\n(.*)$", body, re.DOTALL | re.MULTILINE)
    if not m_sec:
        return []

    sec_lines = m_sec.group(1).splitlines()
    steps: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    detail_lines: list[str] = []

    def flush() -> None:
        nonlocal current, detail_lines
        if current is None:
            return
        detail = " ".join(part for part in detail_lines if part).strip()
        current["detail"] = detail
        steps.append(current)
        current = None
        detail_lines = []

    for raw_line in sec_lines:
        stripped = raw_line.strip()
        m_num = re.match(r"^(\d+)\.\s+\*\*(.+?)\*\*\s*(.*)$", stripped)
        if m_num:
            flush()
            step_num = int(m_num.group(1))
            step_title = m_num.group(2).strip().rstrip(".")
            tail = re.sub(r"^\*[^*]+\*\s*", "", m_num.group(3).strip()).strip()
            current = {"num": step_num, "title": step_title, "detail": ""}
            if tail:
                detail_lines.append(tail)
        elif current is not None:
            if stripped.startswith("## ") or stripped == "---":
                flush()
                break
            if stripped:
                # Preserve non-numbered bullets and strip blockquote prefixes cleanly
                cleaned = re.sub(r"^-\s+", "• ", stripped)
                cleaned = re.sub(r"^>\s+", "", cleaned)
                detail_lines.append(cleaned)
    flush()
    return steps


def _save_json_atomic(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def build_bundle(docs_dir: pathlib.Path = DOCS_DIR, out_path: pathlib.Path = OUT_PATH) -> dict[str, Any]:
    """Compile docs/spot_traps markdown guides into data/spot_traps.json."""
    index_meta, chain_of_command, guardrails, roadmap = parse_master_index(docs_dir / "00_Master_Index.md")

    md_files = sorted(
        p for p in docs_dir.glob("*.md")
        if p.name != "00_Master_Index.md"
    )
    items: list[dict[str, Any]] = []
    for path in md_files:
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        item_id = str(meta["id"])
        is_bonus = item_id.startswith("bonus_")
        if item_id.startswith("trap_"):
            code = item_id.split("_", 1)[1].zfill(2)
        elif is_bonus:
            code = item_id.split("_", 1)[1].upper()
        else:
            code = item_id.upper()

        full_title = str(meta["title"]).strip()
        if ":" in full_title:
            short_title, subtitle = [part.strip() for part in full_title.split(":", 1)]
        else:
            short_title, subtitle = full_title, ""

        pillar_label = str(meta["pillar"]).strip()
        pillar_key = PILLAR_KEY_BY_LABEL.get(pillar_label, "bonus" if is_bonus else "p1")

        summary_src = roadmap.get(code) or BONUS_SUMMARY.get(item_id, {})
        quick_steps = extract_quick_steps(body, is_bonus=is_bonus)

        items.append({
            "id": item_id,
            "code": code,
            "sort_order": 100 + len(items) if is_bonus else int(code),
            "title": full_title,
            "short_title": short_title,
            "subtitle": subtitle,
            "pillar": pillar_label,
            "pillar_key": pillar_key,
            "mindset": str(meta.get("mindset", "1.0x_spot_only")),
            "regime_risk": list(meta.get("regime_risk", ["RED", "AMBER", "GREEN"])),
            "phase_link": list(meta.get("phase_link", [])),
            "related_traps": list(meta.get("related_traps", [])),
            "tags": list(meta.get("tags", [])),
            "core_mistake": summary_src.get("core_mistake", ""),
            "key_defense": summary_src.get("key_defense", ""),
            "quick_steps": quick_steps,
            "body_md": body,
        })

    items.sort(key=lambda x: x["sort_order"])
    for item in items:
        item.pop("sort_order", None)

    counts: dict[str, int] = {}
    for item in items:
        counts[item["pillar_key"]] = counts.get(item["pillar_key"], 0) + 1

    pillars = [
        {
            "key": key,
            "label": label,
            "short_label": short_label,
            "count": counts.get(key, 0),
        }
        for key, label, short_label in PILLAR_DEFS
    ]

    bundle = {
        "version": str(index_meta.get("version", "4.0")),
        "updated": str(index_meta.get("updated", "2026-11-25")),
        "series_title": str(index_meta.get("series", "The Spot Trader's Field Guide to Market Traps")),
        "mindset": str(index_meta.get("mindset", "1.0x_spot_only")),
        "chain_of_command": chain_of_command,
        "guardrails": guardrails,
        "pillars": pillars,
        "items": items,
    }
    _save_json_atomic(out_path, bundle)
    return bundle


if __name__ == "__main__":
    result = build_bundle()
    print(
        f"Built {OUT_PATH.relative_to(REPO_ROOT)}: "
        f"{len(result['items'])} items, {len(result['guardrails'])} guardrails, "
        f"{OUT_PATH.stat().st_size:,} bytes"
    )
