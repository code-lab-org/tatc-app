// Satellite and instrument filter of the display panel, shared by all tabs:
// unchecked satellites, constellation members, and instruments are hidden in
// the orbit preview and left out of analyses. The filter lists the design's
// satellites and constellations (with members once validated) in their
// colors, so it also serves as their legend, and does not depend on a
// preview.

// filtered (unchecked) items by key (see `filterKey`), kept across changes
// to the design
const filterUnchecked = {};
// names of constellations with an expanded member list
const filterExpanded = {};
// keys of instruments without a footprint (found by the orbit preview)
let filterNoFootprint = {};
const filterListeners = [];
let filterToggleCount = 0;

function filterKey(kind, system, detail) {
  return kind + ":" + system + (detail === undefined ? "" : "/" + detail);
}

function isFilterChecked(key) {
  return !filterUnchecked[key];
}

function onLayerFilterChange(listener) {
  filterListeners.push(listener);
}

function notifyLayerFilterChange() {
  _.forEach(filterListeners, function(listener) { listener(); });
}

// Marks the instruments (by key) without a footprint.
function setFilterWithoutFootprint(keys) {
  filterNoFootprint = _.zipObject(keys, _.map(keys, _.constant(true)));
  renderLayerFilter();
}

// Lists the satellites and constellations of the design: [{name, color,
// instruments: [{name, color}], members: [name] or null if not validated}].
function getFilterSystems() {
  return _.map(design.satellites, function(item) {
    const instruments = item.system.instruments || [];
    return {
      name: item.system.name,
      color: item.color,
      instruments: _.map(instruments, function(instrument, i) {
        return {
          name: instrument.name,
          color: instrumentColor(item, i)
        };
      }),
      members: item.validation.status == "valid" ? _.map(item.validation.members, "name") : null
    };
  });
}

function createFilterToggle(key, label, swatch, title, onChange) {
  const id = "layer-toggle-" + (filterToggleCount++);
  return $("<div>").addClass("form-check form-check-inline mr-2").attr("title", title || null).append(
    $("<input type='checkbox'>").addClass("form-check-input").attr("id", id)
      .prop("checked", isFilterChecked(key))
      .on("change", function() {
        if (this.checked) {
          delete filterUnchecked[key];
        } else {
          filterUnchecked[key] = true;
        }
        if (onChange) { onChange(this.checked); }
        notifyLayerFilterChange();
      }),
    $("<label>").addClass("form-check-label").attr("for", id).append(swatch, $("<span>").text(label))
  );
}

function renderLayerFilter() {
  const list = $("#layer-filter-list").empty();
  const systems = getFilterSystems();
  $("#layer-filter").toggle(systems.length > 0);
  _.forEach(systems, function(system) {
    const details = $("<div>").addClass("filter-details")
      .toggleClass("filter-unchecked", !isFilterChecked(filterKey("sys", system.name)));
    const header = $("<div>").append(
      createFilterToggle(
        filterKey("sys", system.name),
        system.name,
        $("<i>").addClass("fas fa-satellite mr-1").css("color", system.color),
        null,
        function(shown) { details.toggleClass("filter-unchecked", !shown); }
      )
    );
    _.forEach(system.instruments, function(instrument, i) {
      const key = filterKey("ins", system.name, i);
      const swatch = $("<span>").addClass("filter-swatch");
      if (filterNoFootprint[key]) {
        swatch.addClass("filter-swatch-none");
      } else {
        swatch.css("background-color", instrument.color);
      }
      details.append(createFilterToggle(
        key,
        instrument.name || "Instrument " + i,
        swatch,
        "Instrument " + i + (filterNoFootprint[key] ? " (no footprint)" : "")
      ));
    });
    if (system.members && system.members.length > 1) {
      const members = $("<div>").addClass("filter-members").toggle(!!filterExpanded[system.name]);
      _.forEach(system.members, function(member) {
        members.append(createFilterToggle(filterKey("sat", system.name, member), member));
      });
      const toggle = $("<a href='#'>").addClass("small ml-1")
        .text(system.members.length + " satellites")
        .prepend($("<i>").addClass("fas mr-1").toggleClass("fa-caret-down", !!filterExpanded[system.name])
          .toggleClass("fa-caret-right", !filterExpanded[system.name]))
        .on("click", function(e) {
          e.preventDefault();
          filterExpanded[system.name] = !filterExpanded[system.name];
          members.toggle(filterExpanded[system.name]);
          $(this).find("i").toggleClass("fa-caret-down fa-caret-right");
        });
      header.append(toggle);
      details.append(members);
    }
    list.append($("<div>").addClass("filter-system").append(header, details));
  });
}

// Gets the inputs of an analysis, less unchecked items: {satellites, colors,
// instrumentColors, excludeMembers}. A satellite or constellation is left
// out if unchecked, or if all of its instruments or members are unchecked.
// Instruments keep their colors (default colors derive from their index
// among all instruments).
function getFilteredInputs() {
  const inputs = { satellites: [], colors: [], instrumentColors: [], excludeMembers: [] };
  _.forEach(design.satellites, function(item) {
    const system = item.system;
    if (!isFilterChecked(filterKey("sys", system.name))) {
      return;
    }
    const instruments = system.instruments || [];
    const kept = _.filter(_.range(instruments.length), function(i) {
      return isFilterChecked(filterKey("ins", system.name, i));
    });
    if (instruments.length > 0 && kept.length == 0) {
      return;
    }
    const members = item.validation.status == "valid" ? _.map(item.validation.members, "name") : [];
    const excluded = members.length > 1 ? _.filter(members, function(member) {
      return !isFilterChecked(filterKey("sat", system.name, member));
    }) : [];
    if (excluded.length > 0 && excluded.length == members.length) {
      return;
    }
    let colors = requestInstrumentColors(item);
    if (kept.length < instruments.length) {
      colors = _.map(kept, function(i) { return instrumentColor(item, i); });
      inputs.satellites.push(_.assign({}, system, { instruments: _.at(instruments, kept) }));
    } else {
      inputs.satellites.push(system);
    }
    inputs.colors.push(item.color);
    inputs.instrumentColors.push(colors);
    inputs.excludeMembers = inputs.excludeMembers.concat(excluded);
  });
  return inputs;
}

$(document).ready(function() {
  $("#layer-filter-all").click(function() {
    _.forEach(_.keys(filterUnchecked), function(key) { delete filterUnchecked[key]; });
    renderLayerFilter();
    notifyLayerFilterChange();
  });
  onDesignChange(renderLayerFilter);
  // the filter lists the members of validated constellations
  onValidationChange(renderLayerFilter);
  renderLayerFilter();
});
