"""
Fakes of CelesTrak downloads, for tests of the CelesTrak and system catalogs.
"""


def omm_record(name: str, catalog_number: int, object_id: str) -> dict:
    """
    Creates an OMM record, as in CelesTrak's JSON format.
    """
    return {
        "OBJECT_NAME": name,
        "OBJECT_ID": object_id,
        "EPOCH": "2026-11-20T12:00:00.000000",
        "MEAN_MOTION": 15.5,
        "ECCENTRICITY": 0.0003,
        "INCLINATION": 51.6,
        "RA_OF_ASC_NODE": 41.5,
        "ARG_OF_PERICENTER": 68.0,
        "MEAN_ANOMALY": 78.3,
        "EPHEMERIS_TYPE": 0,
        "CLASSIFICATION_TYPE": "U",
        "NORAD_CAT_ID": catalog_number,
        "ELEMENT_SET_NO": 999,
        "REV_AT_EPOCH": 100,
        "BSTAR": 0.0001,
        "MEAN_MOTION_DOT": 1e-5,
        "MEAN_MOTION_DDOT": 0,
    }


RECORDS = [
    omm_record("ISS (ZARYA)", 25544, "1998-067A"),
    omm_record("LANDSAT 8", 39084, "2013-008A"),
    omm_record("LANDSAT 9", 49260, "2021-088A"),
    omm_record("ALPHA FIVE SAT", 212345, "2026-001A"),
    omm_record("NINE DIGIT SAT", 812345678, "2026-002A"),
]


class FakeDownload:
    """
    Replaces downloads from CelesTrak, counting calls.
    """

    def __init__(self, records=RECORDS, error: Exception | None = None):
        self.records = records
        self.error = error
        self.calls = 0

    async def __call__(self, group: str) -> list[dict]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.records


class FakeObjectDownload:
    """
    Replaces downloads of objects (by catalog number) from CelesTrak,
    recording the catalog numbers queried.
    """

    def __init__(self, records=(), error: Exception | None = None):
        self.records = {int(r["NORAD_CAT_ID"]): r for r in records}
        self.error = error
        self.calls = []

    async def __call__(self, catalog_number: int) -> dict | None:
        self.calls.append(catalog_number)
        if self.error:
            raise self.error
        return self.records.get(catalog_number)
