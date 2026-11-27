// The entry module of the app (index.html loads it after the libraries):
// importing it loads every module. Once the page has loaded, it sets up the
// modules in order, then loads the stored design (or the default design) and
// validates its satellites once signed in.

import { setupAnalysis } from "./analysis.js";
import { setupCatalog } from "./catalog.js";
import { addSatellites, design, loadInitialDesign, setupDesignState, validateUnknownItems } from "./design-state.js";
import { setupDisplay } from "./display.js";
import { setupFilter } from "./filter.js";
import { onSignedIn, setupIndex } from "./index.js";
import { setupLibrary } from "./library.js";
import { setupPreview } from "./preview.js";
import { cancelRegionGrid, generateRegionGrid, gridPoints, regionOutline, setupRegion } from "./region.js";
import { setupSatelliteDialog } from "./satellite-dialog.js";
import { addTarget, renderStations, setupSites } from "./sites.js";
import { comparisonChart, coverageChart, histogramChart } from "./summary.js";
import { COVERAGE_TERMS } from "./terms.js";

$(function() {
  setupIndex();
  setupDisplay();
  setupDesignState();
  setupSatelliteDialog();
  setupFilter();
  setupCatalog();
  setupPreview();
  setupRegion();
  setupSites();
  setupAnalysis();
  setupLibrary();
  loadInitialDesign();
  onSignedIn(validateUnknownItems);
});

// The parts of the app that browser tests (tests/browser) use, which are
// also handy in the browser's console.
window.tatc = {
  design: design,
  addSatellites: addSatellites,
  renderStations: renderStations,
  addTarget: addTarget,
  generateRegionGrid: generateRegionGrid,
  cancelRegionGrid: cancelRegionGrid,
  gridPoints: gridPoints,
  regionOutline: regionOutline,
  coverageChart: coverageChart,
  histogramChart: histogramChart,
  comparisonChart: comparisonChart,
  COVERAGE_TERMS: COVERAGE_TERMS
};
