"""Check ranking ties and raw-distance/clipped-score distinction."""
import unittest
import numpy as np

from diagnose_novelty_distances import compare, rank_auc


class DistanceChecks(unittest.TestCase):
    def test_rank_ties(self):
        self.assertEqual(rank_auc([0, 0], [0]), .5)
        self.assertEqual(rank_auc([0, 1], [2]), 1.)
        self.assertEqual(rank_auc([1, 2], [0]), 0.)

    def test_clipping_preserves_raw_evidence(self):
        rows = [dict(image=str(i), role=role, group=str(i), sha256='fixture')
                for i, role in enumerate(('memory', 'memory', 'familiar', 'novel'))]
        vectors = [np.array(v, dtype=np.float32) for v in ((1, 0), (0, 1), (1, 0), (1, 1))]
        result = compare(rows, vectors)
        self.assertEqual(result['distance']['rank_auc'], 1.)
        self.assertEqual(result['novelty']['rank_auc'], .5)
        self.assertEqual(result['clipped_to_zero'], {'familiar': 1, 'novel': 1})


if __name__ == '__main__':
    unittest.main(verbosity=2)
