// Summaries of coverage and latency results over a region (`summary` of
// their results, see the server's `analysis/summary.py`): a row of headline
// statistics and charts (the share of the region observed over time, and a
// histogram of revisit or latency times), each with a table of its data.
// Charts are plain SVG, styled by the `summary-` classes of styles.css.

const SVG_NS = "http://www.w3.org/2000/svg";

// chart geometry (SVG user units; charts scale to their container's width)
const CHART = { width: 520, height: 220, top: 14, right: 40, bottom: 36, left: 46 };
// the size of the plot area, within the margins
const PLOT = {
  width: CHART.width - CHART.left - CHART.right,
  height: CHART.height - CHART.top - CHART.bottom
};

// The terms of the results of coverage-like analyses, by type: of the
// observations of points (coverage), or of their coincident observations
// (coincidence), whose results have the same statistics.
const COVERAGE_TERMS = {
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

// --- Axes ---

// Gets about `count` round tick values from 0 to (at least) a maximum.
function niceTicks(max, count) {
  if (!(max > 0)) {
    return [0, 1];
  }
  const rough = max / (count || 4);
  const power = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = _.find([1, 2, 2.5, 5, 10], function(m) { return m * power >= rough; }) * power;
  return _.map(_.range(0, Math.ceil(max / step - 1e-9) + 1), function(i) { return i * step; });
}

// --- DOM helpers ---

function svgElement(name, attributes) {
  const element = document.createElementNS(SVG_NS, name);
  _.forEach(attributes, function(value, key) { element.setAttribute(key, value); });
  return element;
}

function svgText(text, attributes) {
  const element = svgElement("text", attributes);
  element.textContent = text;
  return element;
}

// Creates a chart card: a title, the SVG plot (with a tooltip), and a
// collapsible table of the chart's data.
function chartCard(title, subtitle, table) {
  const card = $("<div>").addClass("summary-chart");
  card.append($("<div>").addClass("summary-chart-title").text(title));
  if (subtitle) {
    card.append($("<div>").addClass("summary-chart-subtitle").text(subtitle));
  }
  const plot = $("<div>").addClass("summary-plot").appendTo(card);
  const svg = svgElement("svg", {
    viewBox: "0 0 " + CHART.width + " " + CHART.height,
    role: "img",
    "aria-label": title
  });
  plot.append(svg);
  const tooltip = $("<div>").addClass("summary-tooltip").attr("role", "status").hide().appendTo(plot);
  const details = $("<details>").addClass("summary-data").appendTo(card);
  details.append($("<summary>").text("Chart data"));
  const tableElement = $("<table>").addClass("table table-sm small mb-0").appendTo(details);
  tableElement.append($("<thead>").append($("<tr>").append(_.map(table.columns, function(column) {
    return $("<th>").text(column);
  }))));
  tableElement.append($("<tbody>").append(_.map(table.rows, function(row) {
    return $("<tr>").append(_.map(row, function(value) { return $("<td>").text(value); }));
  })));
  return { card: card, svg: svg, plot: plot, tooltip: tooltip };
}

// Shows the tooltip of a chart at a position (SVG units), with a value (the
// strong element) and a label.
function showTooltip(chart, x, y, value, label) {
  chart.tooltip.empty().append(
    $("<div>").addClass("summary-tooltip-value").text(value),
    $("<div>").addClass("summary-tooltip-label").text(label)
  ).show();
  const scale = chart.plot.width() / CHART.width || 1;
  const left = Math.min(x * scale + 10, chart.plot.width() - chart.tooltip.outerWidth());
  chart.tooltip.css({ left: Math.max(0, left) + "px", top: Math.max(0, y * scale - 48) + "px" });
}

// Gets the x-axis ticks (values with positions, by `x`) of round values of a
// quantity in a unit ({label, seconds}, the size of one unit), from 0 to a
// maximum.
function axisTicks(max, unit, x) {
  return _.map(_.filter(niceTicks(max / unit.seconds, 5), function(v) {
    return v * unit.seconds <= max * 1.0001;
  }), function(v) { return { x: x(v * unit.seconds), label: formatValue(v) }; });
}

// Draws the gridlines and y-axis labels (shares, 0 to `max`), and the x-axis
// labels at `xTicks` (values with positions).
function drawAxes(svg, yMax, yTicks, xTicks, xTitle) {
  const axes = svgElement("g", { class: "summary-axes" });
  _.forEach(yTicks, function(tick) {
    const y = CHART.top + PLOT.height * (1 - tick / yMax);
    axes.appendChild(svgElement("line", {
      x1: CHART.left, x2: CHART.left + PLOT.width, y1: y, y2: y, class: "summary-grid"
    }));
    axes.appendChild(svgText(formatValue(100 * tick) + "%", {
      x: CHART.left - 6, y: y + 4, "text-anchor": "end", class: "summary-tick"
    }));
  });
  _.forEach(xTicks, function(tick) {
    axes.appendChild(svgText(tick.label, {
      x: tick.x, y: CHART.top + PLOT.height + 16, "text-anchor": "middle", class: "summary-tick"
    }));
  });
  axes.appendChild(svgText(xTitle, {
    x: CHART.left + PLOT.width / 2, y: CHART.height - 4, "text-anchor": "middle", class: "summary-axis-title"
  }));
  svg.appendChild(axes);
}

// Adds the overlay over the plot of a line chart that tracks the pointer and
// moves along the plot with the arrow keys (by `step`, a fraction of its
// width, or 10 times that with shift): calls `show(fraction)`, from 0 at the
// left of the plot to 1 at the right, as it moves (from the right when first
// focused), and `hide()` as it leaves.
function addPlotOverlay(chart, label, step, show, hide) {
  const overlay = svgElement("rect", {
    x: CHART.left, y: CHART.top, width: PLOT.width, height: PLOT.height,
    fill: "transparent", tabindex: 0, "aria-label": label
  });
  chart.svg.appendChild(overlay);
  let current = 1;
  function move(fraction) {
    current = Math.max(0, Math.min(1, fraction));
    show(current);
  }
  overlay.addEventListener("pointermove", function(event) {
    const box = chart.svg.getBoundingClientRect();
    const svgX = (event.clientX - box.left) * CHART.width / box.width;
    move((svgX - CHART.left) / PLOT.width);
  });
  overlay.addEventListener("pointerleave", hide);
  overlay.addEventListener("focus", function() { move(current); });
  overlay.addEventListener("blur", hide);
  overlay.addEventListener("keydown", function(event) {
    const delta = (event.shiftKey ? 10 : 1) * step;
    if (event.key == "ArrowRight") { move(current + delta); event.preventDefault(); }
    if (event.key == "ArrowLeft") { move(current - delta); event.preventDefault(); }
  });
}

// --- Charts ---

// Line (and area) chart of the share of the region observed over time, with
// a crosshair and tooltip that snap to the nearest sample.
function coverageChart(curve, terms) {
  terms = terms || COVERAGE_TERMS.coverage;
  const duration = _.last(curve.times) || 1;
  const unit = durationUnit(duration);
  const rows = _.map(_.range(0, curve.times.length, Math.max(1, Math.floor(curve.times.length / 20))), function(i) {
    return [formatValue(curve.times[i] / unit.seconds), formatShare(curve.shares[i])];
  });
  const chart = chartCard(
    terms.curveTitle,
    terms.curveSubtitle + ", since the start of the analysis",
    { columns: ["Time (" + unit.label + ")", terms.curveColumn], rows: rows }
  );
  const x = function(t) { return CHART.left + PLOT.width * t / duration; };
  const y = function(share) { return CHART.top + PLOT.height * (1 - share); };
  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = axisTicks(duration, unit, x);
  drawAxes(chart.svg, 1, yTicks, xTicks, "Time since start (" + unit.label + ")");

  const points = _.map(curve.times, function(t, i) { return [x(t), y(curve.shares[i])]; });
  const line = _.map(points, function(p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1); }).join("");
  chart.svg.appendChild(svgElement("path", {
    d: line + "L" + x(duration) + "," + y(0) + "L" + x(0) + "," + y(0) + "Z", class: "summary-area"
  }));
  chart.svg.appendChild(svgElement("path", { d: line, class: "summary-line" }));
  // direct label of the final value at the end of the line
  const end = _.last(points);
  chart.svg.appendChild(svgText(formatShare(_.last(curve.shares)), {
    x: end[0] + 6, y: end[1] + 4, class: "summary-end-label"
  }));

  // crosshair and marker at the sample nearest the pointer (keys step by
  // samples)
  const crosshair = svgElement("line", { y1: CHART.top, y2: CHART.top + PLOT.height, class: "summary-crosshair", visibility: "hidden" });
  const marker = svgElement("circle", { r: 4, class: "summary-marker", visibility: "hidden" });
  chart.svg.appendChild(crosshair);
  chart.svg.appendChild(marker);
  const samples = Math.max(1, points.length - 1);
  addPlotOverlay(chart, "Share observed over time (use the arrow keys)", 1 / samples, function(fraction) {
    const i = Math.min(Math.round(fraction * samples), points.length - 1);
    const p = points[i];
    crosshair.setAttribute("x1", p[0]);
    crosshair.setAttribute("x2", p[0]);
    crosshair.setAttribute("visibility", "visible");
    marker.setAttribute("cx", p[0]);
    marker.setAttribute("cy", p[1]);
    marker.setAttribute("visibility", "visible");
    showTooltip(chart, p[0], p[1], formatShare(curve.shares[i]),
      "observed by " + formatDuration(curve.times[i], unit));
  }, function() {
    crosshair.setAttribute("visibility", "hidden");
    marker.setAttribute("visibility", "hidden");
    chart.tooltip.hide();
  });
  return chart.card;
}

