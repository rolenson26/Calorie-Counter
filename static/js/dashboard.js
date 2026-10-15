/*
  dashboard.js - fills the Dashboard page from GET /api/dashboard?date=YYYY-MM-DD.

  Chart choices (kept simple and readable):
    * one big number for calories, with a meter against the goal
    * one stacked bar for "where the calories come from" (every value also written as text)
    * thin columns for the last 7 days, a goal line, a hover tooltip and a table twin
*/
(() => {
  const $ = (id) => document.getElementById(id);
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();

  const NUTRIENTS = [
    { key: "protein", label: "Protein", color: "--series-1" },
    { key: "carbs", label: "Carbohydrates", color: "--series-2" },
    { key: "fat", label: "Fat", color: "--series-3" },
  ];

  let weekChart = null;
  let shownDate = isoDate();
  let lastData = null;                                // kept so the chart can be redrawn when the theme changes

  async function load(day) {
    const dashboard = $("dashboard");
    dashboard.classList.add("loading");               // keep the old numbers, dimmed, while loading
    try {
      const data = await api("GET", `/api/dashboard?date=${day}`);
      shownDate = data.date;
      lastData = data;
      render(data);
      clearAlert($("dash-alert"));
    } catch (error) {
      showAlert($("dash-alert"), error.message);
    } finally {
      dashboard.classList.remove("loading");
    }
  }

  function render(data) {
    const isToday = data.date === isoDate();
    $("dash-date").value = data.date;
    $("btn-next-day").disabled = data.date >= isoDate();           // no future days
    $("dash-date-label").textContent =
      (isToday ? "Today, " : "") + formatDay(data.date, { weekday: "long", day: "numeric", month: "long", year: "numeric" });

    renderCalories(data);
    $("kpi-meals").textContent = data.meals_count;
    for (const key of ["protein", "carbs", "fat", "fiber"]) {
      $(`kpi-${key}`).textContent = formatNumber(data.totals[key], 1);
    }
    renderSplit(data);
    renderWeek(data.last_7_days, data.goal);
    renderMeals(data.meals, data.by_meal_type);
  }

  function renderCalories(data) {
    $("kpi-consumed").textContent = formatNumber(data.consumed);
    $("kpi-goal-text").textContent = `of your ${formatNumber(data.goal)} kcal daily goal`;
    $("goal-input").value = data.goal;
    $("kpi-left").textContent = formatNumber(Math.max(data.remaining, 0));

    const over = data.remaining < 0;
    const meter = $("kpi-meter");
    meter.classList.toggle("over", over);
    meter.setAttribute("aria-valuenow", String(data.percent_of_goal));
    $("kpi-meter-fill").style.width = `${Math.min(data.percent_of_goal, 100)}%`;

    const note = $("kpi-remaining");
    note.className = over ? "over-text" : "";
    note.textContent = over
      ? `▲ ${formatNumber(-data.remaining)} kcal over the goal`
      : `${formatNumber(data.remaining)} kcal left · ${data.percent_of_goal}% of goal`;
  }

  /* Part-to-whole as ONE stacked bar; the legend repeats every value as text. */
  function renderSplit(data) {
    const split = data.energy_split_percent;
    const bar = $("split-bar");
    const total = NUTRIENTS.reduce((sum, n) => sum + split[n.key], 0);
    bar.classList.toggle("empty", total === 0);
    bar.replaceChildren(...(total === 0 ? [] : NUTRIENTS.filter((n) => split[n.key] > 0).map((n) =>
      el("span", {
        style: `flex: ${split[n.key]} 1 0; background: ${color(n.color)}`,
        title: `${n.label}: ${split[n.key]}% of calories`,
      })
    )));
    $("split-legend").replaceChildren(...NUTRIENTS.map((n) =>
      el("li", {},
        el("span", { class: "swatch", style: `background: ${color(n.color)}`, "aria-hidden": "true" }),
        n.label,
        el("span", { class: "value" }, total === 0 ? "–" : `${split[n.key]}% · ${formatNumber(data.totals[n.key], 1)} g`))
    ));
  }

  /* Last 7 days: one series (no colour legend needed for it), plus the goal as a reference line. */
  function renderWeek(days, goal) {
    const hasData = days.some((d) => d.calories > 0);
    $("week-chart-box").hidden = !hasData;
    $("week-empty").hidden = hasData;
    $("week-empty").replaceChildren(...(hasData ? [] : [
      emptyState("📊", "No meals in the last 7 days", "Your chart will appear after you save a meal.",
        el("a", { class: "btn btn-primary", href: "/" }, "Scan a meal"))]));

    // Two-line labels ("Sat" / "26") fit on a phone without tilting the text.
    const labels = days.map((d) => [formatDay(d.date, { weekday: "short" }), formatDay(d.date, { day: "numeric" })]);
    const values = days.map((d) => d.calories);
    const ink = color("--ink");
    const ink2 = color("--ink-2");
    const muted = color("--muted");

    const data = {
      labels,
      datasets: [
        {
          type: "bar",
          label: "Calories eaten",
          data: values,
          backgroundColor: color("--series-1"),
          hoverBackgroundColor: color("--series-1-hover"),
          borderRadius: { topLeft: 4, topRight: 4 },
          borderSkipped: "bottom",
          maxBarThickness: 24,
          pointStyle: "rect",           // legend key mirrors the mark: a box for bars
          order: 2,
        },
        {
          type: "line",
          label: `Daily goal (${formatNumber(goal)} kcal)`,
          data: days.map(() => goal),
          borderColor: ink2,
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 0,
          pointStyle: "line",           // ...and a line for the goal line
          order: 1,                     // drawn on top of the bars
        },
      ],
    };

    if (weekChart) {
      weekChart.data = data;
      weekChart.options.scales.y.suggestedMax = Math.max(goal, ...values) * 1.1;
      weekChart.update();
    } else {
      weekChart = new Chart($("week-chart"), {
        data,
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 300 },
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: {
              position: "top",
              align: "start",
              labels: {
                color: ink2,
                usePointStyle: true,
                boxHeight: 8,
                font: { size: 12 },
                sort: (a, b) => a.datasetIndex - b.datasetIndex,      // calories first, then the goal
              },
            },
            tooltip: {
              itemSort: (a, b) => a.datasetIndex - b.datasetIndex,
              backgroundColor: color("--surface"),
              titleColor: ink,
              bodyColor: ink2,
              borderColor: color("--axis"),
              borderWidth: 1,
              padding: 10,
              callbacks: {
                label: (context) => ` ${context.dataset.label.split(" (")[0]}: ${formatNumber(context.parsed.y)} kcal`,
              },
            },
          },
          scales: {
            x: { grid: { display: false }, border: { color: color("--axis") }, ticks: { color: muted, maxRotation: 0, autoSkip: false, font: { size: 11 } } },
            y: {
              beginAtZero: true,
              suggestedMax: Math.max(goal, ...values) * 1.1,
              grid: { color: color("--grid") },
              border: { display: false },
              ticks: { color: muted, maxTicksLimit: 5, font: { size: 11 }, callback: (value) => formatNumber(value) },
            },
          },
        },
      });
    }

    $("week-table").tBodies[0].replaceChildren(...days.map((d) =>
      el("tr", {},
        el("td", {}, formatDay(d.date)),
        el("td", { class: "num" }, formatNumber(d.calories)),
        el("td", { class: "num" }, formatNumber(goal)))
    ));
  }

  function renderMeals(meals, byMealType) {
    const box = $("meals");
    if (!meals.length) {
      box.replaceChildren(emptyState("🍽", "No meals logged on this day",
        "Take a photo of your meal, or search for a food, and it will show up here.",
        el("a", { class: "btn btn-primary", href: "/" }, "Scan your first meal")));
      return;
    }
    // One block per meal type (breakfast first); inside it the oldest meal comes first.
    const groups = MEAL_ORDER
      .map((meal) => ({ meal, items: meals.filter((m) => m.meal_type === meal).reverse() }))
      .filter((group) => group.items.length)
      .map(({ meal, items }) => el("div", {},
        el("div", { class: "group-head" }, el("span", {}, MEAL_NAMES[meal]),
          el("span", { class: "total" }, `${formatNumber(byMealType[meal])} kcal`)),
        ...items.map((item) => buildMealItem(item, { onEdit: editMeal, onDelete: deleteMeal }))));
    box.replaceChildren(...groups);
  }

  function editMeal(meal) {
    openMealEditor(meal, () => load(shownDate));
  }

  async function deleteMeal(meal) {
    if (!confirmDeleteMeal(meal)) return;
    try {
      await api("DELETE", `/api/food-log/${meal.id}`);
      load(shownDate);
    } catch (error) {
      showAlert($("dash-alert"), error.message);
    }
  }

  /* ------------------------------------------------------------ controls */

  $("dash-date").addEventListener("change", (event) => {
    if (event.target.value) load(event.target.value);
  });
  $("btn-today").addEventListener("click", () => load(isoDate()));
  function shiftDay(days) {
    const day = parseIsoDate(shownDate);
    day.setDate(day.getDate() + days);
    load(isoDate(day));
  }
  $("btn-prev-day").addEventListener("click", () => shiftDay(-1));
  $("btn-next-day").addEventListener("click", () => shiftDay(1));
  document.addEventListener("themechange", () => {     // chart colours are read once, so draw it again
    if (!lastData) return;
    if (weekChart) { weekChart.destroy(); weekChart = null; }
    render(lastData);
  });
  $("btn-week-table").addEventListener("click", (event) => {
    const table = $("week-table");
    table.hidden = !table.hidden;
    event.target.textContent = table.hidden ? "Show as table" : "Hide table";
    event.target.setAttribute("aria-expanded", String(!table.hidden));
  });
  $("goal-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("PUT", "/api/user/goal", { daily_calorie_goal: Number($("goal-input").value) });
      bootstrap.Collapse.getOrCreateInstance($("goal-form")).hide();
      load(shownDate);
    } catch (error) {
      showAlert($("dash-alert"), error.message);
    }
  });

  load(shownDate);
})();
