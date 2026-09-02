/* SPDX-License-Identifier: AGPL-3.0-or-later */

const state = {
  index: null,
  focusId: null,
  history: [],
  camera: { yaw: -0.55, pitch: 0.35, zoom: 1 },
  pointer: null,
  renderedNodes: [],
};

const canvas = document.querySelector("#map");
const context = canvas.getContext("2d");
const labels = document.querySelector("#labels");
const focusTitle = document.querySelector("#focus-title");
const focusStats = document.querySelector("#focus-stats");
const article = document.querySelector("#article");
const articleBody = document.querySelector("#article-body");
const brand = document.querySelector("#brand");
const backButton = document.querySelector("#back");
const search = document.querySelector("#search");
const searchResults = document.querySelector("#search-results");
const version = document.querySelector("#version");
const provenance = document.querySelector("#provenance");

function conceptById(id) {
  return state.index.concepts.find((concept) => concept.id === id);
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

// Provisional local projection. Source coordinates always remain six-dimensional.
function relativeAxis(targetPositive, targetNegative, centrePositive, centreNegative) {
  const numerator = targetPositive * centreNegative - targetNegative * centrePositive;
  const denominator = targetPositive * centreNegative + targetNegative * centrePositive;
  return denominator ? numerator / denominator : 0;
}

function localPosition(target, centre) {
  if (target.id === centre.id) return { x: 0, y: 0, z: 0 };
  const t = target.coordinates;
  const c = centre.coordinates;
  return {
    x: relativeAxis(t[0], t[1], c[0], c[1]),
    y: relativeAxis(t[2], t[3], c[2], c[3]),
    z: relativeAxis(t[4], t[5], c[4], c[5]),
  };
}

function mix(left, right, amount) {
  return left.map((value, index) => value + (right[index] - value) * amount);
}

// Provisional accessible preview only; it is not the stable color contract.
function previewColor(position) {
  const pairs = [
    [[0, 210, 220], [238, 72, 74]],
    [[214, 70, 214], [62, 206, 112]],
    [[240, 205, 44], [65, 112, 238]],
  ];
  const values = [position.x, position.y, position.z];
  const channels = [0, 1, 2].map((axis) => mix(pairs[axis][0], pairs[axis][1], (values[axis] + 1) / 2));
  const rgb = [0, 1, 2].map((channel) => Math.round(channels.reduce((sum, color) => sum + color[channel], 0) / 3));
  return `rgb(${rgb.join(", ")})`;
}

function rotate(position) {
  const cosYaw = Math.cos(state.camera.yaw);
  const sinYaw = Math.sin(state.camera.yaw);
  const cosPitch = Math.cos(state.camera.pitch);
  const sinPitch = Math.sin(state.camera.pitch);
  const x1 = position.x * cosYaw - position.z * sinYaw;
  const z1 = position.x * sinYaw + position.z * cosYaw;
  return {
    x: x1,
    y: position.y * cosPitch - z1 * sinPitch,
    z: position.y * sinPitch + z1 * cosPitch,
  };
}

function project(position, width, height) {
  const rotated = rotate(position);
  const depth = 2.9 + rotated.z;
  const perspective = state.camera.zoom / Math.max(1.5, depth);
  const scale = Math.min(width, height) * 1.45 * perspective;
  return {
    x: width / 2 + rotated.x * scale,
    y: height / 2 - rotated.y * scale,
    z: rotated.z,
    perspective,
  };
}

function resizeCanvas() {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const rectangle = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(rectangle.width * ratio));
  const height = Math.max(1, Math.round(rectangle.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { width: rectangle.width, height: rectangle.height };
}

function drawAxis(width, height, axis, semantics, negativeColor, positiveColor) {
  const centre = project({ x: 0, y: 0, z: 0 }, width, height);
  const negativePosition = { x: 0, y: 0, z: 0 };
  const positivePosition = { x: 0, y: 0, z: 0 };
  negativePosition[axis] = -1;
  positivePosition[axis] = 1;
  const negative = project(negativePosition, width, height);
  const positive = project(positivePosition, width, height);
  const gradient = context.createLinearGradient(negative.x, negative.y, positive.x, positive.y);
  gradient.addColorStop(0, negativeColor);
  gradient.addColorStop(.5, "rgba(150, 157, 169, .26)");
  gradient.addColorStop(1, positiveColor);
  context.strokeStyle = gradient;
  context.lineWidth = 1.2;
  context.beginPath();
  context.moveTo(negative.x, negative.y);
  context.lineTo(centre.x, centre.y);
  context.lineTo(positive.x, positive.y);
  context.stroke();
  for (const [point, color] of [[negative, negativeColor], [positive, positiveColor]]) {
    context.fillStyle = color;
    context.beginPath();
    context.arc(point.x, point.y, 3.5, 0, Math.PI * 2);
    context.fill();
  }
  return [
    { screen: negative, centre, text: semantics.negative, color: negativeColor },
    { screen: positive, centre, text: semantics.positive, color: positiveColor },
  ];
}

function drawSphere(node) {
  const radius = node.radius;
  const gradient = context.createRadialGradient(
    node.screen.x - radius * .3, node.screen.y - radius * .35, radius * .08,
    node.screen.x, node.screen.y, radius,
  );
  gradient.addColorStop(0, "rgba(255, 255, 255, .95)");
  gradient.addColorStop(.24, node.color);
  gradient.addColorStop(1, "rgba(5, 8, 14, .55)");
  context.fillStyle = gradient;
  context.strokeStyle = node.focus ? "rgba(255, 255, 255, .85)" : "rgba(205, 221, 244, .45)";
  context.lineWidth = node.focus ? 2 : 1;
  context.beginPath();
  context.arc(node.screen.x, node.screen.y, radius, 0, Math.PI * 2);
  context.fill();
  context.stroke();
}

function drawMap() {
  if (!state.index) return;
  const { width, height } = resizeCanvas();
  context.clearRect(0, 0, width, height);
  const focus = conceptById(state.focusId);
  const visible = [focus, ...focus.linkedIds.map(conceptById).filter(Boolean)];

  const axisLabels = [
    ...drawAxis(width, height, "x", state.index.axes[0], "rgba(0, 210, 220, .65)", "rgba(238, 72, 74, .65)"),
    ...drawAxis(width, height, "y", state.index.axes[1], "rgba(214, 70, 214, .65)", "rgba(62, 206, 112, .65)"),
    ...drawAxis(width, height, "z", state.index.axes[2], "rgba(240, 205, 44, .65)", "rgba(65, 112, 238, .65)"),
  ];

  const nodes = visible.map((concept) => {
    const position = localPosition(concept, focus);
    const screen = project(position, width, height);
    const baseRadius = concept.id === focus.id ? 18 : 7 + Math.sqrt(concept.incomingCount + 1) * 4;
    return {
      concept,
      position,
      screen,
      radius: baseRadius * clamp(screen.perspective * 2.5, .72, 1.35),
      color: previewColor(position),
      focus: concept.id === focus.id,
    };
  }).sort((left, right) => left.screen.z - right.screen.z);

  const nodesById = new Map(nodes.map((node) => [node.concept.id, node]));
  const edges = [];
  const seenEdges = new Set();
  for (const node of nodes) {
    for (const linkedId of node.concept.linkedIds) {
      if (!nodesById.has(linkedId)) continue;
      const edgeId = [node.concept.id, linkedId].sort().join("\u0000");
      if (seenEdges.has(edgeId)) continue;
      seenEdges.add(edgeId);
      edges.push([node, nodesById.get(linkedId)]);
    }
  }
  context.strokeStyle = "rgba(160, 180, 210, .2)";
  context.lineWidth = 1;
  for (const [source, target] of edges) {
    context.beginPath();
    context.moveTo(source.screen.x, source.screen.y);
    context.lineTo(target.screen.x, target.screen.y);
    context.stroke();
  }
  canvas.dataset.edgeCount = String(edges.length);
  nodes.forEach(drawSphere);
  state.renderedNodes = nodes;
  renderLabels(nodes, axisLabels, width, height);
}

function renderLabels(nodes, axisLabels, width, height) {
  labels.replaceChildren();
  for (const axis of axisLabels) {
    const deltaX = axis.screen.x - axis.centre.x;
    const deltaY = axis.screen.y - axis.centre.y;
    const length = Math.hypot(deltaX, deltaY) || 1;
    const label = document.createElement("span");
    label.className = "axis-label";
    label.textContent = axis.text;
    label.style.left = `${clamp(axis.screen.x + deltaX / length * 22, 52, width - 52)}px`;
    label.style.top = `${clamp(axis.screen.y + deltaY / length * 22, 16, height - 16)}px`;
    label.style.setProperty("--axis-color", axis.color);
    labels.append(label);
  }
  const occupied = [];
  const orderedNodes = [...nodes].sort((left, right) => Number(right.focus) - Number(left.focus) || right.concept.incomingCount - left.concept.incomingCount);
  for (const node of orderedNodes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "node-label";
    button.append(document.createTextNode(node.concept.title));
    const rating = document.createElement("small");
    rating.textContent = `↗ ${node.concept.incomingCount}`;
    button.append(rating);
    button.addEventListener("click", () => navigate(node.concept.id));
    button.style.visibility = "hidden";
    labels.append(button);
    const labelWidth = button.offsetWidth;
    const labelHeight = button.offsetHeight;
    const gap = 10;
    const candidates = [
      { x: node.screen.x - labelWidth / 2, y: node.screen.y - node.radius - labelHeight - gap },
      { x: node.screen.x + node.radius + gap, y: node.screen.y - labelHeight / 2 },
      { x: node.screen.x - node.radius - labelWidth - gap, y: node.screen.y - labelHeight / 2 },
      { x: node.screen.x - labelWidth / 2, y: node.screen.y + node.radius + gap },
    ].map((candidate) => ({
      x: clamp(candidate.x, 6, Math.max(6, width - labelWidth - 6)),
      y: clamp(candidate.y, 6, Math.max(6, height - labelHeight - 6)),
      width: labelWidth,
      height: labelHeight,
    }));
    const chosen = candidates.find((candidate) => !occupied.some((placed) => (
      candidate.x < placed.x + placed.width + 6
      && candidate.x + candidate.width + 6 > placed.x
      && candidate.y < placed.y + placed.height + 6
      && candidate.y + candidate.height + 6 > placed.y
    ))) || candidates[0];
    button.style.left = `${chosen.x}px`;
    button.style.top = `${chosen.y}px`;
    button.style.visibility = "visible";
    occupied.push(chosen);
  }
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function inlineMarkdown(value) {
  return value
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
      const safeLabel = label;
      if (/^(?:https?:)?\/\//i.test(href)) {
        return `<a href="${href}" rel="noopener noreferrer">${safeLabel}</a>`;
      }
      const focus = conceptById(state.focusId);
      const targetPath = new URL(href, `https://hexrelatum.invalid/${focus.path}`).pathname.replace(/^\//, "");
      const target = state.index.concepts.find((concept) => concept.path === targetPath);
      return target ? `<a href="#${target.id}" data-concept-id="${target.id}">${safeLabel}</a>` : safeLabel;
    })
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/~~([^~]+)~~/g, "<s>$1</s>")
    .replace(/\+\+([^+]+)\+\+/g, "<u>$1</u>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function renderMarkdown(markdown) {
  const safe = escapeHtml(markdown);
  const lines = safe.split("\n");
  const output = [];
  let inCode = false;
  let inList = false;
  let paragraph = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    output.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  for (const line of lines) {
    if (line.startsWith("```")) {
      flushParagraph();
      if (inList) { output.push("</ul>"); inList = false; }
      output.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
      continue;
    }
    if (inCode) { output.push(`${line}\n`); continue; }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      if (inList) { output.push("</ul>"); inList = false; }
      const level = heading[1].length;
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const listItem = /^-\s+(.+)$/.exec(line);
    if (listItem) {
      flushParagraph();
      if (!inList) { output.push("<ul>"); inList = true; }
      output.push(`<li>${inlineMarkdown(listItem[1])}</li>`);
      continue;
    }
    if (inList) { output.push("</ul>"); inList = false; }
    if (line.trim()) paragraph.push(line.trim());
    else flushParagraph();
  }
  flushParagraph();
  if (inList) output.push("</ul>");
  if (inCode) output.push("</code></pre>");
  return output.join("\n");
}

function renderFocus() {
  const focus = conceptById(state.focusId);
  focusTitle.textContent = focus.title;
  focusStats.textContent = `входящих упоминаний ${focus.incomingCount} · связей ${focus.linkedIds.length} · шесть координат ${focus.coordinates.join(" · ")}`;
  articleBody.innerHTML = renderMarkdown(focus.body);
  articleBody.querySelectorAll("[data-concept-id]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(link.dataset.conceptId);
    });
  });
  backButton.disabled = state.history.length < 2;
  document.title = `${focus.title} · Hexrelatum`;
  drawMap();
}

