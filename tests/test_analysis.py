import unittest
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
from pydantic import ValidationError
from shapely.geometry import Point
from tatc.schemas import (
    CircularOrbit,
    GeosynchronousOrbit,
    Instrument,
    Satellite,
)

from tatc_app.analysis.endpoints import chunk
from tatc_app.analysis.tasks import compute_member_track
from tatc_app.generation.schemas import TimeGenerator

START = datetime(2022, 1, 1, tzinfo=timezone.utc)


class ChunkTestCase(unittest.TestCase):
    def test_chunk_data_frame(self):
        gdf = gpd.GeoDataFrame(geometry=[Point(i, 0) for i in range(10)])
        chunks = chunk(gdf, 4)
        self.assertEqual([len(c) for c in chunks], [4, 3, 3])
        self.assertTrue(pd.concat(chunks).equals(gdf))
        self.assertEqual([len(c) for c in chunk(gdf.iloc[:0], 4)], [])

    def test_chunk_times(self):
        times = pd.date_range(START, periods=250, freq="1min")
        chunks = chunk(times, 100)
        self.assertEqual([len(c) for c in chunks], [84, 83, 83])
        self.assertTrue(chunks[0].append(chunks[1:]).equals(times))


class TimeGeneratorTestCase(unittest.TestCase):
    def test_validate_period(self):
        delta = timedelta(minutes=1)
        self.assertEqual(
            len(TimeGenerator(start=START, end=START + delta, delta=delta).to_index()),
            2,
        )
        with self.assertRaisesRegex(ValidationError, "Invalid end"):
            TimeGenerator(start=START, end=START, delta=delta)
        with self.assertRaisesRegex(ValidationError, "Invalid delta"):
            TimeGenerator(start=START, end=START + delta / 2, delta=delta)


class MemberTrackTestCase(unittest.TestCase):
    def test_footprints(self):
        times = pd.date_range(START, periods=3, freq="5min")
        # a narrow footprint is the circle spanned by the swath width
        leo = Satellite(
            name="leo",
            orbit=CircularOrbit(altitude=700e3, inclination=98),
            instruments=[Instrument(name="imager", field_of_regard=60)],
        )
        self.assertIsNone(
            compute_member_track(leo, times, START).instruments[0].footprints
        )
        # the full disk of a geostationary imager is too wide to draw as a
        # circle, so its footprint is computed by TAT-C
        geo = Satellite(
            name="geo",
            orbit=GeosynchronousOrbit(longitude=-75.2),
            instruments=[Instrument(name="abi", field_of_regard=17.4)],
        )
        footprints = compute_member_track(geo, times, START).instruments[0].footprints
        self.assertEqual(len(footprints), 3)
        self.assertTrue(all(len(polygons) == 1 for _, polygons in footprints))
