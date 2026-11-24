from datetime import datetime, timedelta, timezone

from tatc.schemas import (
    CircularOrbit,
    Instrument,
    PointedInstrument,
    WalkerConstellation,
)

from tatc_app.tracking.schemas import SwathAnalysisRequest, SwathAnalysisResult

from .base import TatcTestCase


class AnalyzeSwathsTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.constellation = WalkerConstellation(
            name="W",
            orbit=CircularOrbit(altitude=700e3, inclination=98),
            instruments=[
                PointedInstrument(
                    name="Imager",
                    cross_track_field_of_view=40,
                    along_track_field_of_view=2,
                ),
                Instrument(name="Wide", field_of_regard=100),
            ],
            number_satellites=2,
            number_planes=2,
        )
        self.start = datetime(2022, 6, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(hours=3)

    def test_analyze_swaths(self):
        task = self.run_analysis(
            "/analyze/swaths",
            SwathAnalysisRequest(
                satellites=[self.constellation],
                start=self.start,
                end=self.end,
                step=timedelta(seconds=60),
                segment=timedelta(minutes=30),
            ),
        )
        result = SwathAnalysisResult.model_validate(
            self.get_json(f"/analyze/swaths/{task['task_id']}")
        )
        members = [m.name for m in self.constellation.generate_members()]
        self.assertEqual([t.name for t in result.tracks.tracks], members)
        for track in result.tracks.tracks:
            # 3 hours at 60 second steps (inclusive)
            self.assertEqual(len(track.positions), 4 * 181)
            # swath widths of each instrument
            self.assertEqual(
                [instrument.name for instrument in track.instruments],
                ["Imager", "Wide"],
            )
            for instrument in track.instruments:
                self.assertEqual(len(instrument.swath_widths), 2 * 181)
            # footprints computed by TAT-C for the pointed instrument, while
            # the simple instrument's footprint is its swath width's circle
            footprints = track.instruments[0].footprints
            self.assertEqual(len(footprints), 181)
            self.assertTrue(all(len(polygons) > 0 for _, polygons in footprints))
            self.assertIsNone(track.instruments[1].footprints)
            self.assertNotEqual(
                track.instruments[1].swath_widths[1],
                track.instruments[0].swath_widths[1],
            )
        self.assertEqual(result.systems, {member: 0 for member in members})
        # one segment per 30 minutes per member (for the pointed instrument)
        self.assertEqual(len(result.swaths.features), 2 * 6)
        for feature in result.swaths.features:
            self.assertEqual(feature.properties["instrument"], "Imager")
            self.assertLess(feature.properties["start"], feature.properties["end"])
        czml = self.get_json(f"/analyze/swaths/{task['task_id']}/czml")
        self.assertEqual(czml[0]["id"], "document")
        ids = [packet["id"] for packet in czml]
        self.assertIn(f"sat/{members[0]}", ids)
        self.assertIn(f"fp/{members[0]}/0", ids)
        self.assertIn(f"fp/{members[0]}/0/0", ids)
        self.assertIn(f"fp/{members[0]}/1", ids)
        polygon = next(p for p in czml if p["id"] == f"fp/{members[0]}/0/0")
        self.assertEqual(polygon["parent"], f"fp/{members[0]}/0")
        self.assertGreater(len(polygon["polygon"]["positions"]), 1)
        circle = next(p for p in czml if p["id"] == f"fp/{members[0]}/1")
        self.assertIn("ellipse", circle)
        swaths = [packet for packet in czml if packet["id"].startswith("swath/")]
        self.assertGreaterEqual(len(swaths), 12)
        self.assertTrue(all(p["availability"].endswith("Z") for p in swaths))

    def test_instrument_colors(self):
        request = SwathAnalysisRequest.model_validate(
            {
                "satellites": [self.constellation.model_dump(mode="json")],
                "instrumentColors": [[None, "#00ff00"]],
                "start": self.start,
                "end": self.end,
                "segment": None,
            }
        )
        members = [m.name for m in self.constellation.generate_members()]
        self.assertEqual(
            request.get_member_instrument_colors(),
            {member: [None, "#00ff00"] for member in members},
        )
        # only default colors, or none
        for colors in ([[None, None]], [None], None):
            request.instrument_colors = colors
            self.assertEqual(request.get_member_instrument_colors(), {})
        # colors must be `#rrggbb`
        with self.assertRaises(ValueError):
            SwathAnalysisRequest(
                satellites=[self.constellation],
                instrument_colors=[["green"]],
                start=self.start,
                end=self.end,
            )
        # tracks carry the chosen colors of instruments
        request.instrument_colors = [[None, "#00ff00"]]
        task = self.run_analysis("/analyze/swaths", request)
        result = SwathAnalysisResult.model_validate(
            self.get_json(f"/analyze/swaths/{task['task_id']}")
        )
        for track in result.tracks.tracks:
            self.assertEqual(
                [instrument.color for instrument in track.instruments],
                [None, "#00ff00"],
            )
        czml = self.get_json(f"/analyze/swaths/{task['task_id']}/czml")
        circle = next(p for p in czml if p["id"] == f"fp/{members[0]}/1")
        self.assertEqual(
            circle["ellipse"]["material"]["solidColor"]["color"]["rgba"][:3],
            [0, 255, 0],
        )

    def test_analyze_tracks_only(self):
        task = self.run_analysis(
            "/analyze/swaths",
            SwathAnalysisRequest(
                satellites=[self.constellation],
                start=self.start,
                end=self.end,
                segment=None,
            ),
        )
        result = SwathAnalysisResult.model_validate(
            self.get_json(f"/analyze/swaths/{task['task_id']}")
        )
        self.assertEqual(len(result.tracks.tracks), 2)
        self.assertEqual(len(result.swaths.features), 0)

    def test_exclude_members(self):
        members = [m.name for m in self.constellation.generate_members()]
        request = SwathAnalysisRequest.model_validate(
            {
                "satellites": [self.constellation.model_dump(mode="json")],
                "excludeMembers": [members[0], "unknown"],
                "start": self.start,
                "end": self.end,
                "segment": None,
            }
        )
        self.assertEqual([m.name for m in request.get_members()], members[1:])
        task = self.run_analysis("/analyze/swaths", request)
        result = SwathAnalysisResult.model_validate(
            self.get_json(f"/analyze/swaths/{task['task_id']}")
        )
        self.assertEqual([t.name for t in result.tracks.tracks], members[1:])
        # all members excluded
        response = self.client.post(
            "/analyze/swaths",
            json={
                "satellites": [self.constellation.model_dump(mode="json")],
                "excludeMembers": members,
                "start": "2022-06-01T00:00:00Z",
                "end": "2022-06-01T03:00:00Z",
                "segment": None,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_too_many_steps(self):
        response = self.client.post(
            "/analyze/swaths",
            json={
                "satellites": [self.constellation.model_dump(mode="json")],
                "start": "2022-01-01T00:00:00Z",
                "end": "2023-01-01T00:00:00Z",
                "step": "PT1S",
            },
        )
        self.assertEqual(response.status_code, 422)
