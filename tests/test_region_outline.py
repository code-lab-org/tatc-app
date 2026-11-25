from shapely.geometry import box, shape

from tatc_app.generation.masks import resolve_mask

from .base import TatcTestCase


class RegionOutlineTestCase(TatcTestCase):
    def outline(self, mask):
        response = self.client.post("/generate/region", json={"mask": mask})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["features"]

    def test_known_shape_and_country(self):
        for mask in ("conus", "USA"):
            (feature,) = self.outline(mask)
            outline = shape(feature["geometry"])
            region = resolve_mask(mask)
            # simplified, but nearly the same area
            self.assertAlmostEqual(outline.area / region.area, 1, 2)

    def test_latitude_band(self):
        band = box(-180, -30, 180, 30)
        (feature,) = self.outline(
            {"type": "Polygon", "coordinates": [list(band.exterior.coords)]}
        )
        coordinates = feature["geometry"]["coordinates"][0]
        # edges along the parallels are subdivided (at most 1 degree long)
        self.assertGreaterEqual(len(coordinates), 2 * 360)
        self.assertAlmostEqual(shape(feature["geometry"]).area, band.area)

    def test_globe_and_invalid(self):
        self.assertEqual(self.outline(None), [])
        response = self.client.post("/generate/region", json={"mask": "XYZ"})
        self.assertEqual(response.status_code, 422)
