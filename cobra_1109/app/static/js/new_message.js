/*
 * New Message page.
 *
 * Three interactions: extract from the folder path, refresh addressees when a
 * dropdown changes, and save. All errors surface through the snackbar so they
 * stay on screen until dismissed.
 */
(function () {
  var form = document.getElementById("msg-form");
  if (!form) return;

  var MSG_TYPE = form.dataset.msgType;
  var snack = window.COBRA.snack;

  function field(name) {
    return form.querySelector('[data-field="' + name + '"]');
  }

  function setValue(name, value) {
    var el = field(name);
    if (!el || value === undefined || value === null) return;
    if (el.type === "checkbox") {
      el.checked = value === "Yes" || value === true;
    } else {
      el.value = value;
      if (String(value).trim() !== "") el.classList.add("is-filled");
    }
  }

  function getValues() {
    var out = {};
    form.querySelectorAll("[data-field]").forEach(function (el) {
      if (el.type === "checkbox") return;
      out[el.dataset.field] = el.value;
    });
    return out;
  }

  function busy(button, on, label) {
    button.disabled = on;
    if (on) {
      button.dataset.label = button.textContent;
      button.textContent = label;
    } else if (button.dataset.label) {
      button.textContent = button.dataset.label;
    }
  }

  function postJSON(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (r) {
      return r.json().then(function (body) {
        return { status: r.status, body: body };
      });
    });
  }

  // --- format hint -------------------------------------------------------
  var systemEl = field("System");
  var hint = document.getElementById("format-hint");
  if (systemEl && hint) {
    systemEl.addEventListener("change", function () {
      var v = (systemEl.value || "").toUpperCase();
      if (!v) {
        hint.textContent =
          "Systems containing \u201cVS\u201d read PRI.XML; others read the Event ID JSON.";
      } else if (v.indexOf("VS") !== -1) {
        hint.textContent = "This system uses PRI.XML.";
      } else {
        hint.textContent = "This system uses the Event ID JSON file.";
      }
    });
  }

  // --- extract -----------------------------------------------------------
  var extractBtn = document.getElementById("btn-extract");
  var pathEl = document.getElementById("folder-path");
  var statusEl = document.getElementById("extract-status");
  var sourceFolder = "";

  function doExtract() {
    if (!systemEl.value) {
      snack.error("Select a recorder system first.");
      systemEl.focus();
      return;
    }
    if (!pathEl.value.trim()) {
      snack.error("Paste the intercept folder path.");
      pathEl.focus();
      return;
    }

    busy(extractBtn, true, "Reading\u2026");
    statusEl.textContent = "";

    postJSON("/message/api/extract", {
      msg_type: MSG_TYPE,
      folder_path: pathEl.value,
      system: systemEl.value,
    })
      .then(function (res) {
        if (!res.body.ok) {
          snack.error(res.body.error || "Extraction failed.", res.body.detail);
          statusEl.textContent = "";
          return;
        }
        var b = res.body;
        sourceFolder = b.info.source_folder;

        Object.keys(b.extracted).forEach(function (k) {
          setValue(k, b.extracted[k]);
        });
        Object.keys(b.auto).forEach(function (k) {
          setValue(k, b.auto[k]);
        });

        statusEl.textContent =
          "Read " + b.info.file_kind.toUpperCase() + " \u2014 " + b.info.data_file;

        if (!b.info.logger_found) {
          snack.info(
            "Logger ID \u201c" + (b.auto.Lgd_By || "") +
              "\u201d is not in name_details, so the full name is blank."
          );
        }
        if (b.info.unmapped_count > 0) {
          snack.info(
            b.info.unmapped_count +
              " field(s) have no mapping yet and were left blank.",
            "app/messages/parser.py"
          );
        }
        refreshAddressees();
      })
      .catch(function (e) {
        snack.error("Could not reach the server.", String(e));
      })
      .finally(function () {
        busy(extractBtn, false);
      });
  }

  extractBtn.addEventListener("click", doExtract);
  pathEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      doExtract();
    }
  });

  // --- addressee cascade -------------------------------------------------
  function refreshAddressees() {
    var payload = {
      Category: (field("Category") || {}).value || "",
      Language: (field("Language") || {}).value || "",
      Clg_Country: (field("Clg_Country") || {}).value || "",
      Add_To: (field("Add_To") || {}).value || "",
      Add_Info: (field("Add_Info") || {}).value || "",
      Extra_Add: (field("Extra_Add") || {}).value || "",
    };
    postJSON("/message/api/addressees", payload)
      .then(function (res) {
        setValue("Add_To", res.body.Add_To);
        setValue("Add_Info", res.body.Add_Info);
        setValue("Extra_Add", res.body.Extra_Add);
      })
      .catch(function () {
        snack.error("Could not update the addressee fields.");
      });
  }

  ["Category", "Language", "Clg_Country"].forEach(function (name) {
    var el = field(name);
    if (el) el.addEventListener("change", refreshAddressees);
  });

  // --- save --------------------------------------------------------------
  var saveBtn = document.getElementById("btn-save");
  var saveNote = document.getElementById("save-note");

  saveBtn.addEventListener("click", function () {
    var values = getValues();
    if (!(values.Event_Id || "").trim()) {
      snack.error("Extract the intercept folder before saving.");
      return;
    }

    busy(saveBtn, true, "Saving\u2026");
    saveNote.textContent = "";

    postJSON("/message/new/" + MSG_TYPE, {
      values: values,
      manual_msgno: (document.getElementById("manual-msgno") || {}).value || "",
      source_folder: sourceFolder,
      Extra_Add: (field("Extra_Add") || {}).value || "",
      Imp_Msg: (field("Imp_Msg") || {}).checked || false,
    })
      .then(function (res) {
        if (!res.body.ok) {
          snack.error(res.body.error || "Save failed.", res.body.detail);
          return;
        }
        snack.success("Message " + res.body.msgno + " saved.");
        saveNote.textContent = "Saved to " + res.body.destination;

        (res.body.warnings || []).forEach(function (w) {
          // Warnings are errors in tone: the row exists but something still
          // needs doing, and that must not scroll away unnoticed.
          snack.error(w, null, { title: "Needs attention" });
        });

        saveBtn.disabled = true;
        saveBtn.textContent = "Saved";
        refreshNextNumber();
      })
      .catch(function (e) {
        snack.error("Could not reach the server.", String(e));
      })
      .finally(function () {
        if (!saveBtn.disabled) busy(saveBtn, false);
      });
  });

  function refreshNextNumber() {
    fetch("/message/api/next-msgno")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var el = document.getElementById("next-msgno");
        if (el) el.textContent = d.next;
      })
      .catch(function () {});
  }
})();
