const state = {
  fixtures: [],
  layout: null,
  plan: null,
  verification: null,
  processTimer: null,
};

const els = {
  fixtureSelect: document.querySelector("#fixtureSelect"),
  increaseInput: document.querySelector("#increaseInput"),
  sourceInput: document.querySelector("#sourceInput"),
  targetInput: document.querySelector("#targetInput"),
  scenarioSummary: document.querySelector("#scenarioSummary"),
  layoutMeta: document.querySelector("#layoutMeta"),
  diskMap: document.querySelector("#diskMap"),
  partitionTable: document.querySelector("#partitionTable"),
  planStatus: document.querySelector("#planStatus"),
  processQueue: document.querySelector("#processQueue"),
  processClock: document.querySelector("#processClock"),
  checksList: document.querySelector("#checksList"),
  resultSummary: document.querySelector("#resultSummary"),
  jsonOutput: document.querySelector("#jsonOutput"),
  safetyModes: document.querySelector("#safetyModes"),
  runPlanButton: document.querySelector("#runPlanButton"),
  refreshButton: document.querySelector("#refreshButton"),
  simulateButton: document.querySelector("#simulateButton"),
  verifyButton: document.querySelector("#verifyButton"),
  clearButton: document.querySelector("#clearButton"),
};

function apiGet(path) {
  return fetch(path, { headers: { Accept: "application/json" } }).then(assertJson);
}

function apiPost(path, payload) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  }).then(assertJson);
}

