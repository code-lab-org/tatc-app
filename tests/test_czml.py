import unittest
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, Polygon, box

from tatc_app.analysis.colors import assign_colors, instrument_color
from tatc_app.analysis.timeline import Timeline, build_timeline
from tatc_app.analysis.tracks import (
    InstrumentTrack,
    MemberTrack,
    OrbitTracks,
    build_footprints,
)
from tatc_app.cesium.czml import (
    display_polygons,
    document_packet,
    link_packets,
    rgba,
    satellite_packets,
    site_packets,
    swath_packets,
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

    def test_build_footprints(self):
        ground_track = gpd.GeoDataFrame(
            {
                "time": [EPOCH + timedelta(seconds=s) for s in (0, 60, 120)],
                "valid_obs": [True, False, True],
            },
            geometry=[
                box(0, 0, 1, 1),
                box(0, 0, 1, 1),
                MultiPolygon([box(170, 0, 180, 10), box(-180, 0, -170, 10)]),
            ],
            crs="EPSG:4326",
        )
        footprints = build_footprints(ground_track, EPOCH)
        self.assertEqual([t for t, _ in footprints], [0, 60, 120])
        # rings are not closed
        self.assertEqual(len(footprints[0][1]), 1)
        self.assertEqual(len(footprints[0][1][0][0]), 8)
        # no polygons if the instrument does not observe
        self.assertEqual(footprints[1][1], [])
        self.assertEqual(len(footprints[2][1]), 2)


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
        # one translucent footprint per instrument (with a swath), centered
        # below the satellite (on the surface), in distinct colors
        self.assertEqual([first["id"], second["id"]], ["fp/s1/0", "fp/s1/1"])
        self.assertEqual(
            first["position"]["cartographicDegrees"], [0, 0, 0, 0, 60, 3.8, 0, 0]
        )
        self.assertEqual(first["position"]["epoch"], packet["position"]["epoch"])
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
        # an instrument's chosen color replaces its derived color
        tracks.tracks[0].instruments[1].color = "#00ff00"
        _, first, second = satellite_packets(tracks, {"s1": "#4e79a7"})
        self.assertEqual(
            first["ellipse"]["material"]["solidColor"]["color"]["rgba"],
            rgba("#4e79a7", 70),
        )
        self.assertEqual(
            second["ellipse"]["material"]["solidColor"]["color"]["rgba"],
            rgba("#00ff00", 70),
        )

    def test_satellite_footprint_polygons(self):
        square = [[0, 0, 1, 0, 1, 1, 0, 1]]
        ring = [[2, 2, 6, 2, 6, 6, 2, 6], [3, 3, 4, 3, 4, 4, 3, 4]]
        tracks = OrbitTracks(
            epoch=EPOCH,
            tracks=[
                MemberTrack(
                    name="s1",
                    positions=[0, 0, 0, 500e3, 60, 3.8, 0, 500e3, 120, 7.6, 0, 500e3],
                    instruments=[
                        InstrumentTrack(
                            name="a",
                            swath_widths=[0, 2000e3, 60, 2000e3, 120, 2000e3],
                            # two parts, then none, then one with a hole
                            footprints=[(0, [square, square]), (60, []), (120, [ring])],
                        ),
                        InstrumentTrack(
                            name="b",
                            swath_widths=[0, 2000e3, 60, 2000e3, 120, 2000e3],
                            footprints=[(0, []), (60, []), (120, [])],
                        ),
                    ],
                )
            ],
        )
        packets = satellite_packets(tracks, {"s1": "#4e79a7"})
        # a parent (to show or hide the footprint) and one child per part;
        # nothing for an instrument that never observes
        self.assertEqual(
            [p["id"] for p in packets], ["sat/s1", "fp/s1/0", "fp/s1/0/0", "fp/s1/0/1"]
        )
        parent, first, second = packets[1:]
        self.assertNotIn("polygon", parent)
        self.assertNotIn("ellipse", first)
        self.assertEqual(first["parent"], "fp/s1/0")
        # samples span the midpoints with their neighbors
        self.assertEqual(
            first["availability"],
            [
                "2022-01-01T00:00:00.000Z/2022-01-01T00:00:30.000Z",
                "2022-01-01T00:01:30.000Z/2022-01-01T00:02:00.000Z",
            ],
        )
        self.assertEqual(
            second["availability"],
            ["2022-01-01T00:00:00.000Z/2022-01-01T00:00:30.000Z"],
        )
        positions = first["polygon"]["positions"]
        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0]["cartographicDegrees"][:6], [0, 0, 0, 1, 0, 0])
        self.assertEqual(len(positions[1]["cartographicDegrees"]), 12)
        self.assertEqual(
            first["polygon"]["holes"][1]["cartographicDegrees"],
            [[3, 3, 0, 4, 3, 0, 4, 4, 0, 3, 4, 0]],
        )
        self.assertEqual(first["polygon"]["holes"][0]["cartographicDegrees"], [])
        self.assertNotIn("holes", second["polygon"])
        self.assertEqual(
            first["polygon"]["material"]["solidColor"]["color"]["rgba"],
            rgba("#4e79a7", 70),
        )

    def test_satellite_footprint_static_polygons(self):
        # a large footprint (as the full disk of a geostationary imager)
        # that barely moves, then moves, then barely moves
        disk = [-150, -60, 0, -60, 0, 60, -150, 60]
        shifted = [v + 0.2 for v in disk]
        moved = [v + 5 for v in disk]
        tracks = OrbitTracks(
            epoch=EPOCH,
            tracks=[
                MemberTrack(
                    name="s1",
                    positions=[t for i in range(4) for t in (60 * i, -75, 0, 35786e3)],
                    instruments=[
                        InstrumentTrack(
                            name="a",
                            swath_widths=[t for i in range(4) for t in (60 * i, 0)],
                            footprints=[
                                (0, [[disk]]),
                                (60, [[shifted]]),
                                (120, [[moved]]),
                                (180, [[moved]]),
                            ],
                        ),
                    ],
                )
            ],
        )
        packets = satellite_packets(tracks, {"s1": "#4e79a7"})
        # one static child per run of (nearly) unchanged samples, shown
        # only during its run, rather than positions that change over time
        # (which Cesium rebuilds every frame)
        self.assertEqual(
            [p["id"] for p in packets], ["sat/s1", "fp/s1/0", "fp/s1/0/0", "fp/s1/0/1"]
        )
        first, second = packets[2:]
        self.assertEqual(
            [first["availability"], second["availability"]],
            [
                "2022-01-01T00:00:00.000Z/2022-01-01T00:01:30.000Z",
                "2022-01-01T00:01:30.000Z/2022-01-01T00:03:00.000Z",
            ],
        )
        self.assertEqual(first["parent"], "fp/s1/0")
        self.assertEqual(
            first["polygon"]["positions"]["cartographicDegrees"][:3], [-150, -60, 0]
        )
        self.assertEqual(
            second["polygon"]["positions"]["cartographicDegrees"][:3], [-145, -55, 0]
        )
        self.assertEqual(first["polygon"]["arcType"], "RHUMB")
        self.assertEqual(
            first["polygon"]["material"]["solidColor"]["color"]["rgba"],
            rgba("#4e79a7", 70),
        )

    def test_display_polygons(self):
        # polygons away from the poles are drawn as is, with rhumb lines
        ((polygon, arc_type),) = display_polygons([box(0, 0, 10, 10)])
        self.assertTrue(polygon.equals(box(0, 0, 10, 10)))
        self.assertEqual(arc_type, "RHUMB")
        # TAT-C splits a geometry that covers a pole at the antimeridian, with
        # edges along the pole (which Cesium cannot draw): the parts are
        # re-formed as one polygon around the pole, drawn with geodesics
        # (with vertices every few degrees, as TAT-C's footprints have)
        for parts in (
            [box(-180, -90, 0, -80), box(0, -90, 180, -80)],
            # one ring with a spike out to the pole and back
            [Polygon([(-180, -90), (-180, -80), (180, -80), (180, -90)])],
        ):
            parts = [shapely.segmentize(part, 5) for part in parts]
            ((polygon, arc_type),) = display_polygons(parts)
            self.assertEqual(arc_type, "GEODESIC")
            latitudes = [y for _, y in polygon.exterior.coords]
            self.assertAlmostEqual(max(latitudes), -80, places=1)
            self.assertAlmostEqual(min(latitudes), -80, places=1)
            # the cap spans all longitudes, without a seam
            longitudes = sorted(x for x, _ in polygon.exterior.coords)
            self.assertLess(max(b - a for a, b in zip(longitudes, longitudes[1:])), 20)
        # parts at the north pole, and another part elsewhere
        drawn = display_polygons([box(170, 80, 180, 90), box(0, 0, 1, 1)])
        self.assertEqual([arc_type for _, arc_type in drawn], ["RHUMB", "GEODESIC"])

    def test_polygons_at_poles(self):
        # a cap around the south pole, as TAT-C splits it (with a spike out
        # to the pole and back along the antimeridian)
        cap = shapely.segmentize(
            Polygon([(-180, -90), (-180, -80), (180, -80), (180, -90)]), 5
        )
        polar = [[v for x, y in cap.exterior.coords[:-1] for v in (x, y)]]
        square = [[0, 0, 1, 0, 1, 1, 0, 1]]
        tracks = OrbitTracks(
            epoch=EPOCH,
            tracks=[
                MemberTrack(
                    name="s1",
                    positions=[0, 0, -85, 800e3, 60, 0, -80, 800e3],
                    instruments=[
                        InstrumentTrack(
                            name="a",
                            swath_widths=[0, 2000e3, 60, 2000e3],
                            footprints=[(0, [polar]), (60, [square])],
                        )
                    ],
                )
            ],
        )
        packet = next(p for p in satellite_packets(tracks) if p["id"] == "fp/s1/0/0")
        # the arc type changes with the samples
        self.assertEqual(
            [a["arcType"] for a in packet["polygon"]["arcType"]],
            ["GEODESIC", "RHUMB"],
        )
        latitudes = packet["polygon"]["positions"][0]["cartographicDegrees"][1::3]
        self.assertGreater(min(latitudes), -80.1)
        swaths = gpd.GeoDataFrame(
            {"satellite": ["s1"], "start": [EPOCH], "end": [EPOCH]},
            geometry=[box(170, 80, 180, 90)],
            crs="EPSG:4326",
        )
        (swath,) = swath_packets(swaths, EPOCH + timedelta(hours=1), tolerance=0)
        self.assertEqual(swath["polygon"]["arcType"], "GEODESIC")
        latitudes = swath["polygon"]["positions"]["cartographicDegrees"][1::3]
        self.assertAlmostEqual(min(latitudes), 80, places=1)

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
        tracks = OrbitTracks(
            epoch=EPOCH,
            tracks=[
                MemberTrack(
                    name="s1",
                    positions=[],
                    instruments=[
                        InstrumentTrack(name=name, swath_widths=[])
                        for name in ("a", "b")
                    ],
                )
            ],
        )
        packets = swath_packets(swaths, end, {"s1": "#4e79a7"}, tracks=tracks)
        self.assertEqual(
            packets[0]["polygon"]["material"]["solidColor"]["color"]["rgba"],
            rgba("#4e79a7", 150),
        )
        self.assertEqual(
            packets[1]["polygon"]["material"]["solidColor"]["color"]["rgba"],
            rgba(instrument_color("#4e79a7", 1, 2), 150),
        )
        self.assertEqual(packets[1]["name"], "s1 b swath")
        # chosen instrument colors replace derived colors
        tracks.tracks[0].instruments[1].color = "#00ff00"
        packets = swath_packets(swaths, end, {"s1": "#4e79a7"}, tracks=tracks)
        self.assertEqual(
            [p["polygon"]["material"]["solidColor"]["color"]["rgba"] for p in packets],
            [rgba("#4e79a7", 150)] + [rgba("#00ff00", 150)] * 2,
        )
