// Terms of the results of coverage-like analyses (data only, so it imports
// no other module of the app: other modules use it as they load).

// The terms of the results of coverage-like analyses, by type: of the
// observations of points (coverage), or of their coincident observations
// (coincidence), whose results have the same statistics.
export const COVERAGE_TERMS = {
  coverage: {
    observed: "Region observed",
    twice: "observed at least twice",
    neverTwice: "no point is observed twice",
    revisit: "Mean revisit time",
    revisitAxis: "Mean revisit",
    revisitPoints: "Points observed at least twice",
    access: "Mean access time",
    accessDetail: "per observation of observed points",
    curveTitle: "Share of the region observed so far",
    curveSubtitle: "Observed at least once",
    curveColumn: "Observed",
    samples: "Observations"
  },
  // (the area curves of the swath coverage of a region)
  region: {
    curveTitle: "Share of the region's area observed so far",
    curveSubtitle: "Within a swath at least once",
    curveColumn: "Observed"
  },
  regionCommon: {
    curveTitle: "Share of the region's area observed in common so far",
    curveSubtitle: "Within coincident swaths of two satellites at least once",
    curveColumn: "In common"
  },
  coincidence: {
    observed: "Region with coincidences",
    twice: "with at least two",
    neverTwice: "no point has two coincidences",
    revisit: "Mean time between coincidences",
    revisitAxis: "Mean time between coincidences",
    revisitPoints: "Points with at least two coincidences",
    access: "Mean coincidence duration",
    accessDetail: "per coincidence of points with one",
    curveTitle: "Share of the region with a coincidence so far",
    curveSubtitle: "At least one coincidence",
    curveColumn: "With a coincidence",
    samples: "Coincidences"
  }
};
