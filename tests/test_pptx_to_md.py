import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

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
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("# Deck"))
        self.assertLess(text.index("First"), text.index("Second"))
        self.assertIn("- b1", text)
        self.assertIn("only line", text)

    def test_entity_declarations_are_refused(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        path = self.deck({"ppt/slides/slide1.xml": slide("x", "&lol;", prolog=bomb)})
        with self.assertRaisesRegex(ValueError, "DTD or entities"):
            pptx_to_md.convert(path, os.path.join(self.tmp.name, "out.md"))

    def test_entity_declarations_are_refused_in_utf16_too(self):
        bomb = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        xml = slide("x", "&lol;", prolog=bomb).decode()
        for encoded in (xml.encode("utf-16"), xml.encode("utf-16-le"), xml.encode("utf-16-be")):
            path = self.deck({"ppt/slides/slide1.xml": encoded})
            with self.assertRaisesRegex(ValueError, "DTD or entities"):
                pptx_to_md.convert(path, os.path.join(self.tmp.name, "out.md"))

    def test_utf16_and_bom_parts_without_a_dtd_convert(self):
        xml = slide("Título", "naïve café").decode()
        for encoded in (xml.encode("utf-16"), b"\xef\xbb\xbf" + xml.encode("utf-8")):
            path = self.deck({"ppt/slides/slide1.xml": encoded})
            out = pptx_to_md.convert(path, os.path.join(self.tmp.name, "u.md"))
            with open(out, encoding="utf-8") as f:
                self.assertIn("naïve café", f.read())

    def test_notes_with_an_absolute_target_are_found(self):
        notes = (f'<p:notes xmlns:a="{A}" xmlns:p="{P}"><p:cSld><p:spTree><p:sp><p:txBody>'
                 f'<a:p><a:r><a:t>Say this</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>')
        rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'notesSlide" Target="/ppt/notesSlides/notesSlide7.xml"/></Relationships>')
        path = self.deck({"ppt/slides/slide1.xml": slide("T", "b"), "ppt/slides/_rels/slide1.xml.rels": rels,
                          "ppt/notesSlides/notesSlide7.xml": notes})
        out = pptx_to_md.convert(path, os.path.join(self.tmp.name, "n.md"), include_notes=True)
        with open(out, encoding="utf-8") as f:
            self.assertIn("> Notes: Say this", f.read())

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
