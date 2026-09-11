// Theme persistence. Light is the default; dark is opt-in per machine.
// The initial value is applied by an inline script in <head> (see base.html)
// so there is no flash of the wrong theme before this file loads.
(function () {
  const KEY = "cobra-theme";

  function setTheme(theme) {
    if (theme === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    try {
      localStorage.setItem(KEY, theme);
    } catch (e) {
      // Private mode / storage disabled — theme still applies for this page.
    }
  }

  window.cobraToggleTheme = function () {
    const isDark =
      document.documentElement.getAttribute("data-theme") === "dark";
    setTheme(isDark ? "light" : "dark");
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      btn.addEventListener("click", window.cobraToggleTheme);
    });
  });
})();