// Column chart of a histogram: the shares of points (or of another
// `options.of`, such as samples) in equal-width bins of a statistic, each
// column with its own hover and focus tooltip. The axis is labeled by `axis`
// in a unit (`options.unit`: {label, seconds}, the size of one unit in the
// histogram's values; by default, a unit of durations in seconds).
function histogramChart(histogram, title, subtitle, axis, options) {
  options = options || {};
  const of = options.of || "points";
  const maxEdge = _.last(histogram.edges);
  const unit = options.unit || durationUnit(maxEdge);
  const bins = _.map(histogram.shares, function(share, i) {
    return { from: histogram.edges[i], to: histogram.edges[i + 1], share: share };
  });
  const binLabel = function(bin) {
    return formatValue(bin.from / unit.seconds) + "–" + formatValue(bin.to / unit.seconds) + " " + unit.label;
  };
  const chart = chartCard(title, subtitle, {
    columns: [axis + " (" + unit.label + ")", "Share of " + of],
    rows: _.map(bins, function(bin) { return [binLabel(bin), formatShare(bin.share)]; })
  });
  const yTicks = niceTicks(_.max(histogram.shares) || 1, 4);
  const yMax = _.last(yTicks);
  const x = function(seconds) { return CHART.left + PLOT.width * seconds / maxEdge; };
  const y = function(share) { return CHART.top + PLOT.height * (1 - share / yMax); };
  const xTicks = axisTicks(maxEdge, unit, x);
  drawAxes(chart.svg, yMax, yTicks, xTicks, axis + " (" + unit.label + ")");

  const slot = PLOT.width / bins.length;
  // columns at most 24 units wide, with a 2-unit gap between neighbors
  const width = Math.min(24, slot - 2);
  _.forEach(bins, function(bin, i) {
    const left = CHART.left + i * slot + (slot - width) / 2;
    const top = y(bin.share);
    const height = CHART.top + PLOT.height - top;
    if (height > 0) {
      // rounded at the data end (top), square at the baseline
      const r = Math.min(4, height, width / 2);
      chart.svg.appendChild(svgElement("path", {
        d: "M" + left + "," + (top + height) + "V" + (top + r) +
          "Q" + left + "," + top + " " + (left + r) + "," + top +
          "H" + (left + width - r) +
          "Q" + (left + width) + "," + top + " " + (left + width) + "," + (top + r) +
          "V" + (top + height) + "Z",
        class: "summary-bar",
        "data-bin": i
      }));
    }
    // the hit target is the whole slot, taller and wider than the column
    const hit = svgElement("rect", {
      x: CHART.left + i * slot, y: CHART.top, width: slot, height: PLOT.height,
      fill: "transparent", tabindex: 0,
      "aria-label": binLabel(bin) + ": " + formatShare(bin.share) + " of " + of
    });
    const highlight = function(on) {
      $(chart.svg).find(".summary-bar[data-bin='" + i + "']").toggleClass("hover", on);
      if (on) {
        showTooltip(chart, CHART.left + (i + 0.5) * slot, top, formatShare(bin.share), "of " + of + ", " + binLabel(bin));
      } else {
        chart.tooltip.hide();
      }
    };
    hit.addEventListener("pointerenter", function() { highlight(true); });
    hit.addEventListener("pointerleave", function() { highlight(false); });
    hit.addEventListener("focus", function() { highlight(true); });
    hit.addEventListener("blur", function() { highlight(false); });
    chart.svg.appendChild(hit);
  });
  return chart.card;
}

