import unittest
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
from pydantic import ValidationError
from shapely.geometry import Point

from tatc_app.analysis.endpoints import chunk
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
