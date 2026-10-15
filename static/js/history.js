/*
  history.js - lists meals between two dates (GET /api/history?from=&to=).
  Phones see cards grouped by day; wider screens see a table. Each meal can be
  edited (portion / meal type) or deleted. The AI note shows whether the user kept
  or corrected the AI's suggestion, which is the evidence for real-use accuracy.
*/
(() => {
  const $ = (id) => document.getElementById(id);

  function daysAgo(n) {
    const date = new Date();
    date.setDate(date.getDate() - n);
    return isoDate(date);
  }

  async function load() {
    clearAlert($("history-alert"));
    const from = $("from").value;
    const to = $("to").value;
    try {
      const data = await api("GET", `/api/history?from=${from}&to=${to}`);
      render(data.logs, from, to);
    } catch (error) {
      showAlert($("history-alert"), error.message);
    }
  }

  function render(logs, from, to) {
    const total = logs.reduce((sum, log) => sum + log.calories, 0);
    const fromPhoto = logs.filter((log) => log.ai_guess !== null);
    const kept = fromPhoto.filter((log) => !log.was_corrected).length;
    $("history-summary").textContent = logs.length
      ? `${logs.length} meal${logs.length === 1 ? "" : "s"} · ${formatNumber(total)} kcal in total` +
        (fromPhoto.length ? ` · AI suggestion kept for ${kept} of ${fromPhoto.length} photo meals` : "")
      : "";

    const empty = !logs.length;
    $("history-empty").hidden = !empty;
    $("history-cards").hidden = empty;
    $("history-table-card").hidden = empty;
    $("history-empty").replaceChildren(...(empty ? [emptyState("📖", "No meals in this period",
      `Nothing was logged between ${formatDay(from)} and ${formatDay(to)}. Try a longer range, or add a meal.`,
      el("a", { class: "btn btn-primary", href: "/" }, "Scan a meal"))] : []));

    $("history-rows").replaceChildren(...logs.map(row));
    $("history-list").replaceChildren(...cardsByDay(logs));
  }

  /* Phone layout: a heading per day with that day's total, then its meals (newest first). */
  function cardsByDay(logs) {
    const days = [];
    for (const log of logs) {
      let day = days.find((d) => d.date === log.log_date);
      if (!day) days.push((day = { date: log.log_date, items: [], total: 0 }));
      day.items.push(log);
      day.total += log.calories;
    }
    return days.map((day) => el("div", {},
      el("div", { class: "group-head" }, el("span", {}, formatDay(day.date, { weekday: "short", day: "numeric", month: "short" })),
        el("span", { class: "total" }, `${formatNumber(day.total)} kcal`)),
      ...day.items.map((log) => buildMealItem(log, { onEdit: edit, onDelete: remove, showAi: true, showMeal: true }))));
  }

  function aiCell(log) {
    return el("span", { class: "ai-note" }, mealAiNote(log));
  }

  /* Table layout */
  function row(log) {
    const when = log.logged_at.replace(" ", "T");
    return el("tr", {},
      el("td", { class: "text-nowrap" },
        el("div", {}, formatDay(log.log_date)),
        el("div", { class: "small text-secondary" },
          `${MEAL_NAMES[log.meal_type]} · ${new Date(when).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}`)),
      el("td", {}, mealPhoto(log)),
      el("td", { class: "fw-semibold" }, log.food),
      el("td", { class: "text-nowrap" }, portionText(log.quantity, log.serving_unit, log.grams)),
      el("td", { class: "num fw-semibold" }, formatNumber(log.calories)),
      el("td", { class: "num" }, `${formatNumber(log.protein, 1)} g`),
      el("td", { class: "num" }, `${formatNumber(log.carbs, 1)} g`),
      el("td", { class: "num" }, `${formatNumber(log.fat, 1)} g`),
      el("td", { class: "num" }, `${formatNumber(log.fiber, 1)} g`),
      el("td", {}, aiCell(log)),
      el("td", { class: "text-end text-nowrap" },
        el("button", { type: "button", class: "btn btn-sm btn-outline-secondary me-1", "aria-label": `Edit ${log.food}`,
                       onclick: () => edit(log) }, "Edit"),
        el("button", { type: "button", class: "btn btn-sm btn-outline-danger", "aria-label": `Delete ${log.food}`,
                       onclick: () => remove(log) }, "Delete")));
  }

  function edit(log) {
    openMealEditor(log, load);
  }

  async function remove(log) {
    if (!confirmDeleteMeal(log)) return;
    try {
      await api("DELETE", `/api/food-log/${log.id}`);
      load();
    } catch (error) {
      showAlert($("history-alert"), error.message);
    }
  }

  function setRange(days) {
    $("from").value = daysAgo(days - 1);
    $("to").value = isoDate();
    load();
  }

  for (const button of document.querySelectorAll("[data-days]")) {
    button.addEventListener("click", () => setRange(Number(button.dataset.days)));
  }
  $("range-form").addEventListener("submit", (event) => {
    event.preventDefault();
    load();
  });
  $("from").max = $("to").max = isoDate();
  setRange(7);                                     // the server enforces the 31-day limit and explains it
})();
