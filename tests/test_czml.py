import unittest
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, box

from tatc_app.czml import (
    assign_colors,
    document_packet,
    instrument_color,
    link_packets,
    rgba,
    satellite_packets,
    site_packets,
    swath_packets,
)
from tatc_app.utils.timeline import (
    InstrumentTrack,
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

    def test_instrument_colors(self):
        # the first (or only) instrument keeps the satellite color
        self.assertEqual(instrument_color("#4e79a7", 0, 2), "#4e79a7")
        self.assertEqual(instrument_color("#4e79a7", 0, 1), "#4e79a7")
        # others rotate the hue, distinct from each other
        colors = {instrument_color("#4e79a7", i, 3) for i in range(3)}
        self.assertEqual(len(colors), 3)
        # gray colors gain saturation to remain distinct
        self.assertNotEqual(instrument_color("#808080", 1, 2), "#808080")

    def test_satellites(self):
        tracks = OrbitTracks(
            epoch=EPOCH,
            tracks=[
                MemberTrack(
                    name="s1",
                    positions=[0, 0, 0, 500e3, 60, 3.8, 0, 500e3],
                    instruments=[
                        InstrumentTrack(name="a", swath_widths=[0, 2000e3, 60, 2000e3]),
                        InstrumentTrack(name="b", swath_widths=[0, 500e3, 60, 500e3]),
                        InstrumentTrack(name="c", swath_widths=[0, 0, 60, 0]),
                    ],
                )
            ],
        )
        packet, first, second = satellite_packets(tracks, {"s1": "#4e79a7"})
        self.assertEqual(packet["id"], "sat/s1")
        self.assertEqual(packet["position"]["cartographicDegrees"][4], 60)
        self.assertNotIn("ellipse", packet)
        # path trails one orbital period (about 95 minutes at 500 km)
        self.assertAlmostEqual(packet["path"]["trailTime"], 5677, delta=60)
        self.assertEqual(tracks.get_end(), EPOCH + timedelta(seconds=60))
        # one translucent footprint per instrument (with a swath), following
        # the satellite, in distinct colors
        self.assertEqual([first["id"], second["id"]], ["fp/s1/0", "fp/s1/1"])
        self.assertEqual(first["position"], {"reference": "sat/s1#position"})
        self.assertEqual(first["ellipse"]["semiMajorAxis"]["number"], [0, 1e6, 60, 1e6])
        self.assertEqual(
            second["ellipse"]["semiMinorAxis"]["number"], [0, 250e3, 60, 250e3]
        )
        fills = [
            p["ellipse"]["material"]["solidColor"]["color"]["rgba"]
            for p in (first, second)
        ]
        self.assertEqual(fills[0], rgba("#4e79a7", 70))
        self.assertNotEqual(fills[1][:3], fills[0][:3])
        self.assertLess(fills[1][3], 255)
        # footprints can be omitted
        self.assertEqual(len(satellite_packets(tracks, footprint=False)), 1)

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
                "instrument": ["a", "b"],
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
        # without instruments, segments take the satellite color
        colors = {
            p["polygon"]["material"]["solidColor"]["color"]["rgba"][0] for p in packets
        }
        self.assertEqual(len(colors), 1)
        # with instruments, segments of each instrument take distinct colors
        packets = swath_packets(
            swaths, end, {"s1": "#4e79a7"}, instruments={"s1": ["a", "b"]}
        )
        self.assertEqual(
            packets[0]["polygon"]["material"]["solidColor"]["color"]["rgba"],
            rgba("#4e79a7", 150),
        )
        self.assertEqual(
            packets[1]["polygon"]["material"]["solidColor"]["color"]["rgba"],
            rgba(instrument_color("#4e79a7", 1, 2), 150),
        )
        self.assertEqual(packets[1]["name"], "s1 b swath")
