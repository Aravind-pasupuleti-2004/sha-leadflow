/* SHA LeadFlow AI — small, dependency-free UI helpers. */

(function () {
  "use strict";

  const navToggle = document.querySelector("[data-nav-toggle]");
  const nav = document.getElementById("primary-nav");

  if (navToggle && nav) {
    navToggle.addEventListener("click", function () {
      const isOpen = nav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", String(isOpen));
    });
    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        nav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        nav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.focus();
      }
    });
  }

  document.querySelectorAll("[data-dismiss]").forEach(function (button) {
    button.addEventListener("click", function () {
      const flash = button.closest(".flash");
      if (flash) {
        flash.remove();
      }
    });
  });

  document.querySelectorAll("textarea[data-counter]").forEach(function (textarea) {
    const name = textarea.getAttribute("data-counter");
    const wrapper = document.querySelector('[data-counter-for="' + name + '"]');
    if (!wrapper) return;
    const count = wrapper.querySelector("span");
    const max = textarea.getAttribute("maxlength") || "";
    const update = function () {
      if (count) count.textContent = String(textarea.value.length);
    };
    textarea.addEventListener("input", update);
    update();
    if (count && max) count.setAttribute("title", "Maximum " + max + " characters");
  });

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    const confirmMessage = form.getAttribute("data-confirm");
    if (confirmMessage && !window.confirm(confirmMessage)) {
      event.preventDefault();
      return;
    }

    if (form.hasAttribute("data-submit-once")) {
      const button = form.querySelector('button[type="submit"]');
      if (button) {
        window.setTimeout(function () {
          button.disabled = true;
          button.textContent = "Working…";
        }, 0);
      }
    }
  });

  document.querySelectorAll("[data-copy-target]").forEach(function (button) {
    button.addEventListener("click", function () {
      const target = document.getElementById(button.getAttribute("data-copy-target"));
      if (!target) return;
      const text = target.textContent.replace(/^\s+|\s+$/g, "");
      const done = function () {
        const original = button.textContent;
        button.textContent = "Copied";
        window.setTimeout(function () {
          button.textContent = original;
        }, 1600);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done).catch(function () {});
      } else {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        try {
          document.execCommand("copy");
          done();
        } catch (error) {
          /* Clipboard is a convenience; the draft remains selectable. */
        }
        document.body.removeChild(helper);
      }
    });
  });
})();
