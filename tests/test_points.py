import json

import geopandas as gpd
from tatc.generation import (
    generate_points_fibonacci_lattice,
    generate_points_uniform_spacing,
)

from tatc_app.generation.masks import KnownShape, resolve_mask

from .base import TatcTestCase


class GeneratePointsTestCase(TatcTestCase):
    def test_generate_points_equally_spaced(self):
        response = self.client.post(
            "/generate/points",
            json={"method": "equally_spaced", "distance": 5000e3},
        )
        self.assertEqual(response.status_code, 200)
        gdf = gpd.GeoDataFrame.from_features(
            json.loads(response.content), crs="EPSG:4326"
        )
        gdf = gdf.reindex(columns=sorted(gdf.columns))
        tatc_results = generate_points_uniform_spacing(5000e3)
        tatc_results = tatc_results.reindex(columns=sorted(tatc_results.columns))
        print(tatc_results.columns)
        self.assertTrue(gdf.equals(tatc_results))

    def test_generate_points_fibonacci_lattice(self):
        response = self.client.post(
            "/generate/points",
            json={"method": "fibonacci_lattice", "distance": 5000e3},
        )
        self.assertEqual(response.status_code, 200)
        gdf = gpd.GeoDataFrame.from_features(
            json.loads(response.content), crs="EPSG:4326"
        )
        gdf = gdf.reindex(columns=sorted(gdf.columns))
        tatc_results = generate_points_fibonacci_lattice(5000e3)
        tatc_results = tatc_results.reindex(columns=sorted(tatc_results.columns))
        # TODO perform more comprehensive verification
        self.assertEqual(len(gdf), len(tatc_results))

    def test_generate_points_country_mask(self):
        for code in ("USA", "usa"):
            response = self.client.post(
                "/generate/points",
                json={"distance": 500e3, "mask": code},
            )
            self.assertEqual(response.status_code, 200)
            gdf = gpd.GeoDataFrame.from_features(
                json.loads(response.content), crs="EPSG:4326"
            )
            self.assertGreater(len(gdf), 0)
            self.assertTrue(gdf.within(resolve_mask("USA")).all())
        # unknown country codes are rejected
        response = self.client.post(
            "/generate/points",
            json={"distance": 500e3, "mask": "XXX"},
        )
        self.assertEqual(response.status_code, 422)


class ResolveMaskTestCase(TatcTestCase):
    def test_resolve_mask(self):
        self.assertIsNone(resolve_mask(None))
        self.assertEqual(resolve_mask("fra").geom_type, "MultiPolygon")
        self.assertTrue(resolve_mask(KnownShape.conus.value).is_valid)
        polygon = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        }
        self.assertEqual(resolve_mask(polygon).geom_type, "Polygon")
        with self.assertRaises(ValueError):
            resolve_mask("XXX")
