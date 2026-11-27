// Animated layer of target points and cells colored by a metric, either
// static (final statistics) or time-dynamic (computed from a timeline of
// events, such as observations, as the clock advances).
//
// Uses primitives (rather than entities) so that thousands of targets update
// efficiently: point colors are set directly and cell colors through
// per-instance attributes of one ground primitive.

import { addCellPrimitives } from "./region.js";
import { viewer } from "./viewer.js";

const MISSING_COLOR = Cesium.Color.GRAY.withAlpha(0.5);

// Index of the first element of a sorted array greater than a value.
function upperBound(array, value) {
  let low = 0;
  let high = array.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (array[mid] <= value) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  return low;
}

export class TargetLayer {
  // options:
  //   points:      GeoJSON feature collection of targets (timeline order)
  //   cells:       GeoJSON feature collection of cells
  //   timeline:    {epoch, target, start, end} events of targets
  //   cellTargets: {cell_id: [target indices]}
  //   arcType:     Cesium.ArcType of cell edges
  constructor(options) {
    this.points = options.points.features;
    this.cells = options.cells ? options.cells.features : [];
    this.cellTargets = options.cellTargets || {};
    this.epoch = Cesium.JulianDate.fromIso8601(options.timeline.epoch);
    this.mode = null;
    this.lastTime = null;
    this.indexEvents(options.timeline);

    this.pointCollection = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
    this.pointPrimitives = _.map(this.points, (feature) => this.pointCollection.add({
      position: Cesium.Cartesian3.fromDegrees(feature.geometry.coordinates[0], feature.geometry.coordinates[1]),
      color: MISSING_COLOR,
      pixelSize: 6,
      outlineColor: Cesium.Color.BLACK.withAlpha(0.6),
      outlineWidth: 1
    }));
    this.cellCollection = viewer.scene.primitives.add(new Cesium.PrimitiveCollection());
    this.cellIds = _.map(this.cells, function(feature, i) { return feature.properties.cell_id || i; });
    this.cellPrimitive = addCellPrimitives(this.cells, this.cellCollection, null, options.arcType, function() {
      return MISSING_COLOR;
    });

    this.tickListener = viewer.clock.onTick.addEventListener((clock) => this.update(clock.currentTime));
  }

  // Indexes the start and end times of events by target (seconds since epoch).
  indexEvents(timeline) {
    const n = this.points.length;
    const starts = _.times(n, function() { return []; });
    const ends = _.times(n, function() { return []; });
    for (let k = 0; k < timeline.target.length; k++) {
      const t = timeline.target[k];
      starts[t].push(timeline.start[k]);
      ends[t].push(timeline.end[k] === null ? Infinity : timeline.end[k]);
    }
    this.starts = _.map(starts, function(values) { return Float64Array.from(values); });
    // ends of overlapping events may be out of order
    this.sortedEnds = _.map(ends, function(values) { return Float64Array.from(values).sort(); });
  }

  // Number of events started by time t.
  countStarted(i, t) {
    return upperBound(this.starts[i], t);
  }

  // Time (seconds) since the last event ended (0 during an event), or NaN
  // if no event has started.
  timeSince(i, t) {
    if (this.countStarted(i, t) == 0) {
      return NaN;
    }
    if (this.countPending(i, t) > 0) {
      return 0;
    }
    // all events started by t have ended: the latest ended last
    const ends = this.sortedEnds[i];
    return t - ends[upperBound(ends, t) - 1];
  }

  // Number of events started but not ended by time t.
  countPending(i, t) {
    return upperBound(this.starts[i], t) - upperBound(this.sortedEnds[i], t);
  }

  // Maximum number of events pending at once, over all targets.
  maxPending() {
    let max = 0;
    for (let i = 0; i < this.points.length; i++) {
      const starts = this.starts[i];
      const ends = this.sortedEnds[i];
      let a = 0, b = 0, count = 0;
      while (a < starts.length) {
        if (b < ends.length && ends[b] <= starts[a]) {
          b++;
          count--;
        } else {
          a++;
          count++;
          max = Math.max(max, count);
        }
      }
    }
    return max;
  }

  // Sets the display mode: {pointValue(i, t, feature), cellValue(c, feature)?,
  // scale, animated}, with the value of point i at time t (seconds since the
  // epoch) and, optionally, of cell c (by default, the mean value of the
  // points within the cell); an animated mode updates as the clock advances.
  setMode(mode) {
    this.mode = mode;
    this.lastTime = null;
    this.update(viewer.clock.currentTime, true);
  }

  update(time, force) {
    if (!this.mode) {
      return;
    }
    const t = Cesium.JulianDate.secondsDifference(time, this.epoch);
    if (!force && !this.cellsPending) {
      if (!this.mode.animated) {
        return;
      }
      const threshold = Math.max(1, Math.abs(viewer.clock.multiplier) / 4);
      if (this.lastTime !== null && Math.abs(t - this.lastTime) < threshold) {
        return;
      }
    }
    this.lastTime = t;
    const scale = this.mode.scale;
    const values = new Float64Array(this.points.length);
    for (let i = 0; i < this.points.length; i++) {
      values[i] = this.mode.pointValue(i, t, this.points[i]);
      this.pointPrimitives[i].color = scale.color(values[i]) || MISSING_COLOR;
    }
    this.cellsPending = false;
    if (this.cellPrimitive && this.cellPrimitive.ready) {
      for (let c = 0; c < this.cells.length; c++) {
        let value;
        if (this.mode.cellValue) {
          value = this.mode.cellValue(c, this.cells[c]);
        } else {
          const targets = this.cellTargets[this.cellIds[c]] || [];
          const finite = _.filter(_.map(targets, function(i) { return values[i]; }), function(v) { return !isNaN(v); });
          value = finite.length ? _.mean(finite) : NaN;
        }
        const color = (scale.color(value) || MISSING_COLOR).withAlpha(0.55);
        const attributes = this.cellPrimitive.getGeometryInstanceAttributes(this.cellIds[c]);
        if (attributes) {
          attributes.color = Cesium.ColorGeometryInstanceAttribute.toValue(color, attributes.color);
        }
      }
    } else if (this.cellPrimitive) {
      // update cells once the (asynchronously created) primitive is ready
      this.cellsPending = true;
    }
  }

  show(show) {
    this.pointCollection.show = show;
    this.cellCollection.show = show;
  }

  destroy() {
    this.tickListener();
    viewer.scene.primitives.remove(this.pointCollection);
    viewer.scene.primitives.remove(this.cellCollection);
  }
}
