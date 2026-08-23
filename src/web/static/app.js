(() => {
  "use strict";

  const telegram = window.Telegram?.WebApp;
  const initData = telegram?.initData || "";
  const state = { dashboard: null, deletion: null };
  const elements = {
    summary: document.querySelector("#summary"),
    properties: document.querySelector("#properties"),
    refresh: document.querySelector("#refresh-button"),
    addProperty: document.querySelector("#add-property-button"),
    propertyDialog: document.querySelector("#property-dialog"),
    propertyForm: document.querySelector("#property-form"),
    meterDialog: document.querySelector("#meter-dialog"),
    meterForm: document.querySelector("#meter-form"),
    meterProperty: document.querySelector("#meter-property"),
    deleteDialog: document.querySelector("#delete-dialog"),
    deleteForm: document.querySelector("#delete-form"),
    deleteTitle: document.querySelector("#delete-title"),
    deleteDescription: document.querySelector("#delete-description"),
    toastRegion: document.querySelector("#toast-region"),
    greeting: document.querySelector("#greeting"),
  };
  const labels = {
    cold_water: { title: "Холодная вода", icon: "●" },
    hot_water: { title: "Горячая вода", icon: "●" },
    electricity: { title: "Электричество", icon: "ϟ" },
  };

  function setupTelegram() {
    if (!telegram) return;
    telegram.ready();
    telegram.expand();
    telegram.setHeaderColor("secondary_bg_color");
    telegram.setBackgroundColor("secondary_bg_color");
    const firstName = telegram.initDataUnsafe?.user?.first_name;
    if (firstName) elements.greeting.textContent = `Добрый день, ${firstName}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function decimal(value) {
    if (value === null || value === undefined) return "—";
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return escapeHtml(value);
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 6 }).format(parsed);
  }

  function dateLabel(value) {
    if (!value) return "Показаний пока нет";
    return new Intl.DateTimeFormat("ru-RU", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(value));
  }

  function unitLabel(unit) {
    return unit === "kwh" ? "кВт·ч" : "м³";
  }

  function plural(value, one, few, many) {
    const tens = value % 100;
    const units = value % 10;
    if (tens >= 11 && tens <= 19) return many;
    if (units === 1) return one;
    if (units >= 2 && units <= 4) return few;
    return many;
  }

  async function api(path, options = {}) {
    if (!initData) throw new Error("Откройте приложение кнопкой внутри Telegram-бота.");
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": initData,
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      const message = (await response.text()) || `Ошибка ${response.status}`;
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  }

  function renderSummary(summary) {
    const cards = [
      ["⌂", summary.property_count, "Объектов"],
      ["◉", summary.meter_count, "Счётчиков"],
      ["✓", summary.meters_with_readings, "С показаниями"],
      ["!", summary.meters_needing_reading, "Ждут показаний", "attention"],
    ];
    elements.summary.innerHTML = cards.map(([icon, value, label, className = ""]) => `
      <article class="summary-card ${className}">
        <span class="summary-icon" aria-hidden="true">${icon}</span>
        <strong>${value}</strong>
        <span>${label}</span>
      </article>
    `).join("");
  }

  function meterTemplate(meter) {
    const resource = labels[meter.type] || { title: meter.type, icon: "●" };
    const serial = meter.serial_number
      ? `№ ${escapeHtml(meter.serial_number)}`
      : "Номер не привязан";
    const reading = meter.latest_value === null
      ? "—"
      : `${decimal(meter.latest_value)} ${unitLabel(meter.unit)}`;
    const consumption = meter.consumption === null
      ? ""
      : `<span class="consumption">+${decimal(meter.consumption)} ${unitLabel(meter.unit)}</span>`;
    return `
      <div class="meter-row">
        <span class="meter-icon ${escapeHtml(meter.type)}" aria-hidden="true">${resource.icon}</span>
        <div class="meter-main">
          <div class="meter-topline">
            <span class="meter-name">${escapeHtml(meter.name)}</span>
            <span class="status-dot ${meter.needs_reading ? "needs-reading" : ""}">
              ${meter.needs_reading ? "Нужно передать" : "Актуально"}
            </span>
          </div>
          <p class="meter-meta">${escapeHtml(resource.title)} · ${serial} · ${dateLabel(meter.latest_captured_at)}</p>
          <div class="meter-reading">
            <strong>${reading}</strong>
            ${consumption}
          </div>
        </div>
        <button class="delete-meter" type="button" data-action="delete-meter"
          data-id="${meter.id}" data-name="${escapeHtml(meter.name)}" aria-label="Удалить счётчик">×</button>
      </div>
    `;
  }

  function propertyTemplate(property) {
    const meterCount = property.meters.length;
    const meterRows = meterCount
      ? `<div class="meter-list">${property.meters.map(meterTemplate).join("")}</div>`
      : `<div class="no-meters">Счётчиков пока нет. Добавьте первый прибор.</div>`;
    return `
      <article class="property-card">
        <header class="property-header">
          <span class="property-icon" aria-hidden="true">⌂</span>
          <div class="property-title">
            <h3>${escapeHtml(property.name)}</h3>
            <p>${escapeHtml(property.address || "Адрес не указан")}</p>
          </div>
          <button class="more-button" type="button" data-action="delete-property"
            data-id="${property.id}" data-name="${escapeHtml(property.name)}"
            data-meter-count="${meterCount}" aria-label="Удалить объект">×</button>
        </header>
        ${meterRows}
        <footer class="property-footer">
          <small>${meterCount} ${plural(meterCount, "счётчик", "счётчика", "счётчиков")}</small>
          <button class="text-button" type="button" data-action="add-meter"
            data-property-id="${property.id}">＋ Добавить счётчик</button>
        </footer>
      </article>
    `;
  }

  function renderProperties(properties) {
    if (!properties.length) {
      const template = document.querySelector("#empty-template");
      elements.properties.replaceChildren(template.content.cloneNode(true));
      return;
    }
    elements.properties.innerHTML = properties.map(propertyTemplate).join("");
  }

  function populatePropertySelect(selectedId = null) {
    const properties = state.dashboard?.properties || [];
    elements.meterProperty.innerHTML = properties.map((property) => `
      <option value="${property.id}" ${property.id === selectedId ? "selected" : ""}>
        ${escapeHtml(property.name)}
      </option>
    `).join("");
  }

  async function loadDashboard({ quiet = false } = {}) {
    elements.refresh.classList.add("is-loading");
    elements.refresh.disabled = true;
    try {
      const dashboard = await api("/api/v1/dashboard");
      state.dashboard = dashboard;
      renderSummary(dashboard.summary);
      renderProperties(dashboard.properties);
      populatePropertySelect();
      if (!quiet) telegram?.HapticFeedback?.notificationOccurred("success");
    } catch (error) {
      elements.properties.innerHTML = `
        <div class="error-state">
          <div class="empty-icon" aria-hidden="true">!</div>
          <h3>Не удалось загрузить данные</h3>
          <p>${escapeHtml(error.message)}</p>
          <button class="primary-button" type="button" data-action="retry">Повторить</button>
        </div>
      `;
      if (!quiet) showToast(error.message, true);
    } finally {
      elements.refresh.classList.remove("is-loading");
      elements.refresh.disabled = false;
    }
  }

  function openDialog(dialog) {
    telegram?.HapticFeedback?.selectionChanged();
    dialog.showModal();
    dialog.querySelector("input, select")?.focus();
  }

  function closeDialog(dialog) {
    dialog.close();
  }

  function showToast(message, isError = false) {
    const toast = document.createElement("div");
    toast.className = `toast${isError ? " error" : ""}`;
    toast.textContent = message;
    elements.toastRegion.replaceChildren(toast);
    window.setTimeout(() => toast.remove(), 3200);
  }

  function setSubmitting(form, submitting) {
    for (const control of form.elements) control.disabled = submitting;
  }

  async function submitProperty(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setSubmitting(form, true);
    try {
      await api("/api/v1/properties", {
        method: "POST",
        body: JSON.stringify({
          name: data.get("name"),
          address: data.get("address") || null,
        }),
      });
      closeDialog(elements.propertyDialog);
      form.reset();
      showToast("Объект добавлен");
      await loadDashboard({ quiet: true });
    } catch (error) {
      showToast(error.message, true);
    } finally {
      setSubmitting(form, false);
    }
  }

  async function submitMeter(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setSubmitting(form, true);
    try {
      await api("/api/v1/meters", {
        method: "POST",
        body: JSON.stringify({
          property_id: data.get("property_id"),
          name: data.get("name"),
          type: data.get("type"),
          serial_number: data.get("serial_number") || null,
        }),
      });
      closeDialog(elements.meterDialog);
      form.reset();
      showToast("Счётчик добавлен");
      await loadDashboard({ quiet: true });
    } catch (error) {
      showToast(error.message, true);
    } finally {
      setSubmitting(form, false);
    }
  }

  function askDelete(type, id, name, meterCount = 0) {
    state.deletion = { type, id };
    if (type === "property") {
      elements.deleteTitle.textContent = `Удалить «${name}»?`;
      elements.deleteDescription.textContent = meterCount
        ? `Будут удалены ${meterCount} ${plural(meterCount, "счётчик", "счётчика", "счётчиков")}, все показания, начисления и фотографии. Это действие нельзя отменить.`
        : "Объект будет удалён без возможности восстановления.";
    } else {
      elements.deleteTitle.textContent = `Удалить счётчик «${name}»?`;
      elements.deleteDescription.textContent = "Все его показания, начисления и фотографии будут удалены без возможности восстановления.";
    }
    openDialog(elements.deleteDialog);
  }

  async function confirmDelete(event) {
    event.preventDefault();
    if (!state.deletion) return;
    const form = event.currentTarget;
    setSubmitting(form, true);
    const { type, id } = state.deletion;
    const path = type === "property"
      ? `/api/v1/properties/${id}`
      : `/api/v1/meters/${id}`;
    try {
      const result = await api(path, { method: "DELETE" });
      closeDialog(elements.deleteDialog);
      state.deletion = null;
      telegram?.HapticFeedback?.notificationOccurred("success");
      showToast(result.orphaned_photo_count
        ? "Данные удалены, часть фотографий будет очищена позже"
        : "Удалено");
      await loadDashboard({ quiet: true });
    } catch (error) {
      telegram?.HapticFeedback?.notificationOccurred("error");
      showToast(error.message, true);
    } finally {
      setSubmitting(form, false);
    }
  }

  function handleAction(event) {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (action === "add-property") openDialog(elements.propertyDialog);
    if (action === "retry") loadDashboard();
    if (action === "add-meter") {
      populatePropertySelect(button.dataset.propertyId);
      openDialog(elements.meterDialog);
    }
    if (action === "delete-meter") {
      askDelete("meter", button.dataset.id, button.dataset.name);
    }
    if (action === "delete-property") {
      askDelete(
        "property",
        button.dataset.id,
        button.dataset.name,
        Number(button.dataset.meterCount),
      );
    }
  }

  function bindEvents() {
    elements.refresh.addEventListener("click", () => loadDashboard());
    elements.addProperty.addEventListener("click", () => openDialog(elements.propertyDialog));
    elements.properties.addEventListener("click", handleAction);
    elements.propertyForm.addEventListener("submit", submitProperty);
    elements.meterForm.addEventListener("submit", submitMeter);
    elements.deleteForm.addEventListener("submit", confirmDelete);
    document.addEventListener("click", (event) => {
      const close = event.target.closest(".close-dialog");
      if (close) closeDialog(close.closest("dialog"));
    });
    for (const dialog of document.querySelectorAll("dialog")) {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDialog(dialog);
      });
    }
  }

  setupTelegram();
  bindEvents();
  loadDashboard({ quiet: true });
})();