function navigate(id, { remember = true } = {}) {
  if (!conceptById(id)) return;
  if (remember && state.history.at(-1) !== id) state.history.push(id);
  state.focusId = id;
  location.hash = id;
  renderFocus();
  if (!conceptById(id).map) article.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderProvenance() {
  const data = state.index.provenance;
  version.textContent = `Hexrelatum ${state.index.engineVersion} · индекс ${state.index.formatVersion}`;
  const links = [
    ["Репозиторий этой вики", data.repository],
    ["Репозиторий-родитель", data.parentRepository],
    ["Первоисточник", data.upstreamRepository],
    ["Лицензии", `${data.repository}/blob/${data.defaultBranch}/LICENSES.md`],
    ["Скачать", `${data.repository}/archive/refs/heads/${data.defaultBranch}.zip`],
  ];
  provenance.replaceChildren(...links.filter(([, href]) => href).map(([label, href]) => {
    const link = document.createElement("a");
    link.href = href;
    link.textContent = label;
    link.rel = "noopener noreferrer";
    return link;
  }));
}

function renderSearch() {
  const query = search.value.trim().toLocaleLowerCase("ru");
  searchResults.replaceChildren();
  if (!query) return;
  const matches = state.index.concepts
    .filter((concept) => concept.title.toLocaleLowerCase("ru").includes(query))
    .slice(0, 8);
  for (const concept of matches) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = concept.title;
    button.addEventListener("click", () => {
      search.value = "";
      searchResults.replaceChildren();
      navigate(concept.id);
    });
    searchResults.append(button);
  }
}

