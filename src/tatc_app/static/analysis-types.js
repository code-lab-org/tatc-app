// The types of analyses of the Analysis tab (`ANALYSES`, in the order of its
// select): each reads its request from the inputs of the tab
// (`readInputs`), sets those inputs from a request, as of a saved run
// (`writeInputs`), and shows the data of its results (`showData`).

import { usesRegion } from "./analysis.js";
import { design } from "./design-state.js";
import { formatValue, showResultsTable } from "./index.js";
import { boxPolygon, getCellsSpec, getPointsSpec, getRegionMask } from "./region.js";
import { renderCoverageSummary, renderLatencySummary, renderRegionSummary } from "./summary.js";
import { COVERAGE_TERMS } from "./terms.js";
import { viewer } from "./viewer.js";

// An invalid input of an analysis, shown as the error of the Analysis tab.
export class InputError extends Error {}

// --- Inputs shared by analyses ---

// Gets a number input, or null if blank.
function optionalNumber(selector) {
  const text = String($(selector).val()).trim();
  return text === "" ? null : Number(text);
}

// Rounds a number to show in an input.
export function inputNumber(value) {
  return Number(Number(value).toFixed(6));
}

// The points and cells of the region (see region.js).
function readGrid() {
  return { points: getPointsSpec(), cells: getCellsSpec() };
}

// Reads the options of sampling sufficiency, or null if not assessed.
function readSufficiency() {
  if (!$("#sufficiency-enabled").is(":checked")) {
    return null;
  }
  const decorrelation = Number($("#sufficiency-decorrelation").val()) *
    Number($("#sufficiency-decorrelation-unit").val());
  const sigma = optionalNumber("#sufficiency-sigma");
  const target = optionalNumber("#sufficiency-target");
  const bins = Number($("#sufficiency-bins").val());
  if (!(decorrelation > 0)) {
    throw new InputError("The decorrelation time must be positive.");
  }
  if (sigma !== null && !(sigma > 0)) {
    throw new InputError("The field's standard deviation must be positive (or blank).");
  }
  if (target !== null && !(target > 0)) {
    throw new InputError("The target error must be positive (or blank).");
  }
  if (!(Number.isInteger(bins) && bins >= 1 && bins <= 24)) {
    throw new InputError("The number of local-time bins must be a whole number from 1 to 24.");
  }
  return {
    decorrelation_time: decorrelation,
    standard_deviation: sigma,
    target_relative_error: target === null ? null : target / 100,
    local_time_bins: bins
  };
}

// Sets the inputs of sampling sufficiency from its options (none to turn it
// off).
function writeSufficiency(sufficiency) {
  $("#sufficiency-enabled").prop("checked", Boolean(sufficiency));
  $("#sufficiency-options").toggle(Boolean(sufficiency));
  if (!sufficiency) {
    return;
  }
  const seconds = Number(sufficiency.decorrelation_time);
  if (seconds > 0) {
    const unit = seconds >= 86400 && seconds % 86400 == 0 ? 86400 : 3600;
    $("#sufficiency-decorrelation-unit").val(String(unit));
    $("#sufficiency-decorrelation").val(inputNumber(seconds / unit));
  }
  const sigma = sufficiency.standard_deviation;
  $("#sufficiency-sigma").val(sigma === null || sigma === undefined ? "" : sigma);
  const target = sufficiency.target_relative_error;
  $("#sufficiency-target").val(target === null || target === undefined ? "" : inputNumber(100 * target));
  if (sufficiency.local_time_bins) {
    $("#sufficiency-bins").val(sufficiency.local_time_bins);
  }
}

// Reads the options of ground sample sizes, or null if not sized.
function readSampleSize() {
  if (!$("#sample-size-enabled").is(":checked")) {
    return null;
  }
  const km = optionalNumber("#sample-size-max");
  if (km !== null && !(km > 0)) {
    throw new InputError("The maximum sample size must be positive (or blank).");
  }
  return { max_sample_size: km === null ? null : km * 1000 };
}

