import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest import mock
from uuid import uuid4

from tatc.schemas import GeneralPerturbationsOrbit, Instrument, Satellite

from tatc_app import limits
from tatc_app.auth import User, current_user
from tatc_app.coincidence.schemas import CoincidenceAnalysisRequest
from tatc_app.coverage.schemas import CoverageAnalysisRequest, CoverageAnalysisResult
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.library.database import SCHEMA_VERSION, Library
from tatc_app.main import app

from .base import TatcTestCase

TLE = [
    "1 25544U 98067A   22171.11255782  .00008307  00000+0  15444-3 0  9992",
    "2 25544  51.6448 322.0970 0003980 282.3738 231.6559 15.49798078345636",
]
START = datetime(2022, 6, 1, tzinfo=timezone.utc)
DESIGN = {
    "version": 2,
    "satellites": [{"system": {"type": "satellite", "name": "A"}, "color": "#e15759"}],
    "stations": [],
    "targets": [],
}


def coverage_request() -> CoverageAnalysisRequest:
    return CoverageAnalysisRequest(
        satellites=[
            Satellite(
                name="Test",
                orbit=GeneralPerturbationsOrbit.from_tle(TLE),
                instruments=[Instrument(name="Test", field_of_regard=180.0)],
            )
        ],
        start=START,
        end=START + timedelta(hours=6),
        points=PointGenerator(method="equally_spaced", distance=5000e3),
        cells=CellGenerator(method="equally_spaced", distance=5000e3),
    )


class LibraryTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        # each test has its own users, so tests do not see each other's records
        self.users = {}
        self.sign_in("a")

    def sign_in(self, name: str) -> None:
        """
        Signs in as a user of the test.
        """
        user = self.users.setdefault(name, User(id=f"{name}-{uuid4()}"))
        app.dependency_overrides[current_user] = lambda: user


