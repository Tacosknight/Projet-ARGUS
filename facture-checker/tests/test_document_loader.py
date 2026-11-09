import tempfile
import unittest
from pathlib import Path

from PIL import Image

from core.document_loader import iter_document_pages


class TestDocumentLoader(unittest.TestCase):
    def test_image_and_multipage_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "facture test.png"
            Image.new("RGB", (120, 180), "white").save(image_path)
            image_pages = list(iter_document_pages(image_path))
            self.assertEqual((image_pages[0][0], image_pages[0][1]), (1, 1))
            self.assertEqual(image_pages[0][2].shape[:2], (180, 120))

            pdf_path = root / "facture multipage.pdf"
            pages = [Image.new("RGB", (100, 140), "white"), Image.new("RGB", (100, 140), "gray")]
            pages[0].save(pdf_path, save_all=True, append_images=pages[1:])
            pdf_pages = list(iter_document_pages(pdf_path, pdf_scale=1.0))
            self.assertEqual([(number, total) for number, total, _ in pdf_pages], [(1, 2), (2, 2)])


if __name__ == "__main__":
    unittest.main()