// Sets the inputs of ground sample sizes from their options (none to turn
// them off).
function writeSampleSize(sampleSize) {
  $("#sample-size-enabled").prop("checked", Boolean(sampleSize));
  $("#sample-size-options").toggle(Boolean(sampleSize));
  const max = sampleSize && sampleSize.max_sample_size;
  $("#sample-size-max").val(max ? inputNumber(max / 1000) : "");
}

// Reads the options of coincident observations.
function readCoincidence() {
  const minPlatforms = Number($("#coincidence-min").val());
  const minutes = Number($("#coincidence-difference").val());
  if (!(Number.isInteger(minPlatforms) && minPlatforms >= 2 && minPlatforms <= 20)) {
    throw new InputError("The number of platforms at once must be a whole number from 2 to 20.");
  }
  if (!(minutes >= 0)) {
    throw new InputError("The maximum time difference must not be negative.");
  }
  return {
    min_platforms: minPlatforms,
    max_time_difference: minutes * 60,
    instantaneous: $("#coincidence-instantaneous").is(":checked"),
    platforms: $("#coincidence-platforms").val()
  };
}

// Sets the inputs of coincident observations from a request.
function writeCoincidence(request) {
  $("#coincidence-min").val(request.min_platforms || 2);
  $("#coincidence-difference").val(inputNumber((request.max_time_difference || 0) / 60));
  $("#coincidence-instantaneous").prop("checked", Boolean(request.instantaneous));
  $("#coincidence-platforms").val(request.platforms || "members");
}

// --- Data shared by analyses ---

function fixed2(value) {
  return Number(value).toFixed(2);
}

function hours(seconds) {
  return seconds === null ? null : seconds / 3600;
}

// The columns of the statistics of points shared by results of a type.
function pointColumns(type) {
  return [
    { title: "Target", key: "target_hash" },
    { title: "Latitude (°)", key: "latitude_deg", format: fixed2 },
    { title: "Longitude (°)", key: "longitude_deg", format: fixed2 },
    { title: (COVERAGE_TERMS[type] || COVERAGE_TERMS.coverage).samples, key: "samples" }
  ];
}

// The rows of the statistics of points of results, with the shared columns
// (see `pointColumns`) and the values of each point's properties.
function pointRows(result, values) {
  return _.map(result.points.features, function(feature) {
    return _.assign({
      target_hash: feature.properties.target_hash,
      latitude_deg: feature.geometry.coordinates[1],
      longitude_deg: feature.geometry.coordinates[0],
      samples: feature.properties.samples
    }, values(feature.properties));
  });
}