// Gets the share of a coverage curve at a time (the latest sample at or
// before it), or null past the end of its analysis period.
function curveShareAt(curve, t) {
  if (t > _.last(curve.times) + 1e-6) {
    return null;
  }
  const i = _.sortedLastIndex(curve.times, t + 1e-6) - 1;
  return curve.shares[Math.max(0, i)];
}

// Line chart comparing the share of the region observed over time of
// several runs (`series`: {name, color, curve}), with a legend, end labels
// where they do not collide, and a crosshair whose tooltip lists every run.
function comparisonChart(series, terms) {
  terms = terms || COVERAGE_TERMS.coverage;
  const duration = _.max(_.map(series, function(s) { return _.last(s.curve.times); })) || 1;
  const unit = durationUnit(duration);
  const times = _.range(0, 11).map(function(i) { return duration * i / 10; });
  const chart = chartCard(
    terms.curveTitle,
    terms.curveSubtitle + ", since the start of each analysis",
    {
      columns: ["Time (" + unit.label + ")"].concat(_.map(series, "name")),
      rows: _.map(times, function(t) {
        return [formatValue(t / unit.seconds)].concat(_.map(series, function(s) {
          const share = curveShareAt(s.curve, t);
          return share === null ? "–" : formatShare(share);
        }));
      })
    }
  );
  if (series.length > 1) {
    const legend = $("<div>").addClass("summary-legend");
    _.forEach(series, function(s) {
      legend.append($("<span>").addClass("summary-legend-item").append(
        $("<span>").addClass("summary-line-key").css("background", s.color),
        $("<span>").text(s.name)
      ));
    });
    chart.plot.before(legend);
  }
  const x = function(t) { return CHART.left + PLOT.width * t / duration; };
  const y = function(share) { return CHART.top + PLOT.height * (1 - share); };
  const xTicks = axisTicks(duration, unit, x);
  drawAxes(chart.svg, 1, [0, 0.25, 0.5, 0.75, 1], xTicks, "Time since start (" + unit.label + ")");

  const ends = [];
  _.forEach(series, function(s, k) {
    const d = _.map(s.curve.times, function(t, i) {
      return (i ? "L" : "M") + x(t).toFixed(1) + "," + y(s.curve.shares[i]).toFixed(1);
    }).join("");
    chart.svg.appendChild(svgElement("path", { d: d, class: "summary-line", style: "stroke:" + s.color }));
    ends.push({
      series: k, t: _.last(s.curve.times),
      x: x(_.last(s.curve.times)), y: y(_.last(s.curve.shares)), label: formatShare(_.last(s.curve.shares))
    });
  });
  // end labels, skipping any that would collide with one already placed or
  // sit on another run's line (the legend and tooltip identify every run)
  const placed = [];
  _.forEach(ends, function(end) {
    const onLabel = _.some(placed, function(p) { return Math.abs(p.x - end.x) < 40 && Math.abs(p.y - end.y) < 14; });
    const onLine = _.some(series, function(s, k) {
      if (k === end.series) {
        return false;
      }
      // the other line beside the label (just past the end of this one)
      const share = curveShareAt(s.curve, Math.min(end.t + duration * 0.02, _.last(s.curve.times)));
      return _.last(s.curve.times) > end.t && share !== null && Math.abs(y(share) - end.y) < 10;
    });
    if (onLabel || onLine) {
      return;
    }
    placed.push(end);
    chart.svg.appendChild(svgText(end.label, { x: end.x + 6, y: end.y + 4, class: "summary-end-label" }));
  });

  const crosshair = svgElement("line", { y1: CHART.top, y2: CHART.top + PLOT.height, class: "summary-crosshair", visibility: "hidden" });
  chart.svg.appendChild(crosshair);
  const markers = _.map(series, function(s) {
    const marker = svgElement("circle", { r: 4, class: "summary-marker", style: "fill:" + s.color, visibility: "hidden" });
    chart.svg.appendChild(marker);
    return marker;
  });
  addPlotOverlay(chart, "Shares observed over time (use the arrow keys)", 0.01, function(fraction) {
    const t = fraction * duration;
    crosshair.setAttribute("x1", x(t));
    crosshair.setAttribute("x2", x(t));
    crosshair.setAttribute("visibility", "visible");
    chart.tooltip.empty().append($("<div>").addClass("summary-tooltip-label").text(formatDuration(t, unit) + " since start"));
    _.forEach(series, function(s, k) {
      const share = curveShareAt(s.curve, t);
      markers[k].setAttribute("visibility", share === null ? "hidden" : "visible");
      if (share !== null) {
        markers[k].setAttribute("cx", x(t));
        markers[k].setAttribute("cy", y(share));
      }
      chart.tooltip.append($("<div>").addClass("summary-tooltip-row").append(
        $("<span>").addClass("summary-line-key").css("background", s.color),
        $("<span>").addClass("summary-tooltip-value").text(share === null ? "–" : formatShare(share)),
        $("<span>").addClass("summary-tooltip-label").text(s.name)
      ));
    });
    chart.tooltip.show();
    const scale = chart.plot.width() / CHART.width || 1;
    const left = Math.min(x(t) * scale + 12, chart.plot.width() - chart.tooltip.outerWidth());
    chart.tooltip.css({ left: Math.max(0, left) + "px", top: "0px" });
  }, function() {
    crosshair.setAttribute("visibility", "hidden");
    _.forEach(markers, function(m) { m.setAttribute("visibility", "hidden"); });
    chart.tooltip.hide();
  });
  return chart.card;
}

