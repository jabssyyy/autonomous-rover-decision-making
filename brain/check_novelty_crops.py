"""Focused checks for offline crop selection boundaries."""
import unittest

from build_novelty_crops import crop_bounds, role_groups


class CropChecks(unittest.TestCase):
    def test_box_and_minimum(self):
        self.assertEqual(crop_bounds([.5, .5, .1, .1], 640, 480), (288, 216, 352, 264))
        self.assertIsNone(crop_bounds([.5, .5, .01, .01], 640, 480))
        self.assertEqual(crop_bounds([0, 0, .1, .1], 640, 480), (0, 0, 32, 24))

    def test_invalid_boxes(self):
        for box in ([.5, .5, 0, .1], [.5, .5, float('nan'), .1], [2, .5, .1, .1]):
            with self.assertRaises(ValueError):
                crop_bounds(box, 640, 480)

    def test_disjoint_roles_exclude_test(self):
        result = role_groups({'a': 'train', 'b': 'val', 'c': 'val', 'd': 'test'})
        self.assertEqual(result, {'a': 'memory', 'b': 'familiar', 'c': 'novel'})

    def test_insufficient_groups(self):
        with self.assertRaises(ValueError):
            role_groups({'a': 'train', 'b': 'val', 'c': 'test'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