canvas.addEventListener("pointerdown", (event) => {
  canvas.setPointerCapture(event.pointerId);
  state.pointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
  canvas.classList.add("dragging");
});
canvas.addEventListener("pointermove", (event) => {
  if (!state.pointer || state.pointer.id !== event.pointerId) return;
  state.camera.yaw += (event.clientX - state.pointer.x) * .008;
  state.camera.pitch = clamp(state.camera.pitch + (event.clientY - state.pointer.y) * .008, -1.35, 1.35);
  state.pointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
  drawMap();
});
canvas.addEventListener("pointerup", (event) => {
  if (state.pointer?.id === event.pointerId) state.pointer = null;
  canvas.classList.remove("dragging");
});
canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  state.camera.zoom = clamp(state.camera.zoom * Math.exp(-event.deltaY * .001), .55, 2.4);
  drawMap();
}, { passive: false });
canvas.addEventListener("click", (event) => {
  const rectangle = canvas.getBoundingClientRect();
  const x = event.clientX - rectangle.left;
  const y = event.clientY - rectangle.top;
  const match = [...state.renderedNodes].reverse().find((node) => Math.hypot(x - node.screen.x, y - node.screen.y) <= node.radius + 5);
  if (match) navigate(match.concept.id);
});

backButton.addEventListener("click", () => {
  if (state.history.length < 2) return;
  state.history.pop();
  navigate(state.history.at(-1), { remember: false });
});
brand.addEventListener("click", (event) => {
  event.preventDefault();
  navigate(state.index.homeId);
});
search.addEventListener("input", renderSearch);
window.addEventListener("resize", drawMap);

async function start() {
  try {
    const response = await fetch("../public/index.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.index = await response.json();
    renderProvenance();
    const requested = location.hash.slice(1);
    navigate(conceptById(requested) ? requested : state.index.homeId);
  } catch (error) {
    focusTitle.textContent = "Не удалось открыть индекс";
    focusStats.textContent = String(error);
  }
}

start();
