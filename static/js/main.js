/*
  main.js - the Scan page.

  Flow (matches the HLD workflow):
    photo (live camera, phone camera app or file) -> preview: use / retake / change
    -> shrink in the browser -> POST /api/predict -> show top 3 + confidence
    -> user confirms or searches the food, picks the portion -> POST /api/calculate
    -> result card -> POST /api/food-log -> today's total and progress.

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

  const state = {
    prediction: null,                   // answer from /api/predict (null = no photo)
    food: null,                         // the food the user chose
    portion: null,                      // {quantity} or {grams} used for the last calculation
    recent: [],                         // foods this user logged before (quick add)
  };
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
    const chips = () => state.recent.map((food) =>
      el("button", { type: "button", class: "chip", onclick: () => quickAdd(food) }, food.name));
    $("recent-box").hidden = !state.recent.length;
    $("recent-foods").replaceChildren(...chips());
    const showHere = state.recent.length > 0 && !state.prediction && !steps.confirm.hidden;
    $("recent-confirm").hidden = !showHere;
    $("recent-confirm-foods").replaceChildren(...(showHere ? chips() : []));
  }

  function quickAdd(food) {
    showConfirm(null, { food });
  }

  /* ------------------------------------------------------------ step 2: confirm food and portion */

  function showConfirm(prediction, { keepMeal = false, food = null } = {}) {
    state.prediction = prediction;
    state.food = null;
    clearAlert($("confirm-alert"));
    $("food-search").value = "";
    $("search-results").replaceChildren();
    $("quantity").value = 1;
    $("grams").value = "";
    if (!keepMeal) $("meal-type").value = defaultMealType();   // a thali's items share one meal
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
      renderSuggestions(prediction.is_food ? prediction.top_predictions : []);
      if (level === "high") selectFood(top);
    } else {
      photo.hidden = true;
      photo.removeAttribute("src");
      $("no-photo").hidden = false;
      $("prediction-box").hidden = true;
    }
    if (food) selectFood(food);

    updateSelectedFood();
    showStep("confirm");
    renderRecent();
    const level = prediction && prediction.confidence_level;
    if (!food && (!prediction || level === "low" || level === "not_food")) $("food-search").focus({ preventScroll: true });
  }

  function renderSuggestions(suggestions) {
    $("suggestions").replaceChildren(
      ...suggestions.map((s) =>
        el("button", {
          type: "button",
          class: "suggestion",
          "aria-pressed": "false",
          "data-food-id": s.food_id,
          onclick: () => selectFood(s),
        }, el("span", { class: "name" }, s.name), el("span", { class: "pct" }, formatPercent(s.confidence)))
      )
    );
  }

  function selectFood(food) {
    state.food = {
      id: food.food_id ?? food.id,
      name: food.name,
      serving_unit: food.serving_unit,
      serving_grams: food.serving_grams,
    };
    $("food-search").value = "";
    $("search-results").replaceChildren();
    clearAlert($("confirm-alert"));
    updateSelectedFood();
  }

  function updateSelectedFood() {
    const food = state.food;
    const box = $("selected-food");
    box.textContent = food ? food.name : "Choose a food above";
    box.classList.toggle("text-secondary", !food);
    $("serving-hint").textContent = food ? `(1 ${food.serving_unit} = ${formatGrams(food.serving_grams)} g)` : "";
    $("btn-calculate").disabled = !food;
    for (const button of $("suggestions").children) {
      button.setAttribute("aria-pressed", String(Boolean(food) && Number(button.dataset.foodId) === food.id));
    }
    updatePortionTotal();
  }

  function readPortion() {
    const grams = $("grams").value.trim();
    return grams !== "" ? { grams: Number(grams) } : { quantity: Number($("quantity").value) };
  }

  function updatePortionTotal() {
    const portion = readPortion();
    for (const button of document.querySelectorAll("[data-quantity]")) {
      const active = portion.quantity === Number(button.dataset.quantity);
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    }
    const text = state.food && portion.quantity > 0
      ? `= ${formatGrams(Math.round(portion.quantity * state.food.serving_grams * 10) / 10)} g`
      : "";
    $("portion-total").textContent = text;
  }

  function stepQuantity(delta) {
    const current = Number($("quantity").value) || 1;
    $("quantity").value = Math.min(20, Math.max(0.25, current + delta));
    $("grams").value = "";
    updatePortionTotal();
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
    const box = $("search-results");
    if (!foods.length) {
      box.replaceChildren(el("div", { class: "list-group-item text-secondary" },
        `No food called "${query}". `, el("a", { href: "/foods#add-food" }, "Add it"), "."));
      return;
    }
    box.replaceChildren(...foods.map((food) =>
      el("button", { type: "button", class: "list-group-item list-group-item-action", onclick: () => selectFood(food) },
        el("span", { class: "fw-semibold" }, food.name),
        el("span", { class: "small text-secondary" },
          `1 ${food.serving_unit} = ${formatGrams(food.serving_grams)} g · ${formatNumber(food.calories_per_100g)} kcal per 100 g`))
    ));
  }

  async function calculate() {
    clearAlert($("confirm-alert"));
    if (!state.food) return;
    const portion = readPortion();
    try {
      const result = await api("POST", "/api/calculate", { food_id: state.food.id, ...portion });
      state.portion = portion;
      showResult(result);
    } catch (error) {
      showAlert($("confirm-alert"), error.message);
    }
  }

  /* ------------------------------------------------------------ step 3: result and save */

  function confidenceNote() {
    const prediction = state.prediction;
    if (!prediction) return "Chosen by you (no photo)";
    const top = prediction.top_predictions[0];
    if (prediction.is_food && top && top.food_id === state.food.id) {
      return `AI suggestion, ${LEVEL_TEXT[prediction.confidence_level].toLowerCase()} (${formatPercent(top.confidence)})`;
    }
    return top && prediction.is_food ? `Chosen by you (the AI suggested ${top.name})` : "Chosen by you";
  }

  function showResult(result) {
    $("result-calories").textContent = formatNumber(result.calories);
    $("result-food").textContent = result.food.name;
    $("result-serving").textContent = portionText(result.quantity, result.food.serving_unit, result.grams);
    $("result-confidence").textContent = confidenceNote();
    for (const key of ["protein", "carbs", "fat", "fiber"]) {
      $(`result-${key}`).textContent = formatNumber(result[key], 1);
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

  async function save() {
    $("btn-save").disabled = true;
    const body = { food_id: state.food.id, meal_type: $("meal-type").value, ...state.portion };
    if (state.prediction) body.prediction_id = state.prediction.prediction_id;
    try {
      const data = await api("POST", "/api/food-log", body);
      showAlert($("result-alert"), "Saved to today's log.", "success");
      showTodayProgress(data.today);
      $("before-save").hidden = true;
      $("after-save").hidden = false;
      $("btn-another").textContent = state.prediction ? "Add another item from this photo" : "Log another food";
    } catch (error) {
      showAlert($("result-alert"), friendlyError(error));
      $("btn-save").disabled = false;
    }
  }

  function startOver() {
    state.prediction = null;
    state.food = null;
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
  for (const button of document.querySelectorAll("[data-quantity]")) {
    button.addEventListener("click", () => {
      $("quantity").value = button.dataset.quantity;
      $("grams").value = "";
      updatePortionTotal();
    });
  }
  for (const button of document.querySelectorAll("[data-step]")) {
    button.addEventListener("click", () => stepQuantity(Number(button.dataset.step)));
  }
  $("quantity").addEventListener("input", () => {
    $("grams").value = "";
    updatePortionTotal();
  });
  $("grams").addEventListener("input", updatePortionTotal);
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
