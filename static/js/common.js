/*
  common.js - small helpers used by every page.

  api()  talks to the Flask JSON API and turns {"success": false, "error": ...}
         into a thrown Error, so pages can use try/catch.
  el()   builds HTML elements safely: text is always set with textContent,
         never innerHTML, so a food name typed by a user can never inject HTML.
*/

async function api(method, url, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body instanceof FormData) {
    options.body = body;                                   // the browser sets the multipart header
  } else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Cannot reach the server. Is the app still running?");
  }
  if (response.status === 401) {                           // session ended: go and log in again
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    throw new Error("Please log in again");
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    // not JSON (for example a proxy error page)
  }
  if (!response.ok || !data || data.success === false) {
    const error = new Error((data && data.error) || `Something went wrong (${response.status})`);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function showAlert(container, message, kind = "danger") {
  container.replaceChildren(el("div", { class: `alert alert-${kind} mb-0`, role: kind === "danger" ? "alert" : "status" }, message));
}

function clearAlert(container) {
  container.replaceChildren();
}

/* ------------------------------------------------------------ formatting */

function formatNumber(value, digits = 0) {
  return Number(value).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatGrams(value) {
  return formatNumber(value, Number.isInteger(value) ? 0 : 1);
}

function formatPercent(fraction) {
  return `${Math.round(fraction * 100)}%`;
}

const PLURAL_UNITS = { glass: "glasses" };

function unitName(unit, quantity) {
  if (quantity === 1) return unit;
  return PLURAL_UNITS[unit] || `${unit}s`;
}

function formatQuantity(quantity) {
  const whole = Math.floor(quantity);
  const rest = quantity - whole;
  const fractions = { 0.25: "¼", 0.5: "½", 0.75: "¾" };
  if (fractions[rest]) return `${whole || ""}${fractions[rest]}`;
  return formatNumber(quantity, Number.isInteger(quantity) ? 0 : 2);
}

/* "2 pieces · 80 g", or just "120 g" when the user typed grams */
function portionText(quantity, unit, grams) {
  const weight = `${formatGrams(grams)} g`;
  return quantity ? `${formatQuantity(quantity)} ${unitName(unit, quantity)} · ${weight}` : weight;
}

/* Local date as YYYY-MM-DD (toISOString would give the UTC date, a day off late at night in India). */
function isoDate(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function parseIsoDate(text) {
  const [year, month, day] = text.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function formatDay(text, options = { weekday: "short", day: "numeric", month: "short" }) {
  return parseIsoDate(text).toLocaleDateString("en-IN", options);
}

const MEAL_NAMES = { breakfast: "Breakfast", lunch: "Lunch", snack: "Snack", dinner: "Dinner" };
const MEAL_ORDER = ["breakfast", "lunch", "snack", "dinner"];

/* ------------------------------------------------------------ light / dark mode */

/* base.html sets data-bs-theme before the page is drawn; this wires the navbar button. */
(() => {
  const button = document.getElementById("theme-toggle");
  if (!button) return;

  function show() {
    const dark = document.documentElement.getAttribute("data-bs-theme") === "dark";
    button.querySelector(".theme-icon").textContent = dark ? "☀" : "☾";
    button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }

  button.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-bs-theme", next);
    try { localStorage.setItem("theme", next); } catch { /* private mode: the choice just isn't remembered */ }
    show();
    document.dispatchEvent(new CustomEvent("themechange"));    // the dashboard chart redraws itself
  });
  show();
})();

/* ------------------------------------------------------------ empty states */

/* A plain "nothing here yet" block: a title, one sentence and an optional button/link.
   (The first argument used to be a decorative emoji; it is ignored now, so callers need not change.) */
function emptyState(_symbol, title, text, action) {
  return el("div", { class: "empty-state" },
    el("p", { class: "fw-semibold mb-1" }, title),
    el("p", { class: "text-secondary mb-3" }, text),
    action || null);
}

/* ------------------------------------------------------------ show / hide password */

for (const box of document.querySelectorAll("[data-toggle-password]")) {
  box.addEventListener("change", () => {
    document.getElementById(box.dataset.togglePassword).type = box.checked ? "text" : "password";
  });
}
