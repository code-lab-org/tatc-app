from datetime import datetime, timedelta, timezone

import pandas as pd
from tatc.analysis import (
    collect_downlinks,
    collect_observations,
    compute_latencies,
    reduce_latencies,
)
from tatc.generation import generate_points_uniform_spacing
from tatc.schemas import (
    GeneralPerturbationsOrbit,
    GroundStation,
    Instrument,
    WalkerConstellation,
)

from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.latency.schemas import LatencyAnalysisRequest, LatencyAnalysisResult
from tatc_app.utils.serialization import from_geojson

from .base import TLE, TatcTestCase


class LatencyAnalysisTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.satellite = WalkerConstellation(
            name="Test",
            orbit=GeneralPerturbationsOrbit.from_tle(TLE),
            instruments=[Instrument(name="Test", field_of_regard=180.0)],
            number_satellites=4,
            number_planes=2,
        )
        self.stations = [
            GroundStation(name="Svalbard", latitude=78.23, longitude=15.39),
            GroundStation(name="Wallops", latitude=37.94, longitude=-75.46),
        ]
        self.start = datetime(2022, 6, 1, tzinfo=timezone.utc)
        self.end = datetime(2022, 6, 2, tzinfo=timezone.utc)

    def test_analyze_latency(self):
        result = self.analysis_result(
            "/analyze/latency",
            LatencyAnalysisRequest(
                satellites=[self.satellite],
                stations=self.stations,
                start=self.start,
                end=self.end,
                points=PointGenerator(method="equally_spaced", distance=5000e3),
                cells=CellGenerator(method="equally_spaced", distance=5000e3),
            ),
            LatencyAnalysisResult,
        )
        points = generate_points_uniform_spacing(5000e3)
        members = self.satellite.generate_members()
        expected = reduce_latencies(
            compute_latencies(
                collect_observations(
                    points, members, self.start, self.end, instrument_index=None
                ),
                collect_downlinks(self.stations, members, self.start, self.end),
            ),
            targets=points,
        )
        actual = from_geojson(result.points.model_dump_json(), timedeltas=["latency"])
        self.assertEqual(len(actual), len(points))
        merged = actual.merge(expected, on="target_hash", suffixes=("", "_expected"))
        self.assertEqual(len(merged), len(points))
        self.assertTrue((merged["samples"] == merged["samples_expected"]).all())
        self.assertTrue(
            (
                (merged["latency"] - merged["latency_expected"])
                .abs()
                .fillna(pd.Timedelta(0))
                < timedelta(seconds=1)
            ).all()
        )
        # timelines of observations (to downlink) and contacts
        self.assertEqual(len(result.timeline.start), int(expected["samples"].sum()))
        self.assertEqual(result.contacts.targets, ["Svalbard", "Wallops"])
        self.assertGreater(len(result.contacts.start), 0)
        self.assertTrue(
            all(e > s for s, e in zip(result.contacts.start, result.contacts.end))
        )
        # czml document with stations and contact links
        czml = self.get_json(f"/analyze/latency/{self.task_id}/czml")
        ids = [packet["id"] for packet in czml]
        self.assertIn("gs/Svalbard", ids)
        self.assertTrue(any(i.startswith("link/gs/") for i in ids))
        link = next(p for p in czml if p["id"].startswith("link/gs/"))
        self.assertTrue(
            link["polyline"]["positions"]["references"][1].startswith("sat/")
        )

    def test_duplicate_station_names(self):
        response = self.client.post(
            "/analyze/latency",
            json={
                "satellites": [self.satellite.model_dump(mode="json")],
                "stations": [s.model_dump(mode="json") for s in self.stations[:1]] * 2,
                "start": "2022-06-01T00:00:00Z",
                "end": "2022-06-02T00:00:00Z",
                "points": {"method": "equally_spaced", "distance": 5000e3},
                "cells": {"method": "equally_spaced", "distance": 5000e3},
            },
        )
        self.assertEqual(response.status_code, 422)