// --- Summaries ---

// A stat tile: a label, a value, and an optional detail line.
function statTile(label, value, detail) {
  return $("<div>").addClass("summary-tile").append(
    $("<div>").addClass("summary-tile-label").text(label),
    $("<div>").addClass("summary-tile-value").text(value),
    detail ? $("<div>").addClass("summary-tile-detail").text(detail) : null
  );
}

function distributionDetail(distribution, unit) {
  return "median " + formatDuration(distribution.median, unit) +
    " · 90th percentile " + formatDuration(distribution.p90, unit);
}

function weightingNote(summary) {
  return summary.weighting == "area"
    ? "Shares and statistics weight each of the " + summary.points.toLocaleString() +
      " points by the area it represents (points equally spaced in latitude and longitude crowd toward the poles)."
    : "Shares and statistics weight each of the " + summary.points.toLocaleString() + " points equally.";
}

// Renders the summary of coverage (or coincidence, by `terms`, see
// `COVERAGE_TERMS`) results in a container.
function renderCoverageSummary(container, summary, terms) {
  terms = terms || COVERAGE_TERMS.coverage;
  const root = $("<div>").addClass("summary").appendTo($(container).empty());
  const tiles = $("<div>").addClass("summary-tiles").appendTo(root);
  tiles.append(statTile(terms.observed, formatShare(summary.observed),
    formatShare(summary.revisited) + " " + terms.twice));
  if (summary.revisit) {
    const unit = durationUnit(summary.revisit.p90);
    tiles.append(statTile(terms.revisit, formatDuration(summary.revisit.mean, unit),
      distributionDetail(summary.revisit, unit)));
  } else {
    tiles.append(statTile(terms.revisit, "–", terms.neverTwice));
  }
  if (summary.access) {
    tiles.append(statTile(terms.access, formatDuration(summary.access.mean),
      terms.accessDetail));
  }
  const charts = $("<div>").addClass("summary-charts").appendTo(root);
  charts.append(coverageChart(summary.coverage, terms));
  if (summary.revisit_histogram) {
    charts.append(histogramChart(summary.revisit_histogram, terms.revisit,
      terms.revisitPoints, terms.revisitAxis));
  }
  if (summary.sufficiency) {
    renderSufficiencySummary(root, summary.sufficiency);
  }
  if (summary.sample_size) {
    renderSampleSizeSummary(root, summary.sample_size);
  }
  root.append($("<p>").addClass("small text-muted mb-0").text(weightingNote(summary)));
}