// Shows the statistics of points of coverage or coincidence results, with
// those of their sampling sufficiency and ground sample sizes, if assessed.
function showCoverageData(analysis, onCompare) {
  const result = analysis.result;
  const terms = COVERAGE_TERMS[analysis.type];
  const coincidence = analysis.type == "coincidence";
  const sufficiency = result.summary && result.summary.sufficiency;
  const sampleSize = result.summary && result.summary.sample_size;
  const percent = function(share) { return share === null || share === undefined ? null : 100 * share; };
  const km = function(meters) { return meters === null || meters === undefined ? null : meters / 1000; };
  let columns = pointColumns(analysis.type).concat([
    { title: coincidence ? "Mean coincidence duration (s)" : "Mean access (s)", key: "access_s", format: fixed2 },
    { title: terms.revisitAxis + " (h)", key: "revisit_h", format: fixed2 }
  ]);
  if (sufficiency) {
    columns = columns.concat(
      [{ title: "Sampling error (% of σ)", key: "relative_error_pct", format: fixed2 }],
      sufficiency.standard_deviation ? [{ title: "Sampling error", key: "sampling_error", format: fixed2 }] : [],
      [
        { title: "Effective samples", key: "effective_samples", format: fixed2 },
        { title: "Median time between samples (h)", key: "revisit_p50_h", format: fixed2 },
        { title: "90th pct. time between samples (h)", key: "revisit_p90_h", format: fixed2 },
        { title: "Longest gap (h)", key: "max_gap_h", format: fixed2 },
        { title: "Local-time coverage (%)", key: "local_time_pct", format: fixed2 }
      ]
    );
  }
  if (sampleSize) {
    columns = columns.concat(
      [
        { title: "Median sample size (km)", key: "sample_size_median_km", format: fixed2 },
        { title: "Smallest sample size (km)", key: "sample_size_min_km", format: fixed2 },
        { title: "Observations sized", key: "observations_sized" }
      ],
      sampleSize.max_sample_size
        ? [{ title: "Observations at most " + formatValue(sampleSize.max_sample_size / 1000) + " km", key: "observations_meeting" }]
        : []
    );
  }
  showResultsTable({
    title: coincidence ? "Coincidence Statistics" : "Coverage Statistics",
    columns: columns,
    rows: pointRows(result, function(p) {
      return _.assign({ access_s: p.access, revisit_h: hours(p.revisit) }, sufficiency ? {
        relative_error_pct: percent(p.relative_error),
        sampling_error: p.sampling_error,
        effective_samples: p.effective_samples,
        revisit_p50_h: hours(p.revisit_p50),
        revisit_p90_h: hours(p.revisit_p90),
        max_gap_h: hours(p.max_gap),
        local_time_pct: percent(p.local_time_coverage)
      } : {}, sampleSize ? {
        sample_size_median_km: km(p.sample_size_median),
        sample_size_min_km: km(p.sample_size_min),
        observations_sized: p.observations_sized,
        observations_meeting: p.observations_meeting
      } : {});
    }),
    filename: analysis.type + "-points",
    note: (coincidence
      ? "Statistics of the coincident observations of each point over the analysis period: periods when enough platforms observe it at once."
      : "Statistics of each point over the analysis period. Overlapping observations by several satellites count once.") +
      (sufficiency ? " " + terms.revisitAxis + " runs from the end of one to the start of the next; times between samples run between their midpoints." : ""),
    summary: result.summary ? function(container) { renderCoverageSummary(container, result.summary, terms); } : null,
    onCompare: onCompare
  });
}

// --- Analysis types ---

