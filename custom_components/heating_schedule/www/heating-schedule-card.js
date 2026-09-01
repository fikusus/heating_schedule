// Heating Schedule custom Lovelace card.
// Vanilla custom element — no external dependencies, works offline.

const DOMAIN = "heating_schedule";

const PHASE_LABELS = {
  day: "Day",
  transition_to_night: "→ Night",
  night: "Night",
  transition_to_day: "→ Day",
};
const PHASE_ICONS = {
  day: "☀",
  transition_to_night: "🌆",
  night: "🌙",
  transition_to_day: "🌅",
};

const STYLES = `
  :host { display: block; }
  ha-card { padding: 0; }
  .header { padding: 12px 16px 0 16px; font-size: 1.1rem; font-weight: 500; }
  .content { padding: 8px 16px 16px 16px; }

  .phase-row {
    display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 8px 0 4px;
  }
  .phase-card {
    background: var(--secondary-background-color);
    border-radius: 12px; padding: 12px; text-align: center;
  }
  .phase-label { font-size: 0.85rem; color: var(--secondary-text-color); }
  .phase-value { font-size: 1.05rem; font-weight: 500; margin-top: 4px; }
  .phase-target {
    font-size: 1.6rem; font-weight: 600; margin-top: 4px;
    color: var(--primary-text-color);
  }

  .section-title {
    font-size: 0.85rem; text-transform: uppercase;
    letter-spacing: 0.05em; color: var(--secondary-text-color);
    margin: 16px 0 8px;
  }

  .number-grid, .time-grid {
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px;
  }
  .number-tile {
    background: var(--secondary-background-color);
    border-radius: 12px; padding: 10px;
  }
  .number-tile-label {
    font-size: 0.85rem; color: var(--secondary-text-color); margin-bottom: 6px;
  }
  .number-tile-row {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
  }
  .number-tile-value {
    font-size: 1.4rem; font-weight: 600; flex: 1; text-align: center;
  }
  .unit { font-size: 0.85rem; color: var(--secondary-text-color); margin-left: 2px; }
  .step {
    width: 36px; height: 36px; border-radius: 50%; border: none;
    background: var(--card-background-color); color: var(--primary-text-color);
    font-size: 1.4rem; cursor: pointer; line-height: 1;
  }
  .step:hover { background: var(--divider-color); }

  .time-tile {
    background: var(--secondary-background-color);
    border-radius: 12px; padding: 10px;
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
  }
  .time-tile-label { font-size: 0.9rem; color: var(--primary-text-color); }
  .time-input {
    font-size: 1rem; padding: 4px 8px;
    border: 1px solid var(--divider-color); border-radius: 8px;
    background: var(--card-background-color); color: var(--primary-text-color);
  }

  .device-list { display: flex; flex-direction: column; gap: 6px; }
  .device-row {
    display: grid; grid-template-columns: 1fr 2fr auto;
    align-items: center; gap: 10px; padding: 8px 10px;
    background: var(--secondary-background-color); border-radius: 10px;
  }
  .device-info { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .device-name {
    font-size: 0.95rem; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis;
  }
  .badge {
    font-size: 0.7rem; padding: 2px 6px; border-radius: 999px;
    background: var(--primary-color); color: var(--text-primary-color, white);
  }
  .device-slider { width: 100%; accent-color: var(--primary-color); }
  .device-value {
    font-variant-numeric: tabular-nums; font-weight: 600;
    min-width: 4ch; text-align: right;
  }

  .empty { color: var(--secondary-text-color); padding: 16px; }

  .boiler-row {
    display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
  }
  .boiler-stat {
    background: var(--secondary-background-color);
    border-radius: 12px; padding: 10px; text-align: center;
  }
  .boiler-stat-label {
    font-size: 0.85rem; color: var(--secondary-text-color);
  }
  .boiler-stat-value {
    font-size: 1.4rem; font-weight: 600; margin-top: 4px;
  }
  .boiler-toggles {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 8px; margin-top: 8px;
  }
  .toggle {
    display: flex; align-items: center; justify-content: center; gap: 8px;
    padding: 10px; border-radius: 12px; border: none; cursor: pointer;
    font-size: 1rem; font-weight: 500;
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
  }
  .toggle.on {
    background: var(--primary-color);
    color: var(--text-primary-color, white);
  }
  .toggle-icon { font-size: 1.2rem; }

  @media (max-width: 480px) {
    .number-grid, .time-grid { grid-template-columns: 1fr; }
    .device-row { grid-template-columns: 1fr; }
    .boiler-row, .boiler-toggles { grid-template-columns: 1fr; }
  }
`;