async function assertJson(response) {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function payload() {
  return {
    fixture: els.fixtureSelect.value,
    increase_c: els.increaseInput.value.trim() || "40G",
    source: els.sourceInput.value.trim() || "E",
    target: els.targetInput.value.trim() || "C",
  };
}

function humanBytes(value) {
  if (value === null || value === undefined) return "unknown";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = Number(value);
  for (const unit of units) {
    if (Math.abs(amount) < 1024 || unit === units[units.length - 1]) {
      return unit === "B" ? `${amount} ${unit}` : `${amount.toFixed(2)} ${unit}`;
    }
    amount /= 1024;
  }
  return `${value} B`;
}

function setStatus(element, value) {
  element.className = `status-pill ${String(value || "neutral").toLowerCase()}`;
  element.textContent = value || "Idle";
}

function setJson(data) {
  els.jsonOutput.textContent = JSON.stringify(data, null, 2);
}

function setError(error) {
  setStatus(els.planStatus, "fail");
  els.resultSummary.textContent = error.message;
  els.checksList.innerHTML = "";
  setJson({ error: error.message });
}

function partitionSize(partition, sectorSize) {
  return (partition.end_sector - partition.start_sector + 1) * sectorSize;
}

function freeRegions(layout) {
  return layout?.disk?.free_regions || [];
}

function renderLayout(layout) {
  state.layout = layout;
  const disk = layout.disk;
  const sectorSize = disk.sector_size || 512;
  els.scenarioSummary.textContent = `${layout.scenario} · ${layout.description || "Mock layout"}`;
  els.layoutMeta.textContent = `${String(disk.label || "unknown").toUpperCase()} · ${humanBytes(disk.size_bytes)} · sector size ${sectorSize}`;

  const parts = [...disk.partitions]
    .map((partition) => ({
      kind: "partition",
      ...partition,
      size_bytes: partitionSize(partition, sectorSize),
    }))
    .sort((a, b) => a.start_sector - b.start_sector);
  const free = freeRegions(layout).map((region) => ({ kind: "free", label: "Free", ...region }));
  const segments = [...parts, ...free].sort((a, b) => a.start_sector - b.start_sector);
  const totalBytes = disk.size_bytes || segments.reduce((sum, item) => sum + (item.size_bytes || 0), 0);

  els.diskMap.innerHTML = "";
  for (const segment of segments) {
    const size = segment.size_bytes || partitionSize(segment, sectorSize);
    const width = Math.max(8, (size / totalBytes) * 100);
    const div = document.createElement("div");
    const label = segment.label || segment.name || "Partition";
    const className = segment.kind === "free" ? "free" : String(label).toLowerCase();
    div.className = `disk-segment ${className}`;
    div.style.flexBasis = `${width}%`;
    div.innerHTML = `
      <div class="segment-title">${label}</div>
      <div class="segment-meta">${segment.filesystem || "unallocated"} · ${humanBytes(size)}</div>
      <div class="segment-meta">${segment.start_sector} - ${segment.end_sector}</div>
    `;
    els.diskMap.appendChild(div);
  }

  els.partitionTable.innerHTML = `
    <div class="partition-row header">
      <div>Label</div><div>FS</div><div>Start</div><div>End</div><div>Size</div><div>Free</div>
    </div>
  `;
  for (const partition of parts) {
    const row = document.createElement("div");
    row.className = "partition-row";
    row.innerHTML = `
      <div><strong>${partition.label || partition.name || partition.number}</strong></div>
      <div>${partition.filesystem || "unknown"}</div>
      <div>${partition.start_sector}</div>
      <div>${partition.end_sector}</div>
      <div>${humanBytes(partition.size_bytes)}</div>
      <div>${humanBytes(partition.free_bytes)}</div>
    `;
    els.partitionTable.appendChild(row);
  }
}

function renderProcess(operations = []) {
  els.processQueue.innerHTML = "";
  for (const operation of operations) {
    const item = document.createElement("li");
    item.className = "process-step";
    item.dataset.step = operation.step || operation.sequence;
    item.innerHTML = `
      <div class="step-number">${operation.step || operation.sequence}</div>
      <div>
        <div class="step-title">${operation.action || operation.label}</div>
        <div class="step-meta">${operation.writes ? "Guarded write step" : "Read-only step"}</div>
      </div>
      <div class="status-pill ${operation.status || "neutral"}">${operation.status || "queued"}</div>
    `;
    els.processQueue.appendChild(item);
  }
  if (!operations.length) {
    els.processQueue.innerHTML = "<li class=\"process-step\"><div class=\"step-number\">0</div><div><div class=\"step-title\">No process queued</div><div class=\"step-meta\">Run a plan or simulation.</div></div><div class=\"status-pill neutral\">Idle</div></li>";
  }
}

function animateProcess(operations) {
  window.clearInterval(state.processTimer);
  renderProcess(operations.map((item) => ({ ...item, status: "queued" })));
  setStatus(els.processClock, "running");
  let index = 0;
  state.processTimer = window.setInterval(() => {
    const rows = [...els.processQueue.querySelectorAll(".process-step")];
    rows.forEach((row) => row.classList.remove("running"));
    if (index >= operations.length) {
      window.clearInterval(state.processTimer);
      setStatus(els.processClock, "complete");
      return;
    }
    const operation = operations[index];
    const row = rows[index];
    if (row) {
      row.classList.add("running");
      const pill = row.querySelector(".status-pill");
      pill.className = `status-pill ${operation.status}`;
      pill.textContent = operation.status;
    }
    index += 1;
  }, 420);
}

function renderPlan(plan) {
  state.plan = plan;
  setStatus(els.planStatus, plan.plan_status);
  els.resultSummary.textContent = plan.plan_status === "ready"
    ? `Ready to model ${plan.input.increase_human} from ${plan.input.source_label} into ${plan.input.target_label}.`
    : `${plan.blockers.length} blocker${plan.blockers.length === 1 ? "" : "s"} found.`;
  renderProcess(plan.operations);
  els.checksList.innerHTML = "";
  const items = plan.blockers.length
    ? plan.blockers.map((blocker) => ({ title: blocker.id, detail: blocker.message, status: "fail" }))
    : [{ title: "Planner ready", detail: "Mock operation queue is valid.", status: "pass" }];
  for (const item of items) {
    const div = document.createElement("div");
    div.className = "check-item";
    div.innerHTML = `<strong>${item.title}</strong><span>${item.detail}</span><div class="status-pill ${item.status}">${item.status}</div>`;
    els.checksList.appendChild(div);
  }
  setJson(plan);
}

function renderVerification(result) {
  state.verification = result;
  setStatus(els.planStatus, result.verification_status);
  els.resultSummary.textContent = `Verification ${result.verification_status}.`;
  els.checksList.innerHTML = "";
  for (const check of result.checks) {
    const div = document.createElement("div");
    div.className = "check-item";
    const details = check.status === "pass" ? "Expected invariant held." : JSON.stringify(check.details);
    div.innerHTML = `<strong>${check.name}</strong><span>${details}</span><div class="status-pill ${check.status}">${check.status}</div>`;
    els.checksList.appendChild(div);
  }
  setJson(result);
}

async function loadFixtures() {
  const data = await apiGet("/api/fixtures");
  state.fixtures = data.fixtures;
  els.fixtureSelect.innerHTML = "";
  for (const fixture of data.fixtures) {
    const option = document.createElement("option");
    option.value = fixture.file;
    option.textContent = fixture.scenario;
    els.fixtureSelect.appendChild(option);
  }
  const preferred = state.fixtures.find((fixture) => fixture.file === "normal-c-e-layout.json");
  if (preferred) els.fixtureSelect.value = preferred.file;
  await loadLayout();
}

async function loadLayout() {
  const fixture = els.fixtureSelect.value;
  if (!fixture) return;
  const layout = await apiGet(`/api/layout?fixture=${encodeURIComponent(fixture)}`);
  renderLayout(layout);
  renderProcess([]);
  setStatus(els.planStatus, "idle");
  setJson(layout);
}

async function loadSafety() {
  const data = await apiGet("/api/safety");
  els.safetyModes.innerHTML = "";
  for (const mode of data.modes) {
    const item = document.createElement("div");
    item.className = "safety-item";
    item.innerHTML = `<span>${mode.label}</span><span class="status-pill ${mode.status}">${mode.status}</span>`;
    els.safetyModes.appendChild(item);
  }
}

async function runPlan() {
  try {
    els.runPlanButton.disabled = true;
    const plan = await apiPost("/api/plan", payload());
    renderPlan(plan);
  } catch (error) {
    setError(error);
  } finally {
    els.runPlanButton.disabled = false;
  }
}

async function runVerify() {
  try {
    els.verifyButton.disabled = true;
    const result = await apiPost("/api/verify", payload());
    renderVerification(result);
  } catch (error) {
    setError(error);
  } finally {
    els.verifyButton.disabled = false;
  }
}

async function runSimulation() {
  try {
    els.simulateButton.disabled = true;
    const result = await apiPost("/api/process-demo", payload());
    setJson(result);
    setStatus(els.planStatus, result.plan_status);
    animateProcess(result.events);
  } catch (error) {
    setError(error);
  } finally {
    els.simulateButton.disabled = false;
  }
}

function clearOutput() {
  window.clearInterval(state.processTimer);
  setStatus(els.planStatus, "idle");
  setStatus(els.processClock, "waiting");
  els.resultSummary.textContent = "Run a plan to populate results.";
  els.checksList.innerHTML = "";
  renderProcess([]);
  setJson(state.layout || {});
}

els.fixtureSelect.addEventListener("change", () => loadLayout().catch(setError));
els.refreshButton.addEventListener("click", () => loadFixtures().catch(setError));
els.runPlanButton.addEventListener("click", runPlan);
els.verifyButton.addEventListener("click", runVerify);
els.simulateButton.addEventListener("click", runSimulation);
els.clearButton.addEventListener("click", clearOutput);

loadSafety().catch(setError);
loadFixtures().catch(setError);
