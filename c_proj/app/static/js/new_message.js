/*
 * New Message page.
 *
 * Extract is cumulative: each folder adds a capture to the message, so values
 * accumulate with commas and the loggers join with "/". The page keeps the
 * merged state and sends it back on the next extract so the server does the
 * merging in one place.
 *
 * Save runs required-field validation BEFORE the message-number dialog —
 * there is no point asking the operator to confirm a number for a message
 * that cannot be saved.
 */
(function () {
  var form = document.getElementById("msg-form");
  if (!form) return;

  var MSG_TYPE = form.dataset.msgType;
  var snack = window.COBRA.snack;

  var pathEl = document.getElementById("folder-path");
  var statusEl = document.getElementById("extract-status");
  var saveBtn = document.getElementById("btn-save");
  var saveNote = document.getElementById("save-note");
  var extractBtn = document.getElementById("btn-extract");
  var systemEl = null;

  var sourceFolder = "";
  var sourceFolders = [];
  var loggerFinal = "";
  var extractedState = {};

  // Label -> field name, so a validation failure can focus the right input.
  var LABEL_TO_FIELD = {
    "System": "System",
    "Classification": "Classification",
    "Prepared By": "Prep_By",
    "Subject": "Msg_Subject",
    "Transcribed By": "Txbd_By",
    "BEPS ID": "BEPS_ID"
  };

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
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().then(function (body) {
        return { status: r.status, body: body };
      });
    });
  }

  // Values the form starts with, so Reset restores defaults rather than
  // blanking fields that are meant to have one.
  var INITIAL = {};
  form.querySelectorAll("[data-field]").forEach(function (el) {
    INITIAL[el.dataset.field] = el.type === "checkbox" ? el.checked : el.value;
  });

  function prefillPreparedBy() {
    var el = field("Prep_By");
    if (el && form.dataset.currentUser) el.value = form.dataset.currentUser;
  }

  function resetForm() {
    form.querySelectorAll("[data-field]").forEach(function (el) {
      var init = INITIAL[el.dataset.field];
      if (el.type === "checkbox") {
        el.checked = !!init;
      } else {
        el.value = init === undefined ? "" : init;
        el.classList.remove("is-filled");
      }
    });
    pathEl.value = "";
    document.getElementById("manual-msgno").value = "";
    statusEl.textContent = "";
    saveNote.textContent = "";
    sourceFolder = "";
    sourceFolders = [];
    extractedState = {};
    loggerFinal = "";
    saveBtn.disabled = false;
    saveBtn.textContent = "Create message";
    prefillPreparedBy();
    snack.dismissAll();
    refreshNextNumber();
  }

  // --- format hint -------------------------------------------------------
  systemEl = field("System");
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

    postJSON("/message/api/extract", {
      msg_type: MSG_TYPE,
      folder_path: pathEl.value,
      system: systemEl.value,
      // Sent so the server merges this capture into what the form already
      // holds — several folders can make up one message.
      current: extractedState
    })
      .then(function (res) {
        if (!res.body.ok) {
          snack.error(res.body.error || "Extraction failed.", res.body.detail);
          return;
        }
        var b = res.body;
        sourceFolder = b.info.source_folder;
        if (sourceFolders.indexOf(sourceFolder) === -1) {
          sourceFolders.push(sourceFolder);
        }
        extractedState = b.extracted;
        loggerFinal = b.logger_final || "";

        Object.keys(b.extracted).forEach(function (k) {
          setValue(k, b.extracted[k]);
        });
        Object.keys(b.auto).forEach(function (k) {
          // Auto values never overwrite something already filled in.
          var el = field(k);
          if (el && el.type !== "checkbox" && String(el.value || "").trim()) return;
          setValue(k, b.auto[k]);
        });

        statusEl.textContent =
          b.info.event_count + " capture(s) loaded \u2014 last read " +
          b.info.file_kind.toUpperCase() + " \u2014 link " + b.info.link;

        if (!b.info.logger_found) {
          snack.info(
            "Logger \u201c" + (b.info.logger_id || "") +
              "\u201d is not in name_details, so the full name is blank."
          );
        }

        // Cleared so the next folder can be pasted straight in.
        pathEl.value = "";
        pathEl.focus();
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

  var resetBtn = document.getElementById("btn-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      resetForm();
      snack.info("Form cleared.");
    });
  }

  // --- addressee cascade -------------------------------------------------
  function refreshAddressees() {
    postJSON("/message/api/addressees", {
      Category: (field("Category") || {}).value || "",
      Language: (field("Language") || {}).value || "",
      Clg_Country: (field("Clg_Country") || {}).value || "",
      Add_To: (field("Add_To") || {}).value || "",
      Add_Info: (field("Add_Info") || {}).value || "",
      Extra_Add: (field("Extra_Add") || {}).value || ""
    })
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

  // --- confirmation dialog ----------------------------------------------
  var modal = document.getElementById("confirm-modal");
  var confirmNumber = document.getElementById("confirm-number");
  var confirmNote = document.getElementById("confirm-note");
  var pendingSave = null;

  function closeModal() {
    modal.hidden = true;
    pendingSave = null;
  }

  function askConfirmation(number, isManual, onYes) {
    confirmNumber.textContent = number;
    confirmNote.textContent = isManual
      ? "This is the number you entered. It is checked for clashes when you continue."
      : "The number is reserved when you continue, so it may differ if someone else saves first.";
    pendingSave = onYes;
    modal.hidden = false;
    document.getElementById("confirm-ok").focus();
  }

  document.getElementById("confirm-cancel").addEventListener("click", closeModal);
  modal.addEventListener("click", function (e) {
    if (e.target === modal) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });
  document.getElementById("confirm-ok").addEventListener("click", function () {
    var go = pendingSave;
    closeModal();
    if (go) go();
  });

  // --- save --------------------------------------------------------------
  function bepsChecked() {
    var el = document.getElementById("beps-confirm");
    return el ? el.checked : true;
  }

  function doSave() {
    busy(saveBtn, true, "Saving\u2026");
    saveNote.textContent = "";

    postJSON("/message/new/" + MSG_TYPE, {
      values: getValues(),
      manual_msgno: (document.getElementById("manual-msgno") || {}).value || "",
      source_folder: sourceFolder,
      source_folders: sourceFolders,
      logger_final: loggerFinal,
      Extra_Add: (field("Extra_Add") || {}).value || "",
      Osint: (field("Osint") || {}).value || "",
      Imp_Msg: (field("Imp_Msg") || {}).checked || false,
      beps_checked: bepsChecked()
    })
      .then(function (res) {
        if (!res.body.ok) {
          snack.error(res.body.error || "Save failed.", res.body.detail);
          return;
        }
        saveNote.textContent = "Saved to " + res.body.destination;
        saveBtn.disabled = true;
        saveBtn.textContent = "Saved";

        var warnings = res.body.warnings || [];
        if (warnings.length) {
          // Something did not finish — the row exists but the copy or the
          // document failed. That is not a success, so no success dialog;
          // the warnings stay on screen until dismissed.
          snack.success("Message " + res.body.msgno + " saved.");
          warnings.forEach(function (w) {
            snack.error(w, null, { title: "Needs attention" });
          });
          refreshNextNumber();
          return;
        }
        showSuccess(res.body.msgno, res.body.destination);
      })
      .catch(function (e) {
        snack.error("Could not reach the server.", String(e));
      })
      .finally(function () {
        if (!saveBtn.disabled) busy(saveBtn, false);
      });
  }

  saveBtn.addEventListener("click", function () {
    var values = getValues();
    if (!(values.Event_Id || "").trim()) {
      snack.error("Extract the intercept folder before saving.");
      return;
    }

    postJSON("/message/api/validate", {
      msg_type: MSG_TYPE,
      values: values,
      beps_checked: bepsChecked()
    })
      .then(function (res) {
        if (!res.body.ok) {
          var missing = res.body.missing || [];
          snack.error(
            "These are required before saving: " + missing.join(", "),
            null,
            { title: "Incomplete" }
          );
          var target = field(LABEL_TO_FIELD[missing[0]] || missing[0]);
          if (target) target.focus();
          return;
        }

        var manual = (document.getElementById("manual-msgno").value || "").trim();
        if (manual) {
          askConfirmation(manual, true, doSave);
          return;
        }
        // Ask the server rather than trusting the number on screen, which may
        // be stale if another operator has saved since this page loaded.
        fetch("/message/api/next-msgno")
          .then(function (r) { return r.json(); })
          .then(function (d) {
            document.getElementById("next-msgno").textContent = d.next;
            askConfirmation(d.next, false, doSave);
          })
          .catch(function () {
            snack.error("Could not check the next message number.");
          });
      })
      .catch(function (e) {
        snack.error("Could not reach the server.", String(e));
      });
  });

  // --- success dialog ----------------------------------------------------
  // Shown only when everything finished: row written, material copied and
  // document generated. OK reloads the page for a clean form.
  function showSuccess(msgno, destination) {
    var modal = document.getElementById("success-modal");
    if (!modal) { window.location.reload(); return; }
    document.getElementById("success-number").textContent = msgno;
    document.getElementById("success-note").textContent = destination || "";
    modal.hidden = false;
    var ok = document.getElementById("success-ok");
    ok.focus();
    ok.addEventListener("click", function () {
      window.location.href = window.location.pathname;
    }, { once: true });
  }

  function refreshNextNumber() {
    fetch("/message/api/next-msgno")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var el = document.getElementById("next-msgno");
        if (el) el.textContent = d.next;
      })
      .catch(function () {});
  }

  // --- draft persistence -------------------------------------------------
  // The operator leaves this page to pick references or write OSINT notes, so
  // everything typed is pushed to the session first and restored on return.

  function collectDraft() {
    return {
      values: getValues(),
      Osint: (field("Osint") || {}).value || "",
      Extra_Add: (field("Extra_Add") || {}).value || "",
      Imp_Msg: (field("Imp_Msg") || {}).checked || false,
      manual_msgno: (document.getElementById("manual-msgno") || {}).value || "",
      source_folder: sourceFolder,
      source_folders: sourceFolders,
      logger_final: loggerFinal,
      extracted: extractedState
    };
  }

  function saveDraft() {
    return postJSON("/message/api/draft/" + MSG_TYPE, collectDraft())
      .catch(function () { /* navigation continues regardless */ });
  }

  function applyDraft(d) {
    if (!d || !Object.keys(d).length) return;
    Object.keys(d.values || {}).forEach(function (k) {
      if (String(d.values[k] || "").trim()) setValue(k, d.values[k]);
    });
    if (d.Osint) setValue("Osint", d.Osint);
    if (d.Extra_Add) setValue("Extra_Add", d.Extra_Add);
    var imp = field("Imp_Msg");
    if (imp) imp.checked = !!d.Imp_Msg;
    var manual = document.getElementById("manual-msgno");
    if (manual && d.manual_msgno) manual.value = d.manual_msgno;
    sourceFolder = d.source_folder || "";
    sourceFolders = d.source_folders || [];
    loggerFinal = d.logger_final || "";
    extractedState = d.extracted || {};
    if (sourceFolders.length) {
      statusEl.textContent = sourceFolders.length + " capture(s) restored.";
    }
  }

  ["btn-add-ref", "btn-add-osint"].forEach(function (id) {
    var btn = document.getElementById(id);
    if (!btn) return;
    btn.addEventListener("click", function () {
      var href = btn.dataset.href;
      busy(btn, true, "Saving\u2026");
      saveDraft().then(function () { window.location.href = href; });
    });
  });

  // Reset must clear the stored draft too, or it reappears on the next visit.
  var originalReset = resetForm;
  resetForm = function () {
    originalReset();
    postJSON("/message/api/draft/" + MSG_TYPE + "/clear", {}).catch(function () {});
  };

  var draftNode = document.getElementById("draft-data");
  if (draftNode) {
    try { applyDraft(JSON.parse(draftNode.textContent || "{}")); } catch (e) {}
  }

  prefillPreparedBy();
})();