class HeatingScheduleCard extends HTMLElement {
  constructor() {
    super();
    this._root = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = STYLES;
    this._root.appendChild(style);
    this._wrapper = document.createElement("ha-card");
    this._root.appendChild(this._wrapper);
    this._content = document.createElement("div");
    this._content.className = "content";
    this._wrapper.appendChild(this._content);
    this._lastSig = "";
  }

  setConfig(config) {
    this._config = config || {};
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return 6;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  // -------------------------------------------------------------- discovery

  _index() {
    const entities = (this._hass && this._hass.entities) || {};
    const byKey = {};
    const offsets = [];
    for (const e of Object.values(entities)) {
      if (e.platform !== DOMAIN) continue;
      const state = this._hass.states[e.entity_id];
      if (state && state.attributes && state.attributes.target_entity) {
        offsets.push(e);
      } else if (e.translation_key) {
        byKey[e.translation_key] = e;
      }
    }
    offsets.sort((a, b) => a.entity_id.localeCompare(b.entity_id));
    return { byKey, offsets };
  }

  _toggle(entityId, on) {
    if (!entityId) return;
    this._hass.callService("switch", on ? "turn_on" : "turn_off", {
      entity_id: entityId,
    });
  }

  _state(entityId) {
    return entityId ? this._hass.states[entityId] : undefined;
  }

  _formatNumber(state, decimals = 1) {
    if (!state) return "—";
    const n = parseFloat(state.state);
    return isNaN(n) ? state.state : n.toFixed(decimals);
  }

  _formatPhase(state) {
    if (!state) return "—";
    const ic = PHASE_ICONS[state.state] || "";
    const lb = PHASE_LABELS[state.state] || state.state;
    return `${ic} ${lb}`;
  }

  // -------------------------------------------------------------- services

  _setNumber(entityId, value) {
    if (!entityId || value === "" || value == null || isNaN(value)) return;
    this._hass.callService("number", "set_value", {
      entity_id: entityId,
      value: Number(value),
    });
  }

  _setTime(entityId, value) {
    if (!entityId || !value) return;
    const v = value.length === 5 ? `${value}:00` : value;
    this._hass.callService("time", "set_value", {
      entity_id: entityId,
      time: v,
    });
  }

  // -------------------------------------------------------------- render

  _render() {
    if (!this._hass) {
      this._content.innerHTML = `<div class="empty">Loading…</div>`;
      this._wrapper.header = "Heating Schedule";
      return;
    }

    const { byKey, offsets } = this._index();
    this._wrapper.header = "Heating Schedule";

    if (Object.keys(byKey).length === 0 && offsets.length === 0) {
      this._content.innerHTML =
        `<div class="empty">Heating Schedule integration not detected. ` +
        `Add it via Settings → Integrations.</div>`;
      return;
    }

    const phaseMain = this._state(byKey.current_main_phase?.entity_id);
    const phaseBed = this._state(byKey.current_bedroom_phase?.entity_id);
    const targetMain = this._state(byKey.current_main_target?.entity_id);
    const targetBed = this._state(byKey.current_bedroom_target?.entity_id);

    const html = [];
    html.push(`<div class="phase-row">`);
    html.push(this._phaseCardHtml("Main", phaseMain, targetMain));
    html.push(this._phaseCardHtml("Bedroom", phaseBed, targetBed));
    html.push(`</div>`);

    html.push(`<div class="section-title">Temperatures</div>`);
    html.push(`<div class="number-grid">`);
    html.push(this._numberTileHtml(byKey.day_temp, "Day", "☀", "°C", 1));
    html.push(this._numberTileHtml(byKey.night_temp, "Night", "🌙", "°C", 1));
    html.push(
      this._numberTileHtml(byKey.bedroom_night_temp, "Bed Night", "🛏", "°C", 1)
    );
    html.push(
      this._numberTileHtml(
        byKey.transition_duration_min,
        "Transition",
        "⏱",
        "min",
        0
      )
    );
    html.push(`</div>`);

    html.push(`<div class="section-title">Schedule</div>`);
    html.push(`<div class="time-grid">`);
    html.push(this._timeTileHtml(byKey.day_to_night_time, "Day → Night"));
    html.push(this._timeTileHtml(byKey.night_to_day_time, "Night → Day"));
    html.push(
      this._timeTileHtml(byKey.bedroom_day_to_night_time, "Bed Day → Night")
    );
    html.push(
      this._timeTileHtml(byKey.bedroom_night_to_day_time, "Bed Night → Day")
    );
    html.push(`</div>`);

    if (offsets.length > 0) {
      html.push(`<div class="section-title">Devices</div>`);
      html.push(`<div class="device-list">`);
      for (const off of offsets) html.push(this._deviceRowHtml(off));
      html.push(`</div>`);
    }

    const boilerEnabled = byKey.boiler_enabled;
    const boilerSummer = byKey.boiler_summer_mode;
    const boilerKeepOn = byKey.boiler_keep_on;
    const boilerMaxDiff = byKey.boiler_max_diff;
    const boilerPower = byKey.boiler_power_target;
    if (boilerEnabled || boilerSummer || boilerKeepOn || boilerMaxDiff || boilerPower) {
      html.push(`<div class="section-title">Boiler</div>`);
      html.push(`<div class="boiler-row">`);
      html.push(this._boilerStatHtml("Max diff",
        boilerMaxDiff && this._state(boilerMaxDiff.entity_id), "°C"));
      html.push(this._boilerStatHtml("Power",
        boilerPower && this._state(boilerPower.entity_id), "%"));
      html.push(`</div>`);
      html.push(`<div class="boiler-toggles">`);
      if (boilerEnabled)
        html.push(this._toggleHtml(boilerEnabled, "Control", "🔥"));
      if (boilerSummer)
        html.push(this._toggleHtml(boilerSummer, "Summer", "☀"));
      if (boilerKeepOn)
        html.push(this._toggleHtml(boilerKeepOn, "Keep on", "🔁"));
      html.push(`</div>`);
    }

    this._content.innerHTML = html.join("");
    this._wireHandlers();
  }

  _boilerStatHtml(label, state, unit) {
    const value =
      state && state.state !== "unknown" && state.state !== "unavailable"
        ? state.state
        : "—";
    return `
      <div class="boiler-stat">
        <div class="boiler-stat-label">${escapeHtml(label)}</div>
        <div class="boiler-stat-value">${escapeHtml(value)}<span class="unit">${escapeHtml(unit)}</span></div>
      </div>`;
  }

  _toggleHtml(reg, label, icon) {
    const state = this._state(reg.entity_id);
    const isOn = state && state.state === "on";
    return `
      <button class="toggle ${isOn ? "on" : "off"}"
        data-eid="${escapeAttr(reg.entity_id)}"
        data-on="${isOn ? "1" : "0"}">
        <span class="toggle-icon">${escapeHtml(icon)}</span>
        <span class="toggle-label">${escapeHtml(label)}</span>
      </button>`;
  }

  _phaseCardHtml(label, phaseState, targetState) {
    return `
      <div class="phase-card">
        <div class="phase-label">${label}</div>
        <div class="phase-value">${escapeHtml(this._formatPhase(phaseState))}</div>
        <div class="phase-target">${this._formatNumber(targetState)} °C</div>
      </div>`;
  }

  _numberTileHtml(reg, label, icon, unit, decimals) {
    if (!reg) return "";
    const state = this._state(reg.entity_id);
    if (!state) return "";
    const value = parseFloat(state.state);
    const display = isNaN(value) ? "—" : value.toFixed(decimals);
    return `
      <div class="number-tile" data-eid="${escapeAttr(reg.entity_id)}">
        <div class="number-tile-label">${escapeHtml(icon)} ${escapeHtml(label)}</div>
        <div class="number-tile-row">
          <button class="step" data-action="dec">−</button>
          <span class="number-tile-value">
            ${display}<span class="unit">${escapeHtml(unit)}</span>
          </span>
          <button class="step" data-action="inc">+</button>
        </div>
      </div>`;
  }

  _timeTileHtml(reg, label) {
    if (!reg) return "";
    const state = this._state(reg.entity_id);
    if (!state) return "";
    const value = String(state.state).slice(0, 5);
    return `
      <div class="time-tile" data-eid="${escapeAttr(reg.entity_id)}">
        <div class="time-tile-label">${escapeHtml(label)}</div>
        <input class="time-input" type="time" value="${escapeAttr(value)}" />
      </div>`;
  }

  _deviceRowHtml(reg) {
    const state = this._state(reg.entity_id);
    if (!state) return "";
    const target = state.attributes.target_entity || "";
    const isBedroom = !!state.attributes.is_bedroom;
    const targetState = this._state(target);
    const targetName =
      (targetState && targetState.attributes && targetState.attributes.friendly_name) ||
      target ||
      reg.entity_id;
    const min = parseFloat(state.attributes.min);
    const max = parseFloat(state.attributes.max);
    const step = parseFloat(state.attributes.step);
    const value = parseFloat(state.state);
    const valueDisplay = isNaN(value)
      ? "—"
      : (value >= 0 ? "+" : "") + value.toFixed(1);
    return `
      <div class="device-row" data-eid="${escapeAttr(reg.entity_id)}">
        <div class="device-info">
          <span class="device-name">${escapeHtml(targetName)}</span>
          ${isBedroom ? `<span class="badge">bedroom</span>` : ""}
        </div>
        <input class="device-slider" type="range"
          min="${escapeAttr(min)}" max="${escapeAttr(max)}"
          step="${escapeAttr(step)}" value="${escapeAttr(value)}" />
        <span class="device-value">${valueDisplay} °C</span>
      </div>`;
  }

  _wireHandlers() {
    // Step buttons (number tiles)
    for (const btn of this._content.querySelectorAll(".number-tile .step")) {
      btn.addEventListener("click", (ev) => {
        const tile = ev.currentTarget.closest(".number-tile");
        const eid = tile && tile.dataset.eid;
        const state = this._state(eid);
        if (!state) return;
        const min = parseFloat(state.attributes.min);
        const max = parseFloat(state.attributes.max);
        const step = parseFloat(state.attributes.step);
        const cur = parseFloat(state.state);
        const dir = ev.currentTarget.dataset.action === "inc" ? 1 : -1;
        let next = cur + dir * step;
        if (!isNaN(min)) next = Math.max(min, next);
        if (!isNaN(max)) next = Math.min(max, next);
        next = Math.round(next * 1000) / 1000;
        this._setNumber(eid, next);
      });
    }
    // Time inputs
    for (const inp of this._content.querySelectorAll(".time-input")) {
      inp.addEventListener("change", (ev) => {
        const tile = ev.currentTarget.closest(".time-tile");
        const eid = tile && tile.dataset.eid;
        this._setTime(eid, ev.currentTarget.value);
      });
    }
    // Device sliders
    for (const slider of this._content.querySelectorAll(".device-slider")) {
      slider.addEventListener("change", (ev) => {
        const row = ev.currentTarget.closest(".device-row");
        const eid = row && row.dataset.eid;
        this._setNumber(eid, ev.currentTarget.value);
      });
    }
    // Boiler toggles
    for (const btn of this._content.querySelectorAll(".toggle")) {
      btn.addEventListener("click", (ev) => {
        const t = ev.currentTarget;
        const eid = t.dataset.eid;
        const isOn = t.dataset.on === "1";
        this._toggle(eid, !isOn);
      });
    }
  }
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
function escapeAttr(value) {
  return escapeHtml(value);
}

if (!customElements.get("heating-schedule-card")) {
  customElements.define("heating-schedule-card", HeatingScheduleCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "heating-schedule-card")) {
  window.customCards.push({
    type: "heating-schedule-card",
    name: "Heating Schedule",
    description:
      "Centralised heating schedule with smooth day/night transitions and per-device offsets.",
    preview: false,
  });
}