// Renders the summary of the swath coverage of a region in a container.
function renderRegionSummary(container, summary) {
  const root = $("<div>").addClass("summary").appendTo($(container).empty());
  const tiles = $("<div>").addClass("summary-tiles").appendTo(root);
  tiles.append(statTile("Area observed", formatShare(summary.covered),
    "of " + formatValue(summary.area) + " km²"));
  if (summary.revisit) {
    const unit = durationUnit(summary.revisit.p90);
    tiles.append(statTile("Mean revisit time", formatDuration(summary.revisit.mean, unit),
      distributionDetail(summary.revisit, unit)));
  } else {
    tiles.append(statTile("Mean revisit time", "–",
      summary.observations ? "observed once" : "the region is not observed"));
  }
  tiles.append(statTile("Observations", summary.observations.toLocaleString(),
    summary.access ? "mean duration " + formatDuration(summary.access.mean) : "of any part of the region"));
  tiles.append(statTile("Longest gap", formatDuration(summary.max_gap),
    "without an observation, including the ends of the period"));
  const charts = $("<div>").addClass("summary-charts").appendTo(root);
  charts.append(coverageChart(summary.coverage, COVERAGE_TERMS.region));
  const coincidence = summary.coincidence;
  if (coincidence) {
    root.append($("<div>").addClass("summary-section-title").text("Coincident swaths"));
    const common = $("<div>").addClass("summary-tiles").appendTo(root);
    common.append(statTile("Area in common", formatShare(coincidence.common),
      "observed by two satellites within the time difference"));
    common.append(statTile("Coincident footprints", coincidence.pairs.toLocaleString(),
      coincidence.time_difference
        ? "median " + formatDuration(coincidence.time_difference.median) + " apart"
        : "pairs of overlapping footprints"));
    $("<div>").addClass("summary-charts").appendTo(root).append(
      coverageChart(coincidence.coverage, COVERAGE_TERMS.regionCommon));
  }
  root.append($("<p>").addClass("small text-muted mb-0").text(
    "Areas are of the swaths' footprints sampled every step, measured on the WGS 84 ellipsoid."));
}


