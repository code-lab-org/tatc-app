// The Cesium viewer (created when this module loads, so it imports no other
// module of the app), and its upgrade to Cesium ion imagery and terrain.

// Offline base layer bundled with Cesium (no access token required).
function createOfflineBaseLayer() {
  return new Cesium.ImageryLayer(
    new Cesium.UrlTemplateImageryProvider({
      url: Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII/") + "{z}/{x}/{reverseY}.jpg",
      tilingScheme: new Cesium.GeographicTilingScheme(),
      maximumLevel: 2,
      credit: "Natural Earth II"
    })
  );
}

// The viewer is created once; imagery and terrain are upgraded to Cesium ion
// assets once an access token is available (see `initializeCesium`).
export const viewer = new Cesium.Viewer("cesiumContainer", {
  baseLayer: createOfflineBaseLayer(),
  baseLayerPicker: false,
  homeButton: false,
  infoBox: true,
  geocoder: false,
  selectionIndicator: true,
  navigationHelpButton: false,
  navigationInstructionsInitiallyVisible: false,
  sceneModePicker: true,
  timeline: true,
  animation: true
});
viewer.scene.globe.depthTestAgainstTerrain = false;

// Shows a status over the map while Cesium prepares the graphics of data
// sources: large footprints, for example, take seconds to tessellate (in web
// workers). Meanwhile, the viewer pauses the animation (its default
// `allowDataSourcesToSuspendAnimation`), which `canAnimate` reflects. The
// status shows after a delay, so it does not flash for brief preparations.
const MAP_BUSY_DELAY = 300; // milliseconds
let mapBusySince = null;
let mapBusyShown = false;
viewer.scene.postRender.addEventListener(function() {
  const now = performance.now();
  mapBusySince = viewer.clockViewModel.canAnimate ? null : (mapBusySince === null ? now : mapBusySince);
  const shown = mapBusySince !== null && now - mapBusySince >= MAP_BUSY_DELAY;
  if (shown !== mapBusyShown) {
    mapBusyShown = shown;
    $("#map-busy").prop("hidden", !shown);
  }
});

let cesiumIonInitialized = false;
export function initializeCesium() {
  if (cesiumIonInitialized) {
    return;
  }
  $.get("/cesium/token").done(function(token) {
    if (!token) {
      return;
    }
    cesiumIonInitialized = true;
    Cesium.Ion.defaultAccessToken = token;
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.add(
      Cesium.ImageryLayer.fromProviderAsync(Cesium.IonImageryProvider.fromAssetId(3845))
    );
    viewer.scene.setTerrain(Cesium.Terrain.fromWorldTerrain());
  });
}
