/*
  foods.js - the Food database page.
  Loads every food once (GET /api/foods), filters in the browser by search text and
  by category chip, and adds a missing food with POST /api/foods. The server checks
  the values and answers with every problem at once, which is shown as a list.
  Phones see one card per food; wider screens see the table.
*/
(() => {
  const $ = (id) => document.getElementById(id);
  const CUSTOM = "__custom__";                         // the "Added by you" chip is not a real category
  let foods = [];
  let category = "";                                   // "" = all, CUSTOM = added by users, otherwise a category name

  async function load() {
    try {
      foods = (await api("GET", "/api/foods")).foods;
      const categories = [...new Set(foods.map((f) => f.category))].sort();
      $("category-list").replaceChildren(...categories.map((c) => el("option", { value: c })));
      renderChips(categories);
      render();
    } catch (error) {
      showAlert($("foods-alert"), error.message);
    }
  }

  function renderChips(categories) {
    const chip = (value, label) => el("button", {
      type: "button",
      class: "chip",
      "aria-pressed": String(category === value),
      onclick: () => { category = value; renderChips(categories); render(); },
    }, label);
    const chips = [chip("", "All"), ...categories.map((c) => chip(c, c))];
    if (foods.some((f) => f.is_custom)) chips.push(chip(CUSTOM, "Added by you"));
    $("category-chips").replaceChildren(...chips);
  }

  function matches(food, query) {
    if (category === CUSTOM ? !food.is_custom : category && food.category !== category) return false;
    return !query || food.name.toLowerCase().includes(query) || food.category.toLowerCase().includes(query);
  }

  function render() {
    const query = $("food-filter").value.trim().toLowerCase();
    const shown = foods.filter((f) => matches(f, query));
    $("food-count").textContent = `Showing ${shown.length} of ${foods.length} foods`;

    if (!shown.length) {
      const none = el("p", { class: "text-secondary mb-0 py-3" },
        "No food matches. ", el("a", { href: "#add-food" }, "Add it below"), ".");
      $("food-rows").replaceChildren(el("tr", {}, el("td", { colspan: "9" }, none)));
      $("food-card-list").replaceChildren(none.cloneNode(true));
      return;
    }
    $("food-rows").replaceChildren(...shown.map(tableRow));
    $("food-card-list").replaceChildren(...shown.map(card));
  }

  const customBadge = (f) => (f.is_custom ? el("span", { class: "badge badge-custom ms-2" }, "Custom") : null);

  function tableRow(f) {
    return el("tr", {},
      el("td", { class: "fw-semibold" }, f.name, customBadge(f)),
      el("td", {}, f.category),
      el("td", { class: "text-nowrap" }, `1 ${f.serving_unit} = ${formatGrams(f.serving_grams)} g`),
      el("td", { class: "num" }, formatNumber(f.calories_per_100g, 1)),
      el("td", { class: "num" }, formatNumber(f.protein_per_100g, 1)),
      el("td", { class: "num" }, formatNumber(f.carbs_per_100g, 1)),
      el("td", { class: "num" }, formatNumber(f.fat_per_100g, 1)),
      el("td", { class: "num" }, formatNumber(f.fiber_per_100g, 1)),
      el("td", { class: "small text-secondary" }, f.source));
  }

  /* Phone layout: name and calories on top, then the four nutrients in a row. */
  function card(f) {
    const macro = (label, value) => el("div", {}, formatNumber(value, 1), el("span", {}, label));
    return el("div", { class: "food-card" },
      el("div", { class: "d-flex justify-content-between align-items-baseline gap-2" },
        el("div", { class: "fw-semibold" }, f.name, customBadge(f)),
        el("div", { class: "meal-kcal" }, `${formatNumber(f.calories_per_100g)} kcal`)),
      el("div", { class: "small text-secondary" }, `${f.category} · 1 ${f.serving_unit} = ${formatGrams(f.serving_grams)} g · per 100 g`),
      el("div", { class: "food-macros" },
        macro("Protein", f.protein_per_100g), macro("Carbs", f.carbs_per_100g),
        macro("Fat", f.fat_per_100g), macro("Fiber", f.fiber_per_100g)),
      el("div", { class: "small text-secondary mt-1" }, `Source: ${f.source}`));
  }

  async function addFood(event) {
    event.preventDefault();
    const form = event.target;
    const body = Object.fromEntries(new FormData(form).entries());
    clearAlert($("add-alert"));
    try {
      const data = await api("POST", "/api/foods", body);
      showAlert($("add-alert"), `${data.food.name} was added. The AI can now suggest it too.`, "success");
      form.reset();
      category = "";
      $("food-filter").value = data.food.name;
      await load();
    } catch (error) {
      const problems = (error.data && error.data.errors) || [error.message];
      $("add-alert").replaceChildren(el("div", { class: "alert alert-danger", role: "alert" },
        el("ul", { class: "mb-0 ps-3" }, ...problems.map((p) => el("li", {}, p)))));
    }
  }

  $("food-filter").addEventListener("input", render);
  $("add-food-form").addEventListener("submit", addFood);
  load();
})();
