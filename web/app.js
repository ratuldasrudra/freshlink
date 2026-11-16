"use strict";

const defaults = {delay_ms: 0, jitter_ms: 0, bytes_per_second: 0, loss: 0,
  duplicate: 0, reorder: 0, reorder_ms: 0, corrupt: 0, outage: false};
const presets = {
  healthy: ["Healthy", {}],
  queue: ["Queue overload", {delay_ms: 70, jitter_ms: 25, bytes_per_second: 180}],
  loss: ["UDP loss", {loss: 0.45, delay_ms: 30}],
  outage: ["Outage", {outage: true}],
};
const fields = [
  ["delay_ms", "Delay (ms)", 10000, 1], ["jitter_ms", "Jitter (ms)", 10000, 1],
  ["bytes_per_second", "Bandwidth (B/s, 0 = unlimited)", 1000000, 1],
  ["loss", "UDP loss probability", 1, 0.01], ["duplicate", "UDP duplication probability", 1, 0.01],
  ["reorder", "UDP reorder probability", 1, 0.01], ["reorder_ms", "UDP reorder delay (ms)", 10000, 1],
  ["corrupt", "UDP corruption probability", 1, 0.01],
];
const metricRows = [
  ["sequence", "Latest sequence", 0], ["stale_fraction", "Time stale (%)", 1, 100],
  ["latency_median_ms", "Delivered latency · median (ms)", 1],
  ["latency_p95_ms", "Delivered latency · p95 (ms)", 1],
  ["latency_p99_ms", "Delivered latency · p99 (ms)", 1],
  ["position_error", "Position error (rover units)", 3],
  ["useful_per_second", "Useful updates per second", 1],
  ["source_queue_delayed", "Source queue delayed (samples)", 0],
  ["source_queue_dropped", "Source queue dropped (samples)", 0],
  ["source_queue_wait_ms", "Last source queue wait (ms)", 1],
  ["relay_loss", "Emulated relay loss (datagrams)", 0],
  ["relay_overflow", "Relay overflow (copies)", 0],
];
const get = (id) => document.getElementById(id);
const form = get("settings");
const buttons = [...document.querySelectorAll("[data-preset]")];
const colors = {tcp: "#ffc078", udp: "#91e5be"};
const history = [];
let lastState;
let renderedSettings;

for (const [name, title, max, step] of fields) {
  const label = document.createElement("label");
  label.textContent = title;
  const input = document.createElement("input");
  Object.assign(input, {name, type: "number", min: 0, max, step, required: true, value: 0});
  label.append(input);
  get("fields").append(label);
}

for (const protocol of ["tcp", "udp"]) {
  const panel = document.createElement("article");
  panel.className = `panel ${protocol}`;
  panel.innerHTML = `<h2>${protocol.toUpperCase()} · ${protocol === "tcp" ? "In order" : "Latest valid update"}</h2>
    <div class="age"><span id="${protocol}-age">—</span> <small>ms information age</small></div>
    <p id="${protocol}-state" class="status">Waiting for data</p><dl></dl>`;
  const list = panel.querySelector("dl");
  for (const [key, title] of metricRows) {
    const term = document.createElement("dt");
    const value = document.createElement("dd");
    term.textContent = title;
    value.id = `${protocol}-${key}`;
    value.textContent = "—";
    list.append(term, value);
  }
  get("comparison").append(panel);
}

function render(state) {
  if (lastState && state.elapsed_seconds < lastState.elapsed_seconds) history.length = 0;
  lastState = state;
  for (const protocol of ["tcp", "udp"]) {
    const values = state[protocol];
    get(`${protocol}-age`).textContent = values.age_ms == null ? "—" : values.age_ms.toFixed(0);
    get(`${protocol}-state`).textContent = values.age_ms == null ? "Waiting for data" :
      values.age_ms > state.threshold_ms ? `STALE · above ${state.threshold_ms} ms` : "FRESH · within threshold";
    for (const [key, , digits, factor = 1] of metricRows) {
      get(`${protocol}-${key}`).textContent = values[key] == null ? "—" : (values[key] * factor).toFixed(digits);
    }
  }
  history.push([state.elapsed_seconds, state.tcp.age_ms, state.udp.age_ms]);
  while (history.length > 82 || history[0][0] < state.elapsed_seconds - 20) history.shift();
  drawPosition(state);
  drawAge(state);
  const settings = state.settings || defaults;
  const signature = JSON.stringify(Object.keys(defaults).map((key) => settings[key]));
  if (renderedSettings !== signature) {
    renderedSettings = signature;
    const active = Object.entries(presets).find(([, [, values]]) =>
      Object.keys(defaults).every((key) => settings[key] === (values[key] ?? defaults[key])));
    get("condition").textContent = `Active · ${active ? active[1][0] : "Custom"}`;
    buttons.forEach((button) => button.setAttribute("aria-pressed", button.dataset.preset === active?.[0]));
    for (const [name] of fields) form.elements[name].value = settings[name];
    form.elements.outage.checked = settings.outage;
  }
  get("connection").textContent = state.error ? `Telemetry stopped · ${state.error}` : "Live · loopback";
}