// Renders the summary of ground sample sizes (`sample_size` of a coverage
// summary) in a container.
function renderSampleSizeSummary(container, sizes) {
  container.append($("<div>").addClass("summary-section-title").text("Ground sample size"));
  container.append($("<div>").addClass("summary-section-note").text(
    "The size on the ground of each observation's sample: the larger of its pixel and pixel spacing, along and across track. " +
    "Only instruments with pixels (pointed, or conical with a beam width and sample spacing) have sizes."
  ));
  const tiles = $("<div>").addClass("summary-tiles").appendTo(container);
  if (sizes.median) {
    tiles.append(statTile("Median sample size", formatKilometers(sizes.median.median),
      "of points' median · 90th percentile " + formatKilometers(sizes.median.p90)));
  } else {
    tiles.append(statTile("Median sample size", "–", "no observation is sized"));
  }
  if (sizes.best) {
    tiles.append(statTile("Smallest sample size", formatKilometers(sizes.best.median),
      "median of points' smallest"));
  }
  tiles.append(statTile("Observations sized",
    formatShare(sizes.observations > 0 ? sizes.sized / sizes.observations : 0),
    sizes.sized.toLocaleString() + " of " + sizes.observations.toLocaleString()));
  if (sizes.max_sample_size) {
    tiles.append(statTile("At most " + formatKilometers(sizes.max_sample_size),
      formatShare(sizes.observations > 0 ? sizes.meeting / sizes.observations : 0),
      "of observations, which count toward coverage"));
  }
  if (sizes.median_histogram) {
    $("<div>").addClass("summary-charts").appendTo(container).append(
      histogramChart(sizes.median_histogram, "Median ground sample size",
        "Points with a sized observation", "Median sample size",
        { unit: { label: "km", seconds: 1000 } })
    );
  }
}

// Formats a relative error (a share of the field's standard deviation).
function formatRelativeError(value) {
  return formatValue(100 * value) + "% of σ";
}