class DesignsTestCase(LibraryTestCase):
    def test_designs(self):
        response = self.client.post(
            "/designs", json={"name": " First ", "design": DESIGN}
        )
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved["name"], "First")
        self.assertEqual(saved["satellites"], 1)
        self.assertEqual(saved["design"], DESIGN)
        listed = self.client.get("/designs").json()
        self.assertEqual([d["id"] for d in listed], [saved["id"]])
        self.assertNotIn("design", listed[0])
        # update
        changed = dict(DESIGN, satellites=[])
        response = self.client.put(
            f"/designs/{saved['id']}", json={"name": "Second", "design": changed}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["satellites"], 0)
        fetched = self.client.get(f"/designs/{saved['id']}").json()
        self.assertEqual(fetched["name"], "Second")
        self.assertEqual(fetched["design"], changed)
        self.assertEqual(fetched["created"], saved["created"])
        # delete
        response = self.client.delete(f"/designs/{saved['id']}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(f"/designs/{saved['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/designs/{saved['id']}").status_code, 404)
        self.assertEqual(self.client.get("/designs").json(), [])

    def test_users_see_only_their_designs(self):
        saved = self.client.post(
            "/designs", json={"name": "A", "design": DESIGN}
        ).json()
        self.sign_in("b")
        self.assertEqual(self.client.get("/designs").json(), [])
        self.assertEqual(self.client.get(f"/designs/{saved['id']}").status_code, 404)
        response = self.client.put(
            f"/designs/{saved['id']}", json={"name": "B", "design": DESIGN}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.delete(f"/designs/{saved['id']}").status_code, 404)
        self.sign_in("a")
        self.assertEqual(self.client.get(f"/designs/{saved['id']}").json()["name"], "A")

    def test_invalid_designs(self):
        for body in (
            {"name": "", "design": DESIGN},
            {"name": "x" * 101, "design": DESIGN},
            {"name": "A", "design": [1, 2]},
            {"design": DESIGN},
        ):
            with self.subTest(body=body):
                response = self.client.post("/designs", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        with mock.patch.object(limits, "MAX_SAVED_BYTES", 10):
            response = self.client.post(
                "/designs", json={"name": "A", "design": DESIGN}
            )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Too large", response.text)

    def test_capacity(self):
        with mock.patch.object(limits, "MAX_SAVED_ITEMS", 1):
            first = self.client.post("/designs", json={"name": "A", "design": DESIGN})
            self.assertEqual(first.status_code, 200, first.text)
            second = self.client.post("/designs", json={"name": "B", "design": DESIGN})
            self.assertEqual(second.status_code, 409, second.text)
            # updates are allowed at capacity
            response = self.client.put(
                f"/designs/{first.json()['id']}", json={"name": "C", "design": DESIGN}
            )
            self.assertEqual(response.status_code, 200, response.text)

    def test_requires_authentication(self):
        self.require_authentication()
        self.assertEqual(self.client.get("/designs").status_code, 401)
        self.assertEqual(self.client.get("/runs").status_code, 401)


class RunsTestCase(LibraryTestCase):
    def run_coverage(self) -> tuple:
        request = coverage_request()
        task = self.run_analysis("/analyze/coverage", request)
        return request.model_dump(mode="json"), task["task_id"]

    def test_runs(self):
        request, task_id = self.run_coverage()
        response = self.client.post(
            "/runs",
            json={
                "name": "Baseline",
                "analysis": "coverage",
                "taskId": task_id,
                "request": request,
                "design": DESIGN,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        # the summary is the one of the task's results
        result = CoverageAnalysisResult.model_validate(
            self.get_json(f"/analyze/coverage/{task_id}")
        )
        self.assertEqual(saved["summary"], result.summary.model_dump(mode="json"))
        self.assertEqual(saved["request"], request)
        self.assertEqual(saved["design"], DESIGN)
        # listed with summaries, without inputs, and by analysis
        listed = self.client.get("/runs").json()
        self.assertEqual([r["id"] for r in listed], [saved["id"]])
        self.assertIn("summary", listed[0])
        self.assertNotIn("request", listed[0])
        self.assertEqual(len(self.client.get("/runs?analysis=coverage").json()), 1)
        self.assertEqual(self.client.get("/runs?analysis=latency").json(), [])
        # rename and delete
        response = self.client.patch(f"/runs/{saved['id']}", json={"name": "Renamed"})
        self.assertEqual(response.json()["name"], "Renamed")
        self.sign_in("b")
        self.assertEqual(self.client.get(f"/runs/{saved['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/runs/{saved['id']}").status_code, 404)
        self.sign_in("a")
        self.assertEqual(self.client.delete(f"/runs/{saved['id']}").status_code, 204)
        self.assertEqual(self.client.get("/runs").json(), [])

    def test_results_of_another_analysis(self):
        request, task_id = self.run_coverage()
        response = self.client.post(
            "/runs",
            json={
                "name": "Wrong",
                "analysis": "latency",
                "taskId": task_id,
                "request": dict(
                    request,
                    stations=[{"name": "S", "latitude": 0, "longitude": 0}],
                ),
                "design": DESIGN,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("not of a latency analysis", response.text)

    def test_results_not_available(self):
        request, _ = self.run_coverage()
        response = self.client.post(
            "/runs",
            json={
                "name": "Expired",
                "analysis": "coverage",
                "taskId": str(uuid4()),
                "request": request,
                "design": DESIGN,
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_invalid_request(self):
        _, task_id = self.run_coverage()
        response = self.client.post(
            "/runs",
            json={
                "name": "Invalid",
                "analysis": "coverage",
                "taskId": task_id,
                "request": {"satellites": []},
                "design": DESIGN,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"][0]["loc"][:2], ["body", "request"])

    def test_coincidence_run(self):
        request = coverage_request().model_dump(mode="json")
        # two satellites, to coincide
        satellite = dict(request["satellites"][0], name="Other")
        request = dict(request, satellites=request["satellites"] + [satellite])
        task = self.run_analysis(
            "/analyze/coincidence",
            CoincidenceAnalysisRequest.model_validate(request),
        )
        response = self.client.post(
            "/runs",
            json={
                "name": "Matchups",
                "analysis": "coincidence",
                "taskId": task["task_id"],
                "request": request,
                "design": DESIGN,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("observed", response.json()["summary"])
        self.assertEqual(len(self.client.get("/runs?analysis=coincidence").json()), 1)

    def test_run_without_summary(self):
        # point access runs have no summary, so their results are not read
        request = {
            "satellites": [coverage_request().satellites[0].model_dump(mode="json")],
            "start": START.isoformat(),
            "end": (START + timedelta(hours=6)).isoformat(),
            "points": [{"id": 0, "latitude": 0, "longitude": 0}],
        }
        response = self.client.post(
            "/runs",
            json={
                "name": "Access",
                "analysis": "access",
                "taskId": str(uuid4()),
                "request": request,
                "design": DESIGN,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["summary"])

    def save_run(self, task_id: str, request: dict, **kwargs):
        return self.client.post(
            "/runs",
            json=dict(
                {
                    "name": "Run",
                    "analysis": "coverage",
                    "taskId": task_id,
                    "request": request,
                    "design": DESIGN,
                },
                **kwargs,
            ),
        )

    def test_runs_under_designs(self):
        request, task_id = self.run_coverage()
        first = self.client.post("/designs", json={"name": "A", "design": DESIGN})
        second = self.client.post("/designs", json={"name": "B", "design": DESIGN})
        first, second = first.json()["id"], second.json()["id"]
        response = self.save_run(task_id, request, designId=first)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved["design_id"], first)
        unfiled = self.save_run(task_id, request).json()
        self.assertIsNone(unfiled["design_id"])
        # designs count their runs
        counts = {d["id"]: d["runs"] for d in self.client.get("/designs").json()}
        self.assertEqual(counts, {first: 1, second: 0})
        self.assertEqual(self.client.get(f"/designs/{first}").json()["runs"], 1)
        # runs list by design
        listed = self.client.get(f"/runs?design={first}&analysis=coverage").json()
        self.assertEqual([r["id"] for r in listed], [saved["id"]])
        self.assertEqual(self.client.get(f"/runs?design={second}").json(), [])
        # moved to another design (keeping its name), then to none
        response = self.client.patch(f"/runs/{saved['id']}", json={"designId": second})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["design_id"], second)
        self.assertEqual(response.json()["name"], "Run")
        response = self.client.patch(f"/runs/{saved['id']}", json={"designId": None})
        self.assertIsNone(response.json()["design_id"])
        # renaming keeps its design
        self.client.patch(f"/runs/{unfiled['id']}", json={"designId": first})
        response = self.client.patch(f"/runs/{unfiled['id']}", json={"name": "New"})
        self.assertEqual(response.json()["design_id"], first)
        # deleting a design deletes its runs
        self.assertEqual(self.client.delete(f"/designs/{first}").status_code, 204)
        self.assertEqual(self.client.get(f"/runs/{unfiled['id']}").status_code, 404)
        self.assertEqual(
            [r["id"] for r in self.client.get("/runs").json()], [saved["id"]]
        )

    def test_runs_under_unknown_designs(self):
        request, task_id = self.run_coverage()
        run = self.save_run(task_id, request).json()
        self.sign_in("b")
        other = self.client.post("/designs", json={"name": "B", "design": DESIGN})
        other = other.json()["id"]
        self.sign_in("a")
        for design_id in (str(uuid4()), other):
            with self.subTest(design_id=design_id):
                response = self.save_run(task_id, request, designId=design_id)
                self.assertEqual(response.status_code, 404, response.text)
                response = self.client.patch(
                    f"/runs/{run['id']}", json={"designId": design_id}
                )
                self.assertEqual(response.status_code, 404, response.text)
        # deleting another user's design does not delete runs under it
        self.assertEqual(self.client.delete(f"/designs/{other}").status_code, 404)

    def test_invalid_updates(self):
        request, task_id = self.run_coverage()
        run = self.save_run(task_id, request).json()
        for body in ({}, {"name": None}, {"name": ""}, {"designId": "x"}):
            with self.subTest(body=body):
                response = self.client.patch(f"/runs/{run['id']}", json=body)
                self.assertEqual(response.status_code, 422, response.text)


class MigrationTestCase(unittest.TestCase):
    def test_migrate_version_1(self):
        # a database of version 1 of the schema, without designs of runs
        path = os.path.join(tempfile.mkdtemp(prefix="tatc-app-test-"), "v1.db")
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(
                """
                CREATE TABLE designs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    name TEXT NOT NULL, data TEXT NOT NULL, created TEXT NOT NULL,
                    updated TEXT NOT NULL);
                CREATE TABLE runs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    name TEXT NOT NULL, analysis TEXT NOT NULL,
                    request TEXT NOT NULL, design TEXT NOT NULL, summary TEXT,
                    created TEXT NOT NULL);
                INSERT INTO designs VALUES ('d', 'u', 'D', '{}', 't', 't');
                INSERT INTO runs VALUES ('r', 'u', 'R', 'coverage', '{}', '{}',
                    NULL, 't');
                PRAGMA user_version=1;
                """
            )
        library = Library(path)
        self.assertEqual(library.list_runs("u")[0]["design_id"], None)
        self.assertEqual(library.list_designs("u")[0]["runs"], 0)
        library.update_run("u", "r", design_id="d")
        self.assertEqual(library.list_designs("u")[0]["runs"], 1)
        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)
        # opening it again does not migrate it again
        self.assertEqual(Library(path).list_runs("u", design_id="d")[0]["id"], "r")
