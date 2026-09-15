/*
 * Snackbar notifications.
 *
 * Errors persist until the operator dismisses them — on a data-entry form a
 * message that vanishes after three seconds is worse than no message, because
 * the operator may be looking at a different part of the screen when it fires.
 * Successes use a long timeout and can still be dismissed early.
 *
 *   COBRA.snack.error("Could not read the data file", "PRI.XML not found");
 *   COBRA.snack.success("Message 0042 saved");
 *   COBRA.snack.info("Nothing to extract yet");
 */
window.COBRA = window.COBRA || {};

(function () {
  var SUCCESS_TIMEOUT = 12000; // long enough not to be missed
  var INFO_TIMEOUT = 15000;

  var ICONS = {
    error:
      '<path d="M12 8v5M12 16.5v.5"/><circle cx="12" cy="12" r="9"/>',
    success:
      '<path d="M20 6L9 17l-5-5" stroke-linecap="round" stroke-linejoin="round"/>',
    info:
      '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/>',
  };

  var TITLES = { error: "Error", success: "Done", info: "Note" };

  function stack() {
    var el = document.querySelector(".snackbar-stack");
    if (!el) {
      el = document.createElement("div");
      el.className = "snackbar-stack";
      el.setAttribute("aria-live", "polite");
      document.body.appendChild(el);
    }
    return el;
  }

  function dismiss(node) {
    if (!node || node.dataset.leaving) return;
    node.dataset.leaving = "1";
    node.classList.add("is-leaving");
    // Remove after the animation; a fallback timer covers reduced-motion,
    // where the animationend event may not fire.
    var done = false;
    function remove() {
      if (done) return;
      done = true;
      if (node.parentNode) node.parentNode.removeChild(node);
    }
    node.addEventListener("animationend", remove);
    setTimeout(remove, 400);
  }

  function show(kind, message, detail, options) {
    options = options || {};
    var node = document.createElement("div");
    node.className = "snackbar snackbar-" + kind;
    node.setAttribute("role", kind === "error" ? "alert" : "status");

    var svg =
      '<svg class="snack-icon" viewBox="0 0 24 24" aria-hidden="true">' +
      ICONS[kind] +
      "</svg>";

    var body = document.createElement("div");
    body.className = "snack-body";

    var title = document.createElement("div");
    title.className = "snack-title";
    title.textContent = options.title || TITLES[kind];

    var text = document.createElement("div");
    text.className = "snack-text";
    text.textContent = message;

    body.appendChild(title);
    body.appendChild(text);

    if (detail) {
      var det = document.createElement("div");
      det.className = "snack-text has-detail";
      det.textContent = detail;
      body.appendChild(det);
    }

    var close = document.createElement("button");
    close.type = "button";
    close.className = "snack-close";
    close.setAttribute("aria-label", "Dismiss");
    close.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12" stroke-linecap="round"/></svg>';
    close.addEventListener("click", function () {
      dismiss(node);
    });

    node.innerHTML = svg;
    node.appendChild(body);
    node.appendChild(close);
    stack().appendChild(node);

    // Errors never auto-dismiss.
    var timeout = options.timeout;
    if (timeout === undefined) {
      timeout = kind === "error" ? 0 : kind === "success" ? SUCCESS_TIMEOUT : INFO_TIMEOUT;
    }
    if (timeout > 0) {
      var timer = setTimeout(function () {
        dismiss(node);
      }, timeout);
      // Hovering pauses the countdown so a message can be read in full.
      node.addEventListener("mouseenter", function () {
        clearTimeout(timer);
      });
    }
    return node;
  }

  window.COBRA.snack = {
    error: function (m, d, o) {
      return show("error", m, d, o);
    },
    success: function (m, d, o) {
      return show("success", m, d, o);
    },
    info: function (m, d, o) {
      return show("info", m, d, o);
    },
    dismissAll: function () {
      document.querySelectorAll(".snackbar").forEach(dismiss);
    },
  };

  // Server-side flashes are rendered into a JSON script tag by base.html and
  // replayed here, so flashes and client-side errors look identical.
  document.addEventListener("DOMContentLoaded", function () {
    var holder = document.getElementById("server-flashes");
    if (!holder) return;
    var items = [];
    try {
      items = JSON.parse(holder.textContent || "[]");
    } catch (e) {
      return;
    }
    items.forEach(function (it) {
      var kind = it.category === "error" ? "error"
        : it.category === "success" ? "success" : "info";
      show(kind, it.message);
    });
  });
})();
