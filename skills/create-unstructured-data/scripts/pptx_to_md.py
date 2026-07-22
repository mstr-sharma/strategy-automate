#!/usr/bin/env python3
"""Extract slide text from a .pptx into Markdown — stdlib only (zipfile + ElementTree).

Strategy's unstructured-data API (POST /api/nuggets?type=unstructuredData) accepts
PDF / DOCX / MD / TXT / EMAIL but NOT PowerPoint, so decks must be converted to a
text format first. This extractor turns each slide into a Markdown section:
title placeholder -> "## <title>", body text frames -> paragraphs / bullet lists,
tables -> Markdown tables, speaker notes (optional) -> a "> Notes:" block.

Usage:
    python3 pptx_to_md.py DECK.pptx [-o OUT.md] [--notes] [--title "Doc Title"]

Prints the output path on success. Stdout stays clean of content so callers can
chain it (e.g. create_unstructured.py imports convert() directly).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
NOTES_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"


def _slide_number(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _paragraph_text(para) -> str:
    """Concatenate all a:t runs of one a:p paragraph; a:br becomes a space."""
    parts = []
    for node in para.iter():
        if node.tag == f"{A_NS}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{A_NS}br":
            parts.append(" ")
    return "".join(parts).strip()


def _is_title_shape(shape) -> bool:
    ph = shape.find(f".//{P_NS}nvSpPr//{P_NS}ph")
    return ph is not None and ph.get("type") in ("title", "ctrTitle")


def _shape_lines(shape) -> list[str]:
    """One Markdown line per non-empty paragraph; indented paragraphs keep bullets."""
    lines = []
    for para in shape.iter(f"{A_NS}p"):
        text = _paragraph_text(para)
        if not text:
            continue
        ppr = para.find(f"{A_NS}pPr")
        level = int(ppr.get("lvl", "0")) if ppr is not None else 0
        # Heuristic: multi-paragraph text frames read as bullet lists; the
        # bullet-config XML (buChar/buAutoNum/buNone) is often inherited from
        # the layout/master, so we don't try to resolve it precisely.
        lines.append(("  " * level) + "- " + text)
    if len(lines) == 1:
        return [lines[0][2:]]  # single paragraph -> plain text, not a one-item list
    return lines


def _table_lines(graphic_frame) -> list[str]:
    rows = []
    for tr in graphic_frame.iter(f"{A_NS}tr"):
        cells = []
        for tc in tr.findall(f"{A_NS}tc"):
            cells.append(" ".join(filter(None, (_paragraph_text(p) for p in tc.iter(f"{A_NS}p")))))
        rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |",
             "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines


def _slide_to_md(xml_bytes: bytes, index: int) -> list[str]:
    root = ET.fromstring(xml_bytes)
    title = ""
    blocks: list[list[str]] = []
    tree_shapes = root.find(f"{P_NS}cSld/{P_NS}spTree")
    if tree_shapes is None:
        return []
    for shape in tree_shapes:
        if shape.tag == f"{P_NS}sp":
            if _is_title_shape(shape) and not title:
                title = " ".join(_shape_lines(shape)).lstrip("- ").strip()
                continue
            lines = _shape_lines(shape)
            if lines:
                blocks.append(lines)
        elif shape.tag == f"{P_NS}graphicFrame":
            lines = _table_lines(shape)
            if lines:
                blocks.append(lines)
    out = [f"## Slide {index}" + (f": {title}" if title else "")]
    for block in blocks:
        out.append("")
        out.extend(block)
    return out


def _notes_to_md(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    texts = []
    for para in root.iter(f"{A_NS}p"):
        text = _paragraph_text(para)
        # Notes pages embed the slide-number placeholder; drop bare numbers.
        if text and not text.isdigit():
            texts.append(text)
    if not texts:
        return []
    return ["", "> Notes: " + " ".join(texts)]


def _notes_part_for(zf: zipfile.ZipFile, slide_name: str) -> str | None:
    """Resolve the slide's notes part via its .rels file. Notes parts are numbered
    by creation order, NOT slide order, so notesSlideN.xml must never be paired
    with slideN.xml by number."""
    rels_name = re.sub(r"^ppt/slides/(slide\d+\.xml)$", r"ppt/slides/_rels/\1.rels", slide_name)
    if rels_name not in zf.namelist():
        return None
    root = ET.fromstring(zf.read(rels_name))
    for rel in root.iter(f"{R_NS}Relationship"):
        if rel.get("Type") == NOTES_REL:
            target = rel.get("Target", "")
            return os.path.normpath(os.path.join("ppt/slides", target)).replace(os.sep, "/")
    return None


def convert(pptx_path: str, out_path: str | None = None, *,
            include_notes: bool = False, doc_title: str | None = None) -> str:
    """Convert PPTX to Markdown; returns the output file path."""
    if not zipfile.is_zipfile(pptx_path):
        raise ValueError(f"not a .pptx (zip) file: {pptx_path}")
    if out_path is None:
        out_path = os.path.splitext(pptx_path)[0] + ".md"
    with zipfile.ZipFile(pptx_path) as zf:
        names = zf.namelist()
        slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=_slide_number)
        if not slides:
            raise ValueError(f"no slides found in {pptx_path}")
        md = ["# " + (doc_title or os.path.splitext(os.path.basename(pptx_path))[0])]
        for name in slides:
            index = _slide_number(name)
            md.append("")
            md.extend(_slide_to_md(zf.read(name), index))
            if include_notes:
                notes_name = _notes_part_for(zf, name)
                if notes_name and notes_name in names:
                    md.extend(_notes_to_md(zf.read(notes_name)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md).rstrip() + "\n")
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pptx", help="input .pptx path")
    ap.add_argument("-o", "--out", help="output .md path (default: alongside input)")
    ap.add_argument("--notes", action="store_true", help="include speaker notes")
    ap.add_argument("--title", help="document title (default: file name)")
    args = ap.parse_args()
    try:
        out = convert(args.pptx, args.out, include_notes=args.notes, doc_title=args.title)
    except (ValueError, OSError, ET.ParseError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    print(out)


if __name__ == "__main__":
    main()
