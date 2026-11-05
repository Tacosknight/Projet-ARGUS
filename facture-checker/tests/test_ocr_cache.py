#!/usr/bin/env python3
"""
Tests unitaires pour le cache déterministe d'inférence OCR (core/ocr_cache.py).
"""

import tempfile
import unittest
import numpy as np
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.ocr_cache import OCRResultCache, compute_image_hash


class TestOCRCache(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ocr_cache.db"
        self.cache = OCRResultCache(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_compute_hash_consistency(self):
        # 2 arrays identiques doivent produire exactement le même hash
        img_a = np.zeros((100, 100, 3), dtype=np.uint8)
        img_b = np.zeros((100, 100, 3), dtype=np.uint8)
        hash_a = compute_image_hash(img_a)
        hash_b = compute_image_hash(img_b)
        self.assertEqual(hash_a, hash_b)

        # Un array différent doit produire un hash différent
        img_c = np.ones((100, 100, 3), dtype=np.uint8)
        hash_c = compute_image_hash(img_c)
        self.assertNotEqual(hash_a, hash_c)

    def test_cache_miss_and_hit(self):
        img = np.full((50, 50, 3), 128, dtype=np.uint8)

        # 1. Cache MISS
        self.assertIsNone(self.cache.get(img))
        self.assertEqual(self.cache.size(), 0)

        # 2. Sauvegarde en cache
        sample_results = [
            {"text": "Facture 301/10109107", "box": [[10, 10], [50, 10], [50, 20], [10, 20]], "confidence": 0.99},
            {"text": "N° de série : 934534", "box": [[10, 30], [80, 30], [80, 40], [10, 40]], "confidence": 0.98},
        ]
        self.assertTrue(self.cache.set(img, sample_results, image_shape=img.shape))
        self.assertEqual(self.cache.size(), 1)

        # 3. Cache HIT
        cached_data = self.cache.get(img)
        self.assertIsNotNone(cached_data)
        self.assertEqual(len(cached_data), 2)
        self.assertEqual(cached_data[0]["text"], "Facture 301/10109107")
        self.assertEqual(cached_data[1]["text"], "N° de série : 934534")

    def test_cache_clear(self):
        img = np.zeros((20, 20, 3), dtype=np.uint8)
        self.cache.set(img, [{"text": "Test"}])
        self.assertEqual(self.cache.size(), 1)

        cleared_cnt = self.cache.clear()
        self.assertEqual(cleared_cnt, 1)
        self.assertEqual(self.cache.size(), 0)
        self.assertIsNone(self.cache.get(img))


if __name__ == "__main__":
    unittest.main()
