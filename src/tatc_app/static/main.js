// Starts the application once every module (loaded before this script) has
// set up and listens to design changes: loads the stored design (or the
// default design), and validates its satellites once signed in.

$(document).ready(function() {
  loadInitialDesign();
  onSignedIn(validateUnknownItems);
});
