/*
  main.js - the Scan page.

  Flow (matches the HLD workflow):
    photo (live camera, phone camera app or file) -> preview: use / retake / change
    -> shrink in the browser -> POST /api/predict -> show top 3 + confidence
    -> user puts one or more foods on "Your plate" (AI suggestions, search, recent foods),
       each with its own portion -> POST /api/calculate for each food
    -> result card (total + one row per food) -> POST /api/food-log/batch -> today's total and progress.

  Camera: where the browser allows it (HTTPS or localhost) the page opens its own live
  camera preview with getUserMedia. Otherwise "Take Photo" falls back to
  <input type="file" capture="environment">, which opens the phone's camera app.
*/
(() => {
  const $ = (id) => document.getElementById(id);
  const steps = { capture: $("step-capture"), preview: $("step-preview"), confirm: $("step-confirm"), result: $("step-result") };
  const LEVEL_TEXT = {
    high: "High confidence",
    medium: "Medium confidence",
    low: "Low confidence",
    not_food: "Doesn't look like food",
  };
  const MAX_SIDE = 1280;                        // photos are shrunk to this before uploading
  const MAX_PICKED_BYTES = 30 * 1024 * 1024;    // refuse absurdly large files before even decoding them
  const MAX_PLATE_ITEMS = 10;                   // the same limit as /api/food-log/batch
  const QUICK_PORTIONS = [0.5, 1, 1.5, 2, 3];

  const state = {
    prediction: null,                   // answer from /api/predict (null = no photo)
    plate: [],                          // [{key, food, quantity, grams}] - the foods the user chose
    calculated: [],                     // [{food_id, portion, result}] from the last calculation (what Save stores)
    recent: [],                         // foods this user logged before (quick add)
  };
  let plateKey = 0;                     // gives every plate card its own element ids
  const pending = { file: null, source: null, url: null };   // the photo waiting in the preview step

  /* ------------------------------------------------------------ helpers */

  function showStep(name) {
    for (const [key, section] of Object.entries(steps)) section.hidden = key !== name;
    steps[name].scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setPhotoButtons(enabled) {
    $("btn-camera").disabled = !enabled;
    $("btn-upload").disabled = !enabled;
  }

  function defaultMealType() {
    const hour = new Date().getHours();
    if (hour < 11) return "breakfast";
    if (hour < 16) return "lunch";
    if (hour < 19) return "snack";
    return "dinner";
  }

  /* A clearer message for the problems a user can actually fix. */
  function friendlyError(error) {
    const text = error.message;
    if (error.status === 503) return `${text} Your photo is kept: tap "Use this photo" again in a moment.`;
    if (error.status === 413) return `${text}. Try a smaller photo.`;
    if (error.status === 415 || error.status === 400) return `${text}. Try a different photo.`;
    if (error.status >= 500) return `${text} Please try again.`;
    return text;
  }

  /* ------------------------------------------------------------ step 1: model status */

  async function watchModel() {
    const box = $("model-status");
    let retry = true;
    try {
      const status = await api("GET", "/api/status");
      if (status.model_ready) {
        box.replaceChildren();
        setPhotoButtons(true);
        retry = false;
      } else if (status.model_error) {
        showAlert(box, status.model_error);
        setPhotoButtons(false);
        retry = false;
      } else {
        showAlert(box, "The AI model is loading. The first start can take a minute. You can already log a food without a photo.", "info");
        setPhotoButtons(false);
      }
    } catch (error) {
      showAlert(box, error.message, "warning");
    }
    if (retry) setTimeout(watchModel, 2000);
  }

  /* ------------------------------------------------------------ step 1: live camera */

  const camera = { stream: null, facing: "environment", liveFailed: false };

  function liveCameraAvailable() {
    return Boolean(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function stopStream() {
    if (camera.stream) camera.stream.getTracks().forEach((track) => track.stop());
    camera.stream = null;
    $("camera-video").srcObject = null;
  }

  async function startStream() {
    stopStream();
    camera.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: camera.facing }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    const video = $("camera-video");
    video.srcObject = camera.stream;
    await video.play();
  }

  function closeCamera() {
    stopStream();
    $("camera-overlay").hidden = true;
    document.body.classList.remove("no-scroll");
  }

  /* The alert goes where the user is looking: the preview step if it is open, otherwise step 1. */
  function visibleAlertBox() {
    return steps.preview.hidden ? $("capture-alert") : $("preview-alert");
  }

  async function openCamera() {
    if (!liveCameraAvailable() || camera.liveFailed) {
      $("camera-input").click();                       // the phone's own camera app (or a file picker on a laptop)
      return;
    }
    try {
      await startStream();
    } catch {
      camera.liveFailed = true;                        // permission refused or no camera: stop trying
      stopStream();
      showAlert(visibleAlertBox(),
        "The live camera could not be opened (permission refused or no camera). " +
        "Tap Take Photo again to use your phone's camera app instead.", "warning");
      return;
    }
    $("camera-overlay").hidden = false;
    document.body.classList.add("no-scroll");
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      $("camera-flip").hidden = devices.filter((d) => d.kind === "videoinput").length < 2;
    } catch {
      $("camera-flip").hidden = true;
    }
    $("camera-shutter").focus();
  }

  async function flipCamera() {
    camera.facing = camera.facing === "environment" ? "user" : "environment";
    try {
      await startStream();
    } catch {
      closeCamera();
      showAlert(visibleAlertBox(), "Could not switch cameras.", "warning");
    }
  }

  function takeSnapshot() {
    const video = $("camera-video");
    if (!video.videoWidth) return;                     // the camera is not producing pictures yet
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) {
        showAlert(visibleAlertBox(), "Could not take the photo. Please try again.");
        return;
      }
      closeCamera();
      showPreview(new File([blob], "camera.jpg", { type: "image/jpeg" }), "camera-live");
    }, "image/jpeg", 0.92);
  }

  /* ------------------------------------------------------------ step 1b: preview, retake, upload */

  function releasePending() {
    if (pending.url) URL.revokeObjectURL(pending.url);
    pending.file = pending.source = pending.url = null;
  }

  function setPreviewBusy(busy, text = "Preparing your photo…") {
    $("preview-busy").hidden = !busy;
    $("preview-busy-text").textContent = text;
    for (const id of ["btn-use-photo", "btn-retake", "btn-change"]) $(id).disabled = busy;
  }

  function showPreview(file, source) {
    clearAlert($("capture-alert"));
    if (!file) return;
    if (file.type && !file.type.startsWith("image/")) {
      showAlert($("capture-alert"), "Please choose a photo (JPG, PNG or WEBP).");
      return;
    }
    if (file.size > MAX_PICKED_BYTES) {
      showAlert($("capture-alert"), "That file is too large. Please choose a photo under 30 MB.");
      return;
    }
    releasePending();
    pending.file = file;
    pending.source = source;
    pending.url = URL.createObjectURL(file);

    const image = $("preview-image");
    image.onload = () => { $("btn-use-photo").disabled = false; };
    image.onerror = () => {
      $("btn-use-photo").disabled = true;
      showAlert($("preview-alert"),
        "This photo cannot be shown by your browser (for example an iPhone HEIC file). Choose another, or save it as a JPG first.");
    };
    image.src = pending.url;

    $("preview-meta").textContent = `${file.name || "Photo"} · ${file.size < 1024 * 1024 ? Math.max(1, Math.round(file.size / 1024)) + " KB" : (file.size / (1024 * 1024)).toFixed(1) + " MB"}`;
    $("btn-retake").hidden = source === "upload";
    clearAlert($("preview-alert"));
    setPreviewBusy(false);
    showStep("preview");
  }

  /* Shrink big phone photos (4-8 MB) to about 1280 px, so uploads are quick.
     The server still checks everything, because a browser can be bypassed. */
  async function shrinkImage(file) {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      const context = canvas.getContext("2d");
      context.fillStyle = "#fff";                        // transparent PNG areas become white
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close();
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
      return blob || file;
    } catch {
      return file;                                       // the browser can't decode it: let the server decide
    }
  }

  async function usePhoto() {
    if (!pending.file) return;
    clearAlert($("preview-alert"));
    setPreviewBusy(true, "Preparing your photo…");
    try {
      const file = pending.file;
      const image = await shrinkImage(file);
      setPreviewBusy(true, "The AI is looking at your food… this takes a few seconds");
      const form = new FormData();
      form.append("image", image, image === file ? file.name : "photo.jpg");
      const prediction = await api("POST", "/api/predict", form);
      setPreviewBusy(false);
      releasePending();
      showConfirm(prediction);
    } catch (error) {
      setPreviewBusy(false);
      showAlert($("preview-alert"), friendlyError(error));
    }
  }

  function pickedFile(input, source) {
    const file = input.files[0];
    input.value = "";                                    // lets the same file be chosen again
    showPreview(file, source);
  }

  /* ------------------------------------------------------------ quick add (recent foods) */

  async function loadRecent() {
    try {
      state.recent = (await api("GET", "/api/foods/recent")).foods;
    } catch {
      state.recent = [];                                 // a convenience only: never block the page
    }
    renderRecent();
  }

  function renderRecent() {
    const chips = (onPick) => state.recent.map((food) =>
      el("button", { type: "button", class: "chip", onclick: () => onPick(food) }, food.name));
    $("recent-box").hidden = !state.recent.length;
    $("recent-foods").replaceChildren(...chips(quickAdd));                // landing page: start a new plate
    const showHere = state.recent.length > 0 && !state.prediction && !steps.confirm.hidden;
    $("recent-confirm").hidden = !showHere;
    $("recent-confirm-foods").replaceChildren(...(showHere ? chips(addFood) : []));   // confirm step: add to this plate
  }

  function quickAdd(food) {
    showConfirm(null, { food });
  }

  /* ------------------------------------------------------------ step 2: confirm food and portion */

  function showConfirm(prediction, { keepMeal = false, food = null } = {}) {
    state.prediction = prediction;
    state.plate = [];
    clearAlert($("confirm-alert"));
    $("food-search").value = "";
    $("search-results").replaceChildren();
    if (!keepMeal) $("meal-type").value = defaultMealType();   // more items from the same photo share one meal
    $("btn-change-photo").textContent = prediction ? "Change photo" : "Start over";

    const photo = $("photo-preview");
    if (prediction) {
      photo.src = prediction.image_url;
      photo.hidden = false;
      $("no-photo").hidden = true;
      $("prediction-box").hidden = false;

      const level = prediction.confidence_level;
      const top = prediction.top_predictions[0];
      const badge = $("confidence-badge");
      badge.className = `level-badge level-${level}`;
      const label = prediction.is_food ? `${LEVEL_TEXT[level]} · ${formatPercent(top.confidence)}` : LEVEL_TEXT.not_food;
      badge.replaceChildren(el("span", { class: "dot", "aria-hidden": "true" }), label);
      $("conf-meter").className = `conf-meter level-${level}`;
      $("conf-meter").hidden = !prediction.is_food;
      $("conf-fill").style.width = prediction.is_food ? `${Math.round(top.confidence * 100)}%` : "0%";
      $("prediction-message").textContent = prediction.message;
      $("multi-hint").hidden = !prediction.is_food;
      renderSuggestions(prediction.is_food ? prediction.top_predictions : []);
      if (level === "high") addFood(top);
    } else {
      photo.hidden = true;
      photo.removeAttribute("src");
      $("no-photo").hidden = false;
      $("prediction-box").hidden = true;
    }
    if (food) addFood(food);

    renderPlate();
    showStep("confirm");
    renderRecent();
    const level = prediction && prediction.confidence_level;
    if (!food && (!prediction || level === "low" || level === "not_food")) $("food-search").focus({ preventScroll: true });
  }

  /* The AI's suggestions (3 to 8 foods) as toggle buttons, then a "+ Add a food" tile for anything it missed. */
  function renderSuggestions(suggestions) {
    $("suggestions").replaceChildren(
      ...suggestions.map((s) =>
        el("button", {
          type: "button",
          class: "suggestion",
          "aria-pressed": "false",
          "data-food-id": s.food_id,
          onclick: () => (onPlate(s.food_id) ? removeFood(s.food_id) : addFood(s)),   // tap again to take it off
        }, el("span", { class: "name" }, s.name), el("span", { class: "pct" }, formatPercent(s.confidence)))
      ),
      el("button", { type: "button", class: "suggestion suggestion-add", onclick: focusSearch },
        el("span", { class: "name" }, "+ Add a food"))
    );
  }

  /* The search box sits right under the suggestions: bring it into view and type straight away. */
  function focusSearch() {
    const search = $("food-search");
    search.scrollIntoView({ behavior: "smooth", block: "center" });
    search.focus({ preventScroll: true });
  }

  /* ------------------------------------------------------------ step 2: the plate (one or more foods) */

  function onPlate(foodId) {
    return state.plate.some((item) => item.food.id === foodId);
  }

  /* Suggestions use food_id, food lists use id: keep only what the plate needs. */
  function plateFood(food) {
    return { id: food.food_id ?? food.id, name: food.name, serving_unit: food.serving_unit, serving_grams: food.serving_grams };
  }

  function addFood(food) {
    const entry = plateFood(food);
    $("food-search").value = "";
    $("search-results").replaceChildren();
    clearAlert($("confirm-alert"));
    if (onPlate(entry.id)) {                             // already there: just show it
      renderPlate();
      return;
    }
    if (state.plate.length >= MAX_PLATE_ITEMS) {
      showAlert($("confirm-alert"), `You can add up to ${MAX_PLATE_ITEMS} foods at once. Save these, then add the rest.`, "warning");
      return;
    }
    state.plate.push({ key: ++plateKey, food: entry, quantity: 1, grams: "" });
    renderPlate();
  }

  function removeFood(foodId) {
    state.plate = state.plate.filter((item) => item.food.id !== foodId);
    clearAlert($("confirm-alert"));
    renderPlate();
  }

  function renderPlate() {
    const count = state.plate.length;
    $("plate-items").replaceChildren(...state.plate.map(buildPlateItem));
    $("plate-empty").hidden = count > 0;
    $("plate-count").textContent = count > 1 ? `${count} foods` : "";
    $("btn-calculate").disabled = count === 0;
    $("btn-calculate").textContent = count > 1 ? `Calculate Calories (${count} foods)` : "Calculate Calories";
    for (const button of $("suggestions").querySelectorAll("[data-food-id]")) {
      button.setAttribute("aria-pressed", String(onPlate(Number(button.dataset.foodId))));
    }
  }

  /* {grams} when the user typed a weight, otherwise {quantity} in servings. */
  function portionOf(item) {
    return item.grams !== "" ? { grams: Number(item.grams) } : { quantity: Number(item.quantity) };
  }

  /* One card on the plate: name, quick portions, a − / + stepper and an optional weight in grams. */
  function buildPlateItem(item) {
    const { food } = item;
    const id = `plate-${item.key}`;
    const total = el("span", { class: "text-secondary" });
    const quantity = el("input", {
      id: `${id}-qty`, type: "number", inputmode: "decimal", class: "form-control", min: "0.25", max: "20",
      step: "0.25", value: String(item.quantity), "aria-label": `Servings of ${food.name}`,
    });
    const grams = el("input", {
      id: `${id}-grams`, type: "number", inputmode: "decimal", class: "form-control grams-input", min: "1",
      max: "3000", step: "1", placeholder: "optional", value: item.grams,
    });
    const quick = QUICK_PORTIONS.map((amount) =>
      el("button", { type: "button", class: "btn btn-outline-secondary", "data-quantity": amount,
        onclick: () => setQuantity(amount) }, formatQuantity(amount)));

    function refresh() {
      const portion = portionOf(item);
      for (const button of quick) {
        const active = portion.quantity === Number(button.dataset.quantity);
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      }
      total.textContent = portion.quantity > 0
        ? `= ${formatGrams(Math.round(portion.quantity * food.serving_grams * 10) / 10)} g`
        : "";
    }

    function setQuantity(amount) {
      item.quantity = amount;
      item.grams = "";
      quantity.value = amount;
      grams.value = "";
      refresh();
    }

    quantity.addEventListener("input", () => {
      item.quantity = Number(quantity.value);
      item.grams = "";
      grams.value = "";
      refresh();
    });
    grams.addEventListener("input", () => {
      item.grams = grams.value.trim();
      refresh();
    });
    const step = (delta) => setQuantity(Math.min(20, Math.max(0.25, (Number(item.quantity) || 1) + delta)));

    const card = el("li", { class: "plate-item" },
      el("div", { class: "plate-item-head" },
        el("div", { class: "plate-item-name" },
          el("div", { class: "fw-semibold" }, food.name),
          el("div", { class: "small text-secondary" }, `1 ${food.serving_unit} = ${formatGrams(food.serving_grams)} g`)),
        el("button", { type: "button", class: "btn btn-outline-secondary btn-sm", "aria-label": `Remove ${food.name}`,
          onclick: () => removeFood(food.id) }, "Remove")),
      el("div", { class: "portion-grid", role: "group", "aria-label": `Quick portions for ${food.name}` }, ...quick),
      el("div", { class: "d-flex flex-wrap gap-2 align-items-center mt-2" },
        el("div", { class: "input-group qty-group" },
          el("button", { type: "button", class: "btn btn-outline-secondary", "aria-label": `Fewer servings of ${food.name}`,
            onclick: () => step(-0.25) }, "−"),
          quantity,
          el("button", { type: "button", class: "btn btn-outline-secondary", "aria-label": `More servings of ${food.name}`,
            onclick: () => step(0.25) }, "+")),
        total),
      el("div", { class: "grams-row" },
        el("label", { class: "small text-secondary", for: `${id}-grams` }, "Or the exact weight in grams"),
        grams));
    refresh();
    return card;
  }

  /* Search the whole food list. A counter drops answers that arrive out of order. */
  let searchTimer = null;
  let searchTicket = 0;
  function onSearchInput() {
    clearTimeout(searchTimer);
    const query = $("food-search").value.trim();
    if (!query) {
      searchTicket++;                                    // ignore any answer still on its way
      $("search-results").replaceChildren();
      return;
    }
    searchTimer = setTimeout(async () => {
      const ticket = ++searchTicket;
      try {
        const data = await api("GET", `/api/foods?q=${encodeURIComponent(query)}`);
        if (ticket === searchTicket) renderSearchResults(data.foods, query);
      } catch (error) {
        showAlert($("confirm-alert"), error.message);
      }
    }, 200);
  }

  function renderSearchResults(foods, query) {
    const create = el("button", { type: "button", class: "list-group-item list-group-item-action create-food",
      onclick: () => openNewFood(query) },
      el("span", { class: "fw-semibold" }, `+ Create "${query}" as a new food`),
      el("span", { class: "small text-secondary" }, "Enter its nutrition values here; it goes straight on your plate"));
    const header = foods.length ? null : el("div", { class: "list-group-item text-secondary" }, `No food called "${query}".`);
    $("search-results").replaceChildren(...(header ? [header] : []), ...foods.map((food) =>
      el("button", { type: "button", class: "list-group-item list-group-item-action", onclick: () => addFood(food) },
        el("span", { class: "fw-semibold" }, food.name),
        el("span", { class: "small text-secondary" },
          `1 ${food.serving_unit} = ${formatGrams(food.serving_grams)} g · ${formatNumber(food.calories_per_100g)} kcal per 100 g`))
    ), create);
  }

  /* ------------------------------------------------------------ step 2: create a missing food without leaving the page */

  let newFoodModal = null;

  function openNewFood(name = "") {
    const form = $("new-food-form");
    form.reset();
    $("nf-name").value = name;
    clearAlert($("new-food-alert"));
    newFoodModal = newFoodModal || bootstrap.Modal.getOrCreateInstance($("new-food-modal"));
    $("new-food-modal").addEventListener("shown.bs.modal", () => $(name ? "nf-grams" : "nf-name").focus(), { once: true });
    newFoodModal.show();
  }

  /* POST /api/foods checks every value and answers with all the problems at once, shown as a list. */
  async function saveNewFood(event) {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.target).entries());
    $("new-food-save").disabled = true;
    clearAlert($("new-food-alert"));
    try {
      const { food } = await api("POST", "/api/foods", body);
      newFoodModal.hide();
      addFood(food);
      showAlert($("confirm-alert"), `${food.name} was added to the food database and to your plate.`, "success");
    } catch (error) {
      const problems = (error.data && error.data.errors) || [error.message];
      $("new-food-alert").replaceChildren(el("div", { class: "alert alert-danger mb-0", role: "alert" },
        el("ul", { class: "mb-0 ps-3" }, ...problems.map((p) => el("li", {}, p)))));
    } finally {
      $("new-food-save").disabled = false;
    }
  }

  /* Ask the server for every food on the plate (in parallel). The server's numbers are the ones shown and saved. */
  async function calculate() {
    clearAlert($("confirm-alert"));
    if (!state.plate.length) return;
    const button = $("btn-calculate");
    button.disabled = true;
    try {
      state.calculated = await Promise.all(state.plate.map(async (item) => {
        const portion = portionOf(item);
        try {
          const result = await api("POST", "/api/calculate", { food_id: item.food.id, ...portion });
          return { food_id: item.food.id, portion, result };
        } catch (error) {
          error.message = `${item.food.name}: ${error.message}`;    // say which food has the problem
          throw error;
        }
      }));
      showResult(state.calculated.map((entry) => entry.result));
    } catch (error) {
      showAlert($("confirm-alert"), error.message);
    } finally {
      button.disabled = state.plate.length === 0;
    }
  }

  /* ------------------------------------------------------------ step 3: result and save */

  function confidenceNote(foodId) {
    const prediction = state.prediction;
    if (!prediction) return "Chosen by you (no photo)";
    const top = prediction.top_predictions[0];
    if (prediction.is_food && top && top.food_id === foodId) {
      return `AI suggestion, ${LEVEL_TEXT[prediction.confidence_level].toLowerCase()} (${formatPercent(top.confidence)})`;
    }
    return top && prediction.is_food ? `Chosen by you (the AI suggested ${top.name})` : "Chosen by you";
  }

  function showResult(results) {
    const sum = (key) => results.reduce((total, result) => total + result[key], 0);
    $("result-calories").textContent = formatNumber(sum("calories"));
    for (const key of ["protein", "carbs", "fat", "fiber"]) {
      $(`result-${key}`).textContent = formatNumber(Math.round(sum(key) * 10) / 10, 1);
    }

    if (results.length === 1) {
      const [result] = results;
      $("result-food").textContent = result.food.name;
      $("result-serving").textContent = portionText(result.quantity, result.food.serving_unit, result.grams);
      $("result-confidence").textContent = confidenceNote(result.food.id);
      $("result-items").hidden = true;
      $("result-items").replaceChildren();
    } else {
      $("result-food").textContent = `${results.length} foods`;
      $("result-serving").textContent = `${formatGrams(Math.round(sum("grams") * 10) / 10)} g in total`;
      $("result-confidence").textContent = state.prediction ? "From your photo" : "Chosen by you (no photo)";
      $("result-items").replaceChildren(...results.map((result) =>
        el("li", { class: "result-item" },
          el("div", { class: "meal-info" },
            el("div", { class: "meal-name" }, result.food.name),
            el("div", { class: "small text-secondary" }, portionText(result.quantity, result.food.serving_unit, result.grams))),
          el("div", { class: "meal-kcal" }, `${formatNumber(result.calories)} kcal`))));
      $("result-items").hidden = false;
    }
    clearAlert($("result-alert"));
    $("today-progress").hidden = true;
    $("before-save").hidden = false;
    $("after-save").hidden = true;
    $("btn-save").disabled = false;
    showStep("result");
  }

  /* The "calories today" bar shown after a meal is saved. */
  function showTodayProgress(today) {
    const percent = today.goal ? Math.round((100 * today.consumed) / today.goal) : 0;
    const over = today.remaining < 0;
    $("today-meter").classList.toggle("over", over);
    $("today-meter").setAttribute("aria-valuenow", String(percent));
    $("today-meter-fill").style.width = `${Math.min(percent, 100)}%`;
    const left = over
      ? `${formatNumber(-today.remaining)} kcal over your goal`
      : `${formatNumber(today.remaining)} kcal left`;
    const text = $("today-text");
    text.className = over ? "small mt-1 over-text" : "small mt-1";
    text.textContent = `Today: ${formatNumber(today.consumed)} of ${formatNumber(today.goal)} kcal · ${left}`;
    $("today-progress").hidden = false;
  }

  /* Every food is saved in one request: either all of them are stored or none is. */
  async function save() {
    $("btn-save").disabled = true;
    const body = {
      meal_type: $("meal-type").value,
      items: state.calculated.map((entry) => ({ food_id: entry.food_id, ...entry.portion })),
    };
    if (state.prediction) body.prediction_id = state.prediction.prediction_id;
    try {
      const data = await api("POST", "/api/food-log/batch", body);
      const count = data.log_ids.length;
      showAlert($("result-alert"), count > 1 ? `Saved ${count} foods to today's log.` : "Saved to today's log.", "success");
      showTodayProgress(data.today);
      $("before-save").hidden = true;
      $("after-save").hidden = false;
      $("btn-another").textContent = state.prediction ? "Add more from this photo" : "Log another food";
    } catch (error) {
      showAlert($("result-alert"), friendlyError(error));
      $("btn-save").disabled = false;
    }
  }

  function startOver() {
    state.prediction = null;
    state.plate = [];
    state.calculated = [];
    releasePending();
    clearAlert($("capture-alert"));
    showStep("capture");
    loadRecent();
  }

  /* ------------------------------------------------------------ wiring */

  $("btn-camera").addEventListener("click", openCamera);
  $("btn-upload").addEventListener("click", () => $("file-input").click());
  $("camera-input").addEventListener("change", (event) => pickedFile(event.target, "camera-app"));
  $("file-input").addEventListener("change", (event) => pickedFile(event.target, "upload"));
  $("link-manual").addEventListener("click", (event) => {
    event.preventDefault();
    showConfirm(null);
  });

  $("camera-shutter").addEventListener("click", takeSnapshot);
  $("camera-close").addEventListener("click", closeCamera);
  $("camera-flip").addEventListener("click", flipCamera);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("camera-overlay").hidden) closeCamera();
  });
  document.addEventListener("visibilitychange", () => {     // never leave the camera on in the background
    if (document.hidden && !$("camera-overlay").hidden) closeCamera();
  });
  window.addEventListener("pagehide", stopStream);

  $("btn-use-photo").addEventListener("click", usePhoto);
  $("btn-retake").addEventListener("click", openCamera);
  $("btn-change").addEventListener("click", () => $("file-input").click());

  const dropZone = $("drop-zone");
  dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
    if ($("btn-upload").disabled) return;                // model not ready yet
    showPreview(event.dataTransfer.files[0], "upload");
  });

  $("food-search").addEventListener("input", onSearchInput);
  $("btn-new-food").addEventListener("click", () => openNewFood($("food-search").value.trim()));
  $("new-food-form").addEventListener("submit", saveNewFood);
  $("btn-calculate").addEventListener("click", calculate);
  $("btn-save").addEventListener("click", save);

  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "start-over") startOver();
    if (action === "back-to-confirm") showStep("confirm");
    if (action === "another-item") showConfirm(state.prediction, { keepMeal: true });
  });

  setPhotoButtons(false);
  watchModel();
  loadRecent();
})();
