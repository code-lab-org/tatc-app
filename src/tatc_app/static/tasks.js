// Submits analysis tasks to the server and polls them until complete.

import { formatError, postJson } from "./index.js";

// Polls start every POLL_INTERVAL (ms), growing by POLL_BACKOFF after each
// poll to at most POLL_MAX_INTERVAL, so long analyses are polled less often.
const POLL_INTERVAL = 1000;
const POLL_MAX_INTERVAL = 4000;
const POLL_BACKOFF = 1.2;
// polls that fail in a row (network or server errors) before giving up
const POLL_RETRIES = 5;

// Whether a failed request may succeed if sent again: network errors (no
// status) and server errors, not refused requests.
function isTransientError(xhr) {
  return !xhr.status || xhr.status >= 500;
}

// Runs of each named analysis; starting a run cancels the previous run of the
// same name, so late results of a superseded run are dropped.
const activeRuns = {};

// Submits an analysis and polls its status (and progress) until complete.
//
// options:
//   name:       name of the analysis (one active run per name)
//   url:        endpoint to enqueue the analysis (POST), and of its results
//               (GET `url`/{task_id})
//   payload:    request body (serialized to JSON)
//   button:     jQuery button to disable (with a spinner) while running
//   progress:   jQuery progress element to show group progress
//   error:      jQuery element to show errors
//   onResult:   function(result, taskId) called with the results
export function runAnalysis(options) {
  if (activeRuns[options.name]) {
    activeRuns[options.name].cancel();
  }
  const run = {
    cancelled: false,
    task: null, // the enqueued task: {task_id, group_id}
    cancel: function() {
      if (this.cancelled) {
        return;
      }
      this.cancelled = true;
      revoke();
      finish();
    }
  };
  activeRuns[options.name] = run;

  // Revokes the enqueued task (if enqueued yet) so workers skip its pending
  // sub-tasks. Done tasks are unaffected, so this is safe to call any time.
  function revoke() {
    if (!run.task) {
      return;
    }
    $.ajax({
      url: "/tasks/" + run.task.task_id + "/revoke"
        + (run.task.group_id ? "?group_id=" + run.task.group_id : ""),
      type: "POST"
    });
  }

  function setBusy(busy) {
    if (options.button) {
      options.button.prop("disabled", busy);
      options.button.find(".spinner-border").toggle(busy);
    }
    if (options.progress) {
      options.progress.toggle(busy);
      options.progress.find(".progress-bar").css("width", "0%");
    }
  }
  function finish() {
    if (activeRuns[options.name] === run) {
      delete activeRuns[options.name];
    }
    setBusy(false);
  }
  function fail(message) {
    if (run.cancelled) {
      return;
    }
    finish();
    if (options.error) {
      options.error.text(message).show();
    }
  }

  if (options.error) {
    options.error.hide().text("");
  }
  setBusy(true);

  // Polls the task's status until its results are ready, and the progress of
  // its group of parallel tasks (if any) until they complete. The status is
  // polled even while the group runs: a group whose task failed never
  // completes, but the task is then ready (and failed).
  let interval = POLL_INTERVAL;
  let failures = 0;
  let showsProgress = Boolean(options.progress);
  function schedulePoll() {
    setTimeout(poll, interval);
    interval = Math.min(POLL_MAX_INTERVAL, interval * POLL_BACKOFF);
  }
  function poll() {
    if (run.cancelled) {
      return;
    }
    if (showsProgress && run.task.group_id) {
      // a failed poll of progress only leaves the progress bar as it is
      $.get("/tasks/" + run.task.group_id + "/progress").done(showProgress);
    }
    $.get("/tasks/" + run.task.task_id + "/status")
      .done(function(status) {
        if (run.cancelled) {
          return;
        }
        failures = 0;
        if (status.ready) {
          getResult();
        } else {
          schedulePoll();
        }
      })
      .fail(function(xhr) {
        failures += 1;
        if (isTransientError(xhr) && failures <= POLL_RETRIES) {
          schedulePoll();
        } else {
          fail(formatError(xhr));
        }
      });
  }
  function showProgress(progress) {
    if (run.cancelled || !showsProgress) {
      return;
    }
    const percent = progress.task_count
      ? Math.round((100 * progress.completed_count) / progress.task_count)
      : 0;
    options.progress.find(".progress-bar").css("width", percent + "%");
    // the group completed: only the status remains to poll
    showsProgress = progress.completed_count < progress.task_count;
  }
  function getResult() {
    $.get(options.url + "/" + run.task.task_id)
      .done(function(result) {
        if (run.cancelled) {
          return;
        }
        finish();
        options.onResult(result, run.task.task_id);
      })
      .fail(function(xhr) { fail(formatError(xhr)); });
  }

  postJson(options.url, options.payload)
    .done(function(task) {
      run.task = task;
      if (run.cancelled) {
        // cancelled while enqueuing
        revoke();
        return;
      }
      poll();
    })
    .fail(function(xhr) { fail(formatError(xhr)); });
}

// Cancels the active run of a named analysis, if any: its results are dropped
// and its server task is revoked.
export function cancelAnalysis(name) {
  if (activeRuns[name]) {
    activeRuns[name].cancel();
  }
}
