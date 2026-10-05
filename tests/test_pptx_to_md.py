import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "create-unstructured-data", "scripts"))

import pptx_to_md  # noqa: E402

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def slide(title: str, *paragraphs: str, prolog: str = "") -> bytes:
    body = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in paragraphs)
    return (f'{prolog}<p:sld xmlns:a="{A}" xmlns:p="{P}"><p:cSld><p:spTree>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="1" name="t"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
            f'<p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="b"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:txBody>{body}</p:txBody></p:sp>'
            f'</p:spTree></p:cSld></p:sld>').encode()


class PptxToMarkdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def deck(self, parts: dict) -> str:
        path = os.path.join(self.tmp.name, "deck.pptx")
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in parts.items():
                zf.writestr(name, data)
        return path

    def test_slides_become_markdown_in_order(self):
        path = self.deck({"ppt/slides/slide2.xml": slide("Second", "b1", "b2"),
                          "ppt/slides/slide1.xml": slide("First", "only line")})
        out = pptx_to_md.convert(path, os.path.join(self.tmp.name, "deck.md"), doc_title="Deck")
        text = open(out, encoding="utf-8").read()
        self.assertTrue(text.startswith("# Deck"))
        self.assertLess(text.index("First"), text.index("Second"))
        self.assertIn("- b1", text)
        self.assertIn("only line", text)

    def test_entity_declarations_are_refused(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        path = self.deck({"ppt/slides/slide1.xml": slide("x", "&lol;", prolog=bomb)})
        with self.assertRaisesRegex(ValueError, "DTD or entities"):
            pptx_to_md.convert(path, os.path.join(self.tmp.name, "out.md"))

    def test_oversized_parts_are_refused(self):
        path = self.deck({"ppt/slides/slide1.xml": slide("x", "y" * 2000)})
        with mock.patch.object(pptx_to_md, "MAX_PART_BYTES", 1000):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                pptx_to_md.convert(path, os.path.join(self.tmp.name, "out.md"))
        with mock.patch.object(pptx_to_md, "MAX_TOTAL_BYTES", 1000):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                pptx_to_md.convert(path, os.path.join(self.tmp.name, "out.md"))

    def test_not_a_deck(self):
        bad = os.path.join(self.tmp.name, "x.pptx")
        with open(bad, "w") as f:
            f.write("not a zip")
        with self.assertRaises(ValueError):
            pptx_to_md.convert(bad)


if __name__ == "__main__":
    unittest.main()
