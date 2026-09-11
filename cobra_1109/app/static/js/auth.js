// Auto-uppercase the NameID field as the user types (matches how it's stored/looked up).
document.addEventListener("DOMContentLoaded", () => {
  const idField = document.getElementById("name_id");
  if (idField) {
    idField.addEventListener("input", () => {
      const pos = idField.selectionStart;
      idField.value = idField.value.toUpperCase();
      idField.setSelectionRange(pos, pos);
    });
  }
});
