import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.pdf_native import native_pdf_page


def make_pdf(path, streams, rotations=None):
    """Construit un PDF synthétique sans bibliothèque externe."""
    rotations = rotations or [0] * len(streams)
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', None,
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    page_ids = []
    for stream, rotation in zip(streams, rotations):
        page_id = len(objects) + 1
        page_ids.append(page_id)
        content_id = page_id + 1
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 400] /Rotate {rotation} /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>'.encode())
        objects.append(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
    objects[1] = ('<< /Type /Pages /Count %d /Kids [%s] >>' % (len(page_ids), ' '.join(f'{i} 0 R' for i in page_ids))).encode()
    result = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        result.extend(f'{offset:010} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(result)


TEXT = b'''BT /F1 12 Tf
1 0 0 1 30 350 Tm (Facture numero 123456789) Tj
1 0 0 1 30 310 Tm (Client Exemple Nom Prenom) Tj
1 0 0 1 30 270 Tm (Montant total 1234 euros) Tj
1 0 0 1 240 270 Tm (Paiement valide) Tj
ET'''


class NativePdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.pdf'

    def test_native_columns_and_geometry(self):
        make_pdf(self.path, [TEXT])
        blocks, reason = native_pdf_page(self.path, 1)
        self.assertEqual(reason, 'native_pdf')
        self.assertTrue(any('Facture' in b['text'] for b in blocks))
        self.assertTrue(any('Paiement' in b['text'] for b in blocks))
        facture = next(b for b in blocks if 'Facture' in b['text'])
        self.assertAlmostEqual(facture['box'][0][0], 60, delta=4)
        self.assertTrue(70 < facture['box'][0][1] < 110)
        self.assertEqual(facture['source'], 'native_pdf')
        self.assertTrue(all(0 <= p <= 800 for b in blocks for pt in b['box'] for p in pt))

    def test_multipage_fallback_and_bad_page(self):
        make_pdf(self.path, [TEXT, b'', b'BT /F1 12 Tf 20 300 Td (short) Tj ET'])
        self.assertIsNotNone(native_pdf_page(self.path, 1)[0])
        self.assertIsNone(native_pdf_page(self.path, 2)[0])
        self.assertIsNone(native_pdf_page(self.path, 3)[0])
        self.assertEqual(native_pdf_page(self.path, 0), (None, 'invalid_page_number'))
        self.assertEqual(native_pdf_page(self.path, 4), (None, 'invalid_page_number'))
        self.assertEqual(native_pdf_page(self.path.with_name('missing.pdf'), 1), (None, 'pdf_analysis_error'))

    def test_invisible_text_rejected(self):
        make_pdf(self.path, [TEXT.replace(b'BT /F1 12 Tf', b'BT /F1 12 Tf 3 Tr')])
        self.assertEqual(native_pdf_page(self.path, 1), (None, 'invisible_or_clipped_text'))

    def test_hybrid_image_rejected(self):
        image = b'\nq 100 0 0 100 10 10 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00 EI Q'
        make_pdf(self.path, [TEXT + image, image])
        self.assertEqual(native_pdf_page(self.path, 1), (None, 'image_present'))
        self.assertEqual(native_pdf_page(self.path, 2), (None, 'image_present'))

    def test_rotation_geometry(self):
        make_pdf(self.path, [TEXT], [180])
        self.assertEqual(native_pdf_page(self.path, 1), (None, 'rotated_page'))


if __name__ == '__main__':
    unittest.main()
