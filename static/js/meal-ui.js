/*
  meal-ui.js - the saved-meal card and the "Edit meal" pop-up, shared by the
  Dashboard and History pages (they load common.js first).

  buildMealItem(meal, options)   one saved meal as a touch-friendly card with Edit and Delete buttons
  openMealEditor(meal, onSaved)  pop-up to change the meal type and portion (PUT /api/food-log/<id>)
  confirmDeleteMeal(meal)        the "are you sure?" question before DELETE
*/

function confirmDeleteMeal(meal) {
  return window.confirm(`Delete ${meal.food} (${formatNumber(meal.calories)} kcal)?`);
}

function mealPhoto(meal) {
  return meal.image_url
    ? el("img", { class: "thumb", src: meal.image_url, alt: meal.food, loading: "lazy" })
    : el("div", { class: "thumb-empty", "aria-hidden": "true" });
}

function mealAiNote(meal) {
  if (meal.ai_guess === null) return "Typed in";
  if (!meal.was_corrected) return "AI was right";
  // On a plate only one food can be the AI's first guess: the others count if they were in its top 3.
  return meal.in_ai_top3 ? "In the AI's top 3" : `Corrected (AI said ${meal.ai_guess})`;
}

/*
  options: onEdit(meal), onDelete(meal)
           showAi    - add the "AI was right / corrected" line (History)
           showMeal  - add the meal name and time under the food (History groups by day)
*/
function buildMealItem(meal, { onEdit, onDelete, showAi = false, showMeal = false } = {}) {
  const lines = [
    el("div", { class: "meal-name" }, meal.food),
    el("div", { class: "small text-secondary" }, portionText(meal.quantity, meal.serving_unit, meal.grams)),
    el("div", { class: "small text-secondary" },
      `P ${formatNumber(meal.protein, 1)} · C ${formatNumber(meal.carbs, 1)} · F ${formatNumber(meal.fat, 1)} g`),
  ];
  if (showMeal) {
    const time = new Date(meal.logged_at.replace(" ", "T")).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
    lines.splice(1, 0, el("div", { class: "small text-secondary" }, `${MEAL_NAMES[meal.meal_type]} · ${time}`));
  }
  if (showAi) lines.push(el("div", { class: "ai-note" }, mealAiNote(meal)));

  return el("div", { class: "meal-item" },
    mealPhoto(meal),
    el("div", { class: "meal-info" }, ...lines),
    el("div", { class: "meal-kcal" }, `${formatNumber(meal.calories)} kcal`),
    el("div", { class: "meal-actions" },
      el("button", { type: "button", class: "btn btn-sm btn-outline-secondary", "aria-label": `Edit ${meal.food}`,
                     onclick: () => onEdit(meal) }, "Edit"),
      el("button", { type: "button", class: "btn btn-sm btn-outline-danger", "aria-label": `Delete ${meal.food}`,
                     onclick: () => onDelete(meal) }, "Delete")));
}

/* ------------------------------------------------------------ the Edit meal pop-up */

const mealEditor = { meal: null, onSaved: null, modal: null, timer: null, ticket: 0 };

function openMealEditor(meal, onSaved) {
  const $ = (id) => document.getElementById(id);
  const editor = mealEditor;
  editor.meal = meal;
  editor.onSaved = onSaved;
  editor.modal = bootstrap.Modal.getOrCreateInstance($("edit-meal-modal"));

  $("edit-food").textContent = meal.food;
  $("edit-serving-hint").textContent = `1 ${meal.serving_unit} = ${formatGrams(meal.serving_grams)} g`;
  $("edit-meal-type").value = meal.meal_type;
  $("edit-quantity").value = meal.quantity ?? "";
  $("edit-grams").value = meal.quantity ? "" : meal.grams;       // a meal logged by weight stays "by weight"
  clearAlert($("edit-alert"));
  $("edit-preview").textContent = "";
  $("edit-save").disabled = false;
  syncQuickButtons();
  editor.modal.show();
}

function editPortion() {
  const grams = document.getElementById("edit-grams").value.trim();
  return grams !== "" ? { grams: Number(grams) } : { quantity: Number(document.getElementById("edit-quantity").value) };
}

function syncQuickButtons() {
  const portion = editPortion();
  for (const button of document.querySelectorAll("[data-edit-quantity]")) {
    button.classList.toggle("active", portion.quantity === Number(button.dataset.editQuantity));
  }
}

/* Ask the server what the new portion would be, so the person sees the new calories before saving. */
function previewEdit() {
  const $ = (id) => document.getElementById(id);
  const editor = mealEditor;
  syncQuickButtons();
  clearTimeout(editor.timer);
  editor.timer = setTimeout(async () => {
    const ticket = ++editor.ticket;
    try {
      const result = await api("POST", "/api/calculate", { food_id: editor.meal.food_id, ...editPortion() });
      if (ticket !== editor.ticket) return;
      clearAlert($("edit-alert"));
      $("edit-save").disabled = false;
      $("edit-preview").textContent =
        `New total: ${formatNumber(result.calories)} kcal · ${formatGrams(result.grams)} g (was ${formatNumber(editor.meal.calories)} kcal)`;
    } catch (error) {
      if (ticket !== editor.ticket) return;
      $("edit-preview").textContent = "";
      $("edit-save").disabled = true;
      showAlert($("edit-alert"), error.message);
    }
  }, 250);
}

(() => {
  const form = document.getElementById("edit-meal-form");
  if (!form) return;                                              // the pop-up is only on pages that include it
  const $ = (id) => document.getElementById(id);

  for (const button of document.querySelectorAll("[data-edit-quantity]")) {
    button.addEventListener("click", () => {
      $("edit-quantity").value = button.dataset.editQuantity;
      $("edit-grams").value = "";
      previewEdit();
    });
  }
  for (const button of document.querySelectorAll("[data-edit-step]")) {
    button.addEventListener("click", () => {
      const next = (Number($("edit-quantity").value) || 1) + Number(button.dataset.editStep);
      $("edit-quantity").value = Math.min(20, Math.max(0.25, next));
      $("edit-grams").value = "";
      previewEdit();
    });
  }
  $("edit-quantity").addEventListener("input", () => { $("edit-grams").value = ""; previewEdit(); });
  $("edit-grams").addEventListener("input", previewEdit);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const editor = mealEditor;
    $("edit-save").disabled = true;
    try {
      await api("PUT", `/api/food-log/${editor.meal.id}`, { meal_type: $("edit-meal-type").value, ...editPortion() });
      editor.modal.hide();
      editor.onSaved();
    } catch (error) {
      showAlert($("edit-alert"), error.message);
      $("edit-save").disabled = false;
    }
  });
})();