// For each analysis: whether it analyzes a region (`"optional"` if it may,
// see `usesRegion`), whether it samples a grid of points and cells of the
// region (or else analyzes the region itself, shown by its outline), and
// whether it shows its results with a layer of targets (points and cells
// colored by a metric, see `DISPLAY_MODES`). `readInputs(base)` adds its
// inputs to the inputs shared by all analyses (see `getBasePayload`),
// throwing an `InputError` if invalid, and `showData(analysis, onCompare)`
// shows its results (see `analysisResult`).
export const ANALYSES = {
  coverage: {
    label: "Coverage and Revisit",
    description: "Observations of a grid of points (and cells) by the checked instruments of the checked satellites. " +
      "Animates observations accumulating over the analysis period, or shows final revisit statistics.",
    region: true,
    grid: true,
    targetLayer: true,
    endpoint: "/analyze/coverage",
    readInputs: function(base) {
      return _.assign(base, readGrid(), {
        sufficiency: readSufficiency(),
        sample_size: readSampleSize()
      });
    },
    writeInputs: function(request) {
      writeSufficiency(request.sufficiency);
      writeSampleSize(request.sample_size);
    },
    showData: showCoverageData
  },
  coincidence: {
    label: "Coincident Observations",
    description: "Periods when several of the checked satellites (or satellites and constellations) observe a point of the grid at once, " +
      "as for cross-calibration or multi-sensor matchups. Animates coincidences accumulating, or shows final statistics.",
    region: true,
    grid: true,
    targetLayer: true,
    endpoint: "/analyze/coincidence",
    readInputs: function(base) {
      return _.assign(base, readGrid(), {
        sufficiency: readSufficiency(),
        sample_size: readSampleSize()
      }, readCoincidence());
    },
    writeInputs: function(request) {
      writeCoincidence(request);
      writeSufficiency(request.sufficiency);
      writeSampleSize(request.sample_size);
    },
    showData: showCoverageData
  },
  swaths: {
    label: "Ground Track Swaths",
    description: "Ground track swaths of the checked instruments, accumulating in segments over the animation. " +
      "Limited to a region, also the share of its area observed over the analysis period, its observations and revisit, " +
      "and optionally the areas several satellites observe in common within a time difference.",
    region: "optional",
    grid: false,
    targetLayer: false,
    endpoint: "/analyze/swaths",
    readInputs: function(base) {
      const step = Number($("#swaths-step").val());
      const segment = Number($("#swaths-segment").val());
      if (!(step > 0) || !(segment > 0)) {
        throw new InputError("The step and segment must be positive.");
      }
      const region = usesRegion("swaths");
      let coincidence = null;
      if (region && $("#swaths-coincidence-enabled").is(":checked")) {
        const minutes = Number($("#swaths-coincidence-difference").val());
        if (!(minutes >= 0)) {
          throw new InputError("The maximum time difference must not be negative.");
        }
        coincidence = {
          max_time_difference: minutes * 60,
          platforms: $("#swaths-coincidence-platforms").val()
        };
      }
      // swaths over the animation; with a region, its coverage over the
      // analysis period (a global region is the whole globe, not none)
      return _.assign(base, {
        region: region ? (getRegionMask() || boxPolygon(-180, -90, 180, 90)) : null,
        instrument_index: null,
        step: step,
        segment: segment * 60,
        coincidence: coincidence
      });
    },
    writeInputs: function(request) {
      $("#swaths-step").val(request.step);
      if (request.segment) {
        $("#swaths-segment").val(request.segment / 60);
      }
      $("#swaths-region-enabled").prop("checked", Boolean(request.region)).trigger("change");
      const coincidence = request.coincidence;
      $("#swaths-coincidence-enabled").prop("checked", Boolean(coincidence));
      $("#swaths-coincidence-options").toggle(Boolean(coincidence));
      if (coincidence) {
        $("#swaths-coincidence-difference").val(inputNumber((coincidence.max_time_difference || 0) / 60));
        $("#swaths-coincidence-platforms").val(coincidence.platforms || "members");
      }
    },
    showData: function(analysis, onCompare) {
      const result = analysis.result;
      if (!result.summary) {
        showResultsTable({
          title: "Swath Segments",
          columns: [
            { title: "Satellite", key: "satellite" },
            { title: "Instrument", key: "instrument" },
            { title: "Start (UTC)", key: "start" },
            { title: "End (UTC)", key: "end" }
          ],
          rows: _.map(result.swaths.features, "properties"),
          filename: "swath-segments",
          note: "Segments over the animation; each appears once it ends. Download the full geometry with the API."
        });
        return;
      }
      // over a region: its observations, with the swath segments as extras
      const segments = {
        label: "Swath segments CSV",
        filename: "swath-segments.csv",
        columns: ["satellite", "instrument", "start", "end"],
        rows: _.map(result.swaths.features, function(feature) {
          const p = feature.properties;
          return [p.satellite, p.instrument, p.start, p.end];
        })
      };
      const epoch = new Date(analysis.payload.start).getTime();
      const iso = function(seconds) { return new Date(epoch + seconds * 1000).toISOString(); };
      showResultsTable({
        title: "Observations of the Region",
        columns: [
          { title: "Satellites", key: "satellite" },
          { title: "Instruments", key: "instrument" },
          { title: "Start (UTC)", key: "start_utc" },
          { title: "End (UTC)", key: "end_utc" },
          { title: "Duration (min)", key: "duration_min", format: fixed2 }
        ],
        rows: _.map(result.observations, function(o) {
          return {
            satellite: o.satellite,
            instrument: o.instrument,
            start_utc: iso(o.start),
            end_utc: iso(o.end),
            duration_min: (o.end - o.start) / 60
          };
        }),
        filename: "region-observations",
        note: "Periods over the analysis period when any part of the region is observed (overlapping observations merged). " +
          "Swaths show over the animation: click a row within it to jump to it.",
        summary: function(container) { renderRegionSummary(container, result.summary); },
        onCompare: onCompare,
        extras: [segments],
        onRowClick: function(row) {
          const start = Cesium.JulianDate.fromIso8601(row.start_utc);
          if (Cesium.JulianDate.greaterThan(start, viewer.clock.stopTime)) {
            return;
          }
          viewer.clock.currentTime = start;
          viewer.clock.shouldAnimate = true;
          $("#results-dialog").modal("hide");
        }
      });
    }
  },
  latency: {
    label: "Data Latency (Ground Stations)",
    description: "Latency from the observation of each point to its downlink at a ground station. " +
      "Animates contacts with ground stations and observations awaiting downlink.",
    region: true,
    grid: true,
    targetLayer: true,
    endpoint: "/analyze/latency",
    readInputs: function(base) {
      if (design.stations.length == 0) {
        throw new InputError("Add at least one ground station.");
      }
      return _.assign(base, readGrid(), {
        stations: design.stations,
        during_contact: $("#latency-contact").val()
      });
    },
    writeInputs: function(request) {
      if (request.during_contact) {
        $("#latency-contact").val(request.during_contact);
      }
    },
    showData: function(analysis, onCompare) {
      const result = analysis.result;
      const contacts = result.contacts;
      const epoch = new Date(contacts.epoch).getTime();
      showResultsTable({
        title: "Data Latency Statistics",
        columns: pointColumns("latency").concat([{ title: "Mean latency (h)", key: "latency_h", format: fixed2 }]),
        rows: pointRows(result, function(p) { return { latency_h: hours(p.latency) }; }),
        filename: "latency-points",
        note: "Statistics of each point over the analysis period.",
        summary: result.summary ? function(container) { renderLatencySummary(container, result.summary); } : null,
        onCompare: onCompare,
        extras: [{
          label: "Contacts CSV",
          filename: "latency-contacts.csv",
          columns: ["satellite", "ground_station", "start", "end", "duration_s"],
          rows: _.map(contacts.start, function(start, k) {
            const end = contacts.end[k];
            return [
              contacts.members[contacts.member[k]],
              contacts.targets[contacts.target[k]],
              new Date(epoch + start * 1000).toISOString(),
              end === null ? "" : new Date(epoch + end * 1000).toISOString(),
              end === null ? "" : (end - start).toFixed(1)
            ];
          })
        }]
      });
    }
  },
  access: {
    label: "Point Access (Overflight)",
    description: "Accesses of selected target points by each satellite, with lines of sight " +
      "animated during each access and a table of access windows.",
    region: false,
    grid: false,
    targetLayer: false,
    endpoint: "/analyze/overflight",
    readInputs: function(base) {
      if (design.targets.length == 0) {
        throw new InputError("Add at least one target point.");
      }
      return _.assign(base, {
        points: _.map(design.targets, function(target, i) {
          return { id: i, latitude: target.latitude, longitude: target.longitude };
        }),
        omit_solar: !$("#access-solar").is(":checked")
      });
    },
    writeInputs: function(request) {
      $("#access-solar").prop("checked", !request.omit_solar);
    },
    showData: function(analysis) {
      const result = analysis.result;
      const ids = _.map(result.points.features, function(f) { return f.properties.id; });
      const hashes = _.map(result.points.features, function(f) { return f.properties.point_id; });
      const columns = [
        { title: "Target", key: "target" },
        { title: "Satellite", key: "satellite" },
        { title: "Instrument", key: "instrument" },
        { title: "Start (UTC)", key: "start" },
        { title: "End (UTC)", key: "end" },
        { title: "Duration (s)", key: "duration_s", format: fixed2 },
        { title: "Max. elevation (°)", key: "platform_alt", format: fixed2 }
      ];
      if (!analysis.payload.omit_solar) {
        columns.push({ title: "Solar elevation (°)", key: "solar_alt", format: fixed2 });
      }
      showResultsTable({
        title: "Point Accesses",
        columns: columns,
        rows: _.map(result.observations.features, function(feature) {
          const p = feature.properties;
          const index = _.indexOf(hashes, p.target_hash);
          return _.assign({}, p, {
            target: index >= 0 ? "Point " + ids[index] : p.target_hash,
            duration_s: (new Date(p.end) - new Date(p.start)) / 1000
          });
        }),
        filename: "point-accesses",
        note: "Click a row to jump the animation to that access.",
        onRowClick: function(row) {
          const start = Cesium.JulianDate.fromIso8601(row.start);
          viewer.clock.currentTime = Cesium.JulianDate.addSeconds(start, -60, new Cesium.JulianDate());
          viewer.clock.shouldAnimate = true;
          $("#results-dialog").modal("hide");
        }
      });
    }
  }
};
