import unittest
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, box

from tatc_app.czml import (
    assign_colors,
    document_packet,
    link_packets,
    rgba,
    satellite_packets,
    site_packets,
    swath_packets,
)
from tatc_app.utils.timeline import (
    MemberTrack,
    OrbitTracks,
    Timeline,
    build_timeline,
)

EPOCH = datetime(2022, 1, 1, tzinfo=timezone.utc)


class TimelineTestCase(unittest.TestCase):
    def test_build_timeline(self):
        events = pd.DataFrame(
            {
                "target_hash": ["b", "a", "c", "a"],
                "satellite": ["s2", "s1", "s1", "s1, s2"],
                "start": [EPOCH + timedelta(seconds=s) for s in (20, 10, 5, 30)],
                "end": [EPOCH + timedelta(seconds=s) for s in (25, 15, 6, 40)],
            }
        )
        timeline = build_timeline(events, EPOCH, ["a", "b"], ["s1", "s2"])
        # sorted by start, unknown target (c) dropped, merged members
        # attributed to the first
        self.assertEqual(timeline.start, [10, 20, 30])
        self.assertEqual(timeline.end, [15, 25, 40])
        self.assertEqual(timeline.target, [0, 1, 0])
        self.assertEqual(timeline.member, [0, 1, 0])

    def test_build_timeline_missing_end(self):
        events = pd.DataFrame(
            {
                "target_hash": ["a"],
                "satellite": ["s1"],
                "observed": [EPOCH],
                "downlinked": [pd.NaT],
            }
        )
        timeline = build_timeline(
            events,
            EPOCH,
            ["a"],
            ["s1"],
            start_column="observed",
            end_column="downlinked",
        )
        self.assertEqual(timeline.end, [None])

    def test_build_timeline_empty(self):
        timeline = build_timeline(pd.DataFrame(), EPOCH, ["a"], ["s1"])
        self.assertEqual(timeline.start, [])
        self.assertEqual(timeline.targets, ["a"])


class CzmlTestCase(unittest.TestCase):
    def test_document(self):
        packet = document_packet("Test", EPOCH, EPOCH + timedelta(days=1))
        self.assertEqual(packet["id"], "document")
        self.assertEqual(
            packet["clock"]["interval"],
            "2022-01-01T00:00:00.000Z/2022-01-02T00:00:00.000Z",
        )

    def test_colors(self):
        self.assertEqual(rgba("#ff8000", 10), [255, 128, 0, 10])
        colors = assign_colors(["a", "b"], {"b": "#000000"})
        self.assertEqual(colors["b"], "#000000")
        self.assertTrue(colors["a"].startswith("#"))

    def test_satellites(self):
        tracks = OrbitTracks(
            epoch=EPOCH,
            tracks=[
                MemberTrack(
                    name="s1",
                    positions=[0, 0, 0, 500e3, 60, 3.8, 0, 500e3],
                    swath_widths=[0, 2000e3, 60, 2000e3],
                )
            ],
        )
        (packet,) = satellite_packets(tracks)
        self.assertEqual(packet["id"], "sat/s1")
        self.assertEqual(packet["position"]["cartographicDegrees"][4], 60)
        self.assertEqual(
            packet["ellipse"]["semiMajorAxis"]["number"], [0, 1e6, 60, 1e6]
        )
        # path trails one orbital period (about 95 minutes at 500 km)
        self.assertAlmostEqual(packet["path"]["trailTime"], 5677, delta=60)
        self.assertEqual(tracks.get_end(), EPOCH + timedelta(seconds=60))

    def test_links(self):
        timeline = Timeline(
            epoch=EPOCH,
            targets=["gs1"],
            members=["s1", "s2"],
            target=[0, 0, 0],
            member=[0, 1, 0],
            start=[0, 10, 100],
            end=[50, None, 150],
        )
        packets = link_packets(timeline, "gs")
        self.assertEqual(len(packets), 2)
        first = next(p for p in packets if p["id"] == "link/gs/gs1/s1")
        self.assertEqual(len(first["availability"]), 2)
        self.assertEqual(
            first["polyline"]["positions"]["references"],
            ["gs/gs1#position", "sat/s1#position"],
        )
        # instantaneous events are shown for a minimum duration
        second = next(p for p in packets if p["id"] == "link/gs/gs1/s2")
        self.assertEqual(
            second["availability"],
            ["2022-01-01T00:00:10.000Z/2022-01-01T00:00:11.000Z"],
        )

    def test_sites(self):
        (packet,) = site_packets("tgt", [("h1", "Point 1", -111.9, 33.4)], label=True)
        self.assertEqual(packet["id"], "tgt/h1")
        self.assertEqual(packet["position"]["cartographicDegrees"], [-111.9, 33.4, 0])
        self.assertEqual(packet["label"]["text"], "Point 1")

    def test_swaths(self):
        swaths = gpd.GeoDataFrame(
            {
                "satellite": ["s1", "s1"],
                "start": [EPOCH, EPOCH + timedelta(minutes=10)],
                "end": [EPOCH + timedelta(minutes=10), EPOCH + timedelta(minutes=20)],
            },
            geometry=[
                box(0, 0, 10, 10),
                MultiPolygon([box(170, 0, 180, 10), box(-180, 0, -170, 10)]),
            ],
            crs="EPSG:4326",
        )
        end = EPOCH + timedelta(hours=1)
        packets = swath_packets(swaths, end)
        self.assertEqual(len(packets), 3)
        self.assertEqual(
            packets[0]["availability"],
            "2022-01-01T00:10:00.000Z/2022-01-01T01:00:00.000Z",
        )
        self.assertEqual(
            len(packets[0]["polygon"]["positions"]["cartographicDegrees"]), 12
        )