function canvas(id) {
  const element = get(id);
  const context = element.getContext("2d");
  context.clearRect(0, 0, element.width, element.height);
  context.font = "14px system-ui";
  context.fillStyle = "#c6d6e3";
  return context;
}

function line(context, x1, y1, x2, y2) {
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  context.stroke();
}

function drawPosition(state) {
  const ctx = canvas("position");
  const center = [215, 117], radius = 83;
  ctx.strokeStyle = "#71879a";
  line(ctx, 98, 117, 330, 117);
  line(ctx, 215, 12, 215, 224);
  ctx.beginPath();
  ctx.arc(...center, radius, 0, 2 * Math.PI);
  ctx.stroke();
  ctx.fillText("x (rover units)", 290, 147);
  ctx.fillText("y (rover units)", 231, 23);
  ctx.fillText("−1", 126, 139);
  ctx.fillText("+1", 285, 139);
  ctx.fillText("+1", 187, 38);
  ctx.fillText("−1", 188, 205);
  for (const [kind, point] of [["tcp", state.tcp.position], ["udp", state.udp.position], ["truth", state.truth]]) {
    if (!point) continue;
    const x = center[0] + point.x * radius, y = center[1] - point.y * radius;
    ctx.strokeStyle = colors[kind] || "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    if (kind === "tcp") ctx.rect(x - 10, y - 10, 20, 20);
    else if (kind === "udp") {
      ctx.moveTo(x, y - 14); ctx.lineTo(x + 13, y + 9); ctx.lineTo(x - 13, y + 9); ctx.closePath();
    } else ctx.arc(x, y, 4, 0, 2 * Math.PI);
    ctx.stroke();
  }
}

function drawAge(state) {
  const ctx = canvas("history");
  const left = 67, right = 550, top = 18, bottom = 213;
  const highest = Math.max(state.threshold_ms, ...history.flatMap((row) => row.slice(1).filter(Number.isFinite)));
  const max = Math.ceil(highest / 250) * 250;
  const y = (age) => bottom - (bottom - top) * age / max;
  const x = (time) => right - (right - left) * (state.elapsed_seconds - time) / 20;
  ctx.strokeStyle = "#71879a";
  line(ctx, left, top, left, bottom);
  line(ctx, left, bottom, right, bottom);
  ctx.fillText(`${max} ms`, 5, top + 5);
  ctx.fillText("0 ms", 20, bottom);
  ctx.fillText("−20 s", left, 240);
  ctx.fillText("Time (s)", 280, 240);
  ctx.fillText("Now", right - 34, 240);
  ctx.setLineDash([2, 5]);
  line(ctx, left, y(state.threshold_ms), right, y(state.threshold_ms));
  for (const [index, protocol] of ["tcp", "udp"].entries()) {
    ctx.strokeStyle = colors[protocol];
    ctx.lineWidth = 2.5;
    ctx.setLineDash(index ? [8, 5] : []);
    let started = false;
    ctx.beginPath();
    for (const row of history) {
      if (row[index + 1] == null) { started = false; continue; }
      if (started) ctx.lineTo(x(row[0]), y(row[index + 1]));
      else ctx.moveTo(x(row[0]), y(row[index + 1]));
      started = true;
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.lineWidth = 1;
}

async function apply(values, label, selection) {
  const controls = [...buttons, form.querySelector("button")];
  controls.forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch("/control", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    get("condition").textContent = `Active · ${label}`;
    buttons.forEach((button) => button.setAttribute("aria-pressed", button.dataset.preset === selection));
    for (const [name] of fields) form.elements[name].value = values[name];
    form.elements.outage.checked = values.outage;
  } catch (error) {
    get("condition").textContent = `Could not apply settings · ${error.message}`;
  } finally {
    controls.forEach((button) => { button.disabled = false; });
  }
}

buttons.forEach((button) => {
  button.setAttribute("aria-pressed", button.dataset.preset === "healthy");
  button.addEventListener("click", () => {
    const [label, values] = presets[button.dataset.preset];
    apply({...defaults, ...values}, label, button.dataset.preset);
  });
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const values = Object.fromEntries(fields.map(([name]) => [name, form.elements[name].valueAsNumber]));
  apply({...values, outage: form.elements.outage.checked}, "Custom");
});

const events = new EventSource("/events");
events.onmessage = (event) => render(JSON.parse(event.data));
events.onerror = () => { get("connection").textContent = "Disconnected · reconnecting…"; };