// Renders the summary of sampling sufficiency (`sufficiency` of a coverage
// summary) in a container.
function renderSufficiencySummary(container, sufficiency) {
  container.append($("<div>").addClass("summary-section-title").text("Sampling sufficiency"));
  container.append($("<div>").addClass("summary-section-note").text(
    "Error of estimating each point's mean of a field over the period from its samples, for a field " +
    "with a decorrelation time of " + formatDuration(sufficiency.decorrelation_time) +
    (sufficiency.standard_deviation ? " and a standard deviation (σ) of " + formatValue(sufficiency.standard_deviation) : "") +
    ". The estimate assumes a steady field without a daily cycle."
  ));
  const tiles = $("<div>").addClass("summary-tiles").appendTo(container);
  if (sufficiency.sufficient !== null && sufficiency.sufficient !== undefined) {
    tiles.append(statTile("Region meeting target", formatShare(sufficiency.sufficient),
      "sampling error at most " + formatRelativeError(sufficiency.target_relative_error)));
  }
  const error = sufficiency.relative_error;
  if (error) {
    tiles.append(statTile("Median sampling error", formatRelativeError(error.median),
      "90th percentile " + formatRelativeError(error.p90) +
      (sufficiency.sampling_error ? " · median " + formatValue(sufficiency.sampling_error.median) + " in field units" : "")));
  } else {
    tiles.append(statTile("Median sampling error", "–", "no point is observed"));
  }
  if (sufficiency.effective_samples) {
    tiles.append(statTile("Effective samples", formatValue(sufficiency.effective_samples.median),
      "median independent samples per point"));
  }
  if (sufficiency.max_gap) {
    const unit = durationUnit(sufficiency.max_gap.p90);
    tiles.append(statTile("Longest gap", formatDuration(sufficiency.max_gap.median, unit),
      "median · 90th percentile " + formatDuration(sufficiency.max_gap.p90, unit)));
  }
  tiles.append(statTile("Local time-of-day coverage", formatShare(sufficiency.local_time_coverage),
    "mean share of " + sufficiency.local_time_shares.length + " intervals of the day sampled"));

  const charts = $("<div>").addClass("summary-charts").appendTo(container);
  if (sufficiency.relative_error_histogram) {
    charts.append(histogramChart(sufficiency.relative_error_histogram, "Sampling error",
      "Observed points, relative to the field's standard deviation", "Sampling error",
      { unit: { label: "% of σ", seconds: 0.01 } }));
  }
  if (sufficiency.max_gap_histogram) {
    charts.append(histogramChart(sufficiency.max_gap_histogram, "Longest gap without a sample",
      "Including from the start and to the end of the period", "Longest gap"));
  }
  const bins = sufficiency.local_time_shares.length;
  if (bins > 0 && _.sum(sufficiency.local_time_shares) > 0) {
    charts.append(histogramChart({
      edges: _.map(_.range(bins + 1), function(i) { return 24 * i / bins; }),
      shares: sufficiency.local_time_shares
    }, "Samples by local time of day", "Local (mean solar) time of all samples", "Local time",
    { unit: { label: "h", seconds: 1 }, of: "samples" }));
  }
}

// Renders the summary of latency results in a container.
function renderLatencySummary(container, summary) {
  const root = $("<div>").addClass("summary").appendTo($(container).empty());
  const tiles = $("<div>").addClass("summary-tiles").appendTo(root);
  tiles.append(statTile("Region downlinked", formatShare(summary.downlinked),
    "with an observation downlinked in the period"));
  if (summary.latency) {
    const unit = durationUnit(summary.latency.p90);
    tiles.append(statTile("Mean latency", formatDuration(summary.latency.mean, unit),
      distributionDetail(summary.latency, unit)));
  } else {
    tiles.append(statTile("Mean latency", "–", "no observation is downlinked"));
  }
  tiles.append(statTile("Contacts", summary.contacts.toLocaleString(),
    summary.contact_duration === null || summary.contact_duration === undefined
      ? "with ground stations"
      : "mean duration " + formatDuration(summary.contact_duration)));
  if (summary.latency_histogram) {
    $("<div>").addClass("summary-charts").appendTo(root).append(
      histogramChart(summary.latency_histogram, "Mean latency",
        "Points with a downlinked observation", "Mean latency")
    );
  }
  root.append($("<p>").addClass("small text-muted mb-0").text(weightingNote(summary)));
}
