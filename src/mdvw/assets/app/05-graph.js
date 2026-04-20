// ---------- Graph ----------

const graphCanvas = document.getElementById('graph-canvas');
const graphCtx = graphCanvas ? graphCanvas.getContext('2d') : null;
const graphStage = document.getElementById('graph-stage');
const graphTooltip = document.getElementById('graph-tooltip');
const graphStats = document.getElementById('graph-stats');
const graphDepth = document.getElementById('graph-depth');
const graphDepthValue = document.getElementById('graph-depth-value');
const graphShowUnresolved = document.getElementById('graph-show-unresolved');
const graphShowOrphans = document.getElementById('graph-show-orphans');
const graphModeInputs = Array.from(document.querySelectorAll('input[name="graph-mode"]'));

let graphNodes = [];
let graphEdges = [];
let graphNodeMap = new Map();
let graphFrame = 0;
let graphTicks = 0;
let graphHoverNode = null;
let graphDragNode = null;
let graphPointer = null;
let graphPanning = false;
let graphTransform = { x: 0, y: 0, k: 1 };

function showGraphView() {
  if (!browseRoot) {
    flash('Graph unavailable without a workspace');
    return;
  }
  showLeftSection('graph');
}

function graphIsVisible() {
  return document.body.classList.contains('graph-fullscreen')
    || (leftPaneSection === 'graph' && !leftPaneCollapsed);
}

async function enterFullscreenGraph() {
  if (!browseRoot) {
    flash('Graph unavailable without a workspace');
    return;
  }
  if (document.body.classList.contains('graph-fullscreen')) return;
  document.body.classList.add('graph-fullscreen');
  if (!graphLoaded || graphStale) {
    await loadGraph({ resetView: true });
  } else {
    resizeGraphCanvas();
    renderGraph();
    startGraphSimulation();
  }
}

function exitFullscreenGraph() {
  if (!document.body.classList.contains('graph-fullscreen')) return;
  document.body.classList.remove('graph-fullscreen');
  if (leftPaneSection === 'graph' && !leftPaneCollapsed) {
    requestAnimationFrame(() => { resizeGraphCanvas(); renderGraph(); });
  }
}

function toggleFullscreenGraph() {
  if (document.body.classList.contains('graph-fullscreen')) exitFullscreenGraph();
  else enterFullscreenGraph();
}

function selectedGraphMode() {
  const checked = graphModeInputs.find(input => input.checked);
  if (checked && checked.value === 'local' && !currentPath) return 'workspace';
  return checked ? checked.value : (currentPath ? 'local' : 'workspace');
}

function graphOptions() {
  return {
    mode: selectedGraphMode(),
    depth: Number(graphDepth.value || 1),
    include_unresolved: graphShowUnresolved.checked,
    include_orphans: graphShowOrphans.checked,
    max_nodes: 500,
    max_edges: 2000,
  };
}

function updateGraphControlState() {
  if (!currentPath) {
    const workspace = graphModeInputs.find(input => input.value === 'workspace');
    if (workspace) workspace.checked = true;
  }
  const local = selectedGraphMode() === 'local';
  graphDepth.disabled = !local;
  graphShowOrphans.disabled = local;
  graphDepthValue.textContent = graphDepth.value;
}

async function loadGraph({ resetView = false } = {}) {
  if (!graphCanvas || !graphCtx) return;
  const api = await whenApiReady();
  if (!api || !api.get_graph || !browseRoot) {
    graphNodes = [];
    graphEdges = [];
    graphNodeMap = new Map();
    graphStats.textContent = browseRoot ? 'Graph unavailable' : 'No workspace';
    renderGraph();
    return;
  }
  updateGraphControlState();
  graphStats.textContent = 'Loading graph...';
  let payload = null;
  try {
    payload = await api.get_graph(graphOptions());
  } catch {
    graphStats.textContent = 'Could not load graph';
    return;
  }
  applyGraphPayload(payload || { nodes: [], edges: [], stats: {} }, resetView);
  graphLoaded = true;
  graphStale = false;
}

function applyGraphPayload(payload, resetView) {
  const oldMap = graphNodeMap;
  graphNodeMap = new Map();
  graphNodes = (payload.nodes || []).map((node, i) => {
    const existing = oldMap.get(node.id);
    const next = existing ? Object.assign(existing, node) : seedGraphNode(node, i);
    graphNodeMap.set(next.id, next);
    return next;
  });
  graphEdges = (payload.edges || [])
    .map(edge => ({
      ...edge,
      sourceNode: graphNodeMap.get(edge.source),
      targetNode: graphNodeMap.get(edge.target),
    }))
    .filter(edge => edge.sourceNode && edge.targetNode);
  if (resetView || !oldMap.size) resetGraphView();
  updateGraphStats(payload.stats || {});
  resizeGraphCanvas();
  startGraphSimulation();
  renderGraph();
}

function seedGraphNode(node, index) {
  const angle = (hashString(node.id) % 6283) / 1000;
  const ring = 40 + (hashString(`${node.id}:${index}`) % 120);
  const seeded = {
    ...node,
    x: node.current ? 0 : Math.cos(angle) * ring,
    y: node.current ? 0 : Math.sin(angle) * ring,
    vx: 0,
    vy: 0,
  };
  return seeded;
}

function hashString(value) {
  let h = 2166136261;
  for (let i = 0; i < String(value).length; i += 1) {
    h ^= String(value).charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

function updateGraphStats(stats) {
  const message = stats.message ? `${escapeHtml(stats.message)}. ` : '';
  const mode = stats.mode === 'local' ? `Local depth ${stats.depth || 1}` : 'Workspace';
  const truncated = stats.truncated ? ' <strong>Truncated</strong>' : '';
  graphStats.innerHTML =
    `${message}<strong>${mode}</strong> · ${stats.node_count || 0} nodes · ` +
    `${stats.edge_count || 0} links${truncated}`;
}

function resizeGraphCanvas() {
  if (!graphCanvas || !graphStage) return;
  const rect = graphStage.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  if (graphCanvas.width !== Math.floor(width * dpr)) graphCanvas.width = Math.floor(width * dpr);
  if (graphCanvas.height !== Math.floor(height * dpr)) graphCanvas.height = Math.floor(height * dpr);
  graphCanvas.style.width = `${width}px`;
  graphCanvas.style.height = `${height}px`;
}

function graphColor(name) {
  return getComputedStyle(html).getPropertyValue(name).trim();
}

function graphNodeRadius(node) {
  const base = node.type === 'unresolved' ? 5 : 6;
  return base + Math.min(6, Math.sqrt(node.degree || 0) * 1.7) + (node.current ? 2 : 0);
}

function graphToScreen(node) {
  const w = graphCanvas.clientWidth || 1;
  const h = graphCanvas.clientHeight || 1;
  return {
    x: (w / 2) + graphTransform.x + (node.x * graphTransform.k),
    y: (h / 2) + graphTransform.y + (node.y * graphTransform.k),
  };
}

function screenToGraph(x, y) {
  const w = graphCanvas.clientWidth || 1;
  const h = graphCanvas.clientHeight || 1;
  return {
    x: (x - (w / 2) - graphTransform.x) / graphTransform.k,
    y: (y - (h / 2) - graphTransform.y) / graphTransform.k,
  };
}

function renderGraph() {
  if (!graphCanvas || !graphCtx) return;
  resizeGraphCanvas();
  const dpr = window.devicePixelRatio || 1;
  const w = graphCanvas.clientWidth || 1;
  const h = graphCanvas.clientHeight || 1;
  graphCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  graphCtx.clearRect(0, 0, w, h);
  graphCtx.lineCap = 'round';
  graphCtx.lineJoin = 'round';
  drawGraphEdges();
  drawGraphNodes();
  if (!graphNodes.length) {
    graphCtx.fillStyle = graphColor('--muted');
    graphCtx.font = '12px var(--font-sans)';
    graphCtx.textAlign = 'center';
    graphCtx.fillText('No graph data', w / 2, h / 2);
  }
}

function drawGraphEdges() {
  const okColor = graphColor('--border');
  const weakColor = graphColor('--muted');
  for (const edge of graphEdges) {
    const a = graphToScreen(edge.sourceNode);
    const b = graphToScreen(edge.targetNode);
    graphCtx.beginPath();
    graphCtx.setLineDash(edge.status === 'ok' ? [] : [5, 4]);
    graphCtx.strokeStyle = edge.status === 'ok' ? okColor : weakColor;
    graphCtx.globalAlpha = edge.status === 'ok' ? 0.8 : 0.7;
    graphCtx.lineWidth = edge.status === 'ok' ? 1 : 1.2;
    graphCtx.moveTo(a.x, a.y);
    graphCtx.lineTo(b.x, b.y);
    graphCtx.stroke();
  }
  graphCtx.globalAlpha = 1;
  graphCtx.setLineDash([]);
}

function drawGraphNodes() {
  const fg = graphColor('--fg');
  const soft = graphColor('--fg-soft');
  const bg = graphColor('--bg');
  const muted = graphColor('--muted');
  const labelColor = graphColor('--fg-soft');
  const showLabels = graphNodes.length <= 120 || graphTransform.k >= 1.15;
  graphCtx.font = '11px var(--font-sans)';
  graphCtx.textAlign = 'center';
  graphCtx.textBaseline = 'top';
  for (const node of graphNodes) {
    const p = graphToScreen(node);
    const r = graphNodeRadius(node) * Math.max(0.75, Math.sqrt(graphTransform.k));
    graphCtx.beginPath();
    graphCtx.arc(p.x, p.y, r, 0, Math.PI * 2);
    graphCtx.fillStyle = node.type === 'unresolved' ? bg : (node.current ? fg : soft);
    graphCtx.strokeStyle = node.type === 'unresolved' ? muted : fg;
    graphCtx.lineWidth = node.current ? 2 : 1.3;
    graphCtx.setLineDash(node.type === 'unresolved' ? [4, 3] : []);
    graphCtx.fill();
    graphCtx.stroke();
    graphCtx.setLineDash([]);
    if (node === graphHoverNode) {
      graphCtx.beginPath();
      graphCtx.arc(p.x, p.y, r + 4, 0, Math.PI * 2);
      graphCtx.strokeStyle = fg;
      graphCtx.lineWidth = 1;
      graphCtx.stroke();
    }
    if (showLabels || node.current || node === graphHoverNode) {
      graphCtx.fillStyle = labelColor;
      graphCtx.fillText(truncateGraphLabel(node.label || node.id), p.x, p.y + r + 5);
    }
  }
}

function truncateGraphLabel(label) {
  const text = String(label || '');
  return text.length > 22 ? `${text.slice(0, 21)}…` : text;
}

function startGraphSimulation() {
  cancelAnimationFrame(graphFrame);
  graphTicks = 0;
  const run = () => {
    tickGraphLayout();
    renderGraph();
    graphTicks += 1;
    if (graphTicks < 220) graphFrame = requestAnimationFrame(run);
  };
  graphFrame = requestAnimationFrame(run);
}

function tickGraphLayout() {
  const nodes = graphNodes;
  if (!nodes.length) return;
  const charge = nodes.length > 260 ? 900 : 2200;
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let dist2 = (dx * dx) + (dy * dy);
      if (dist2 < 0.01) {
        dx = 0.1 + (j % 3) * 0.05;
        dy = 0.1 + (i % 3) * 0.05;
        dist2 = (dx * dx) + (dy * dy);
      }
      const dist = Math.sqrt(dist2);
      const force = charge / Math.max(80, dist2);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx -= fx;
      a.vy -= fy;
      b.vx += fx;
      b.vy += fy;
    }
  }
  for (const edge of graphEdges) {
    const a = edge.sourceNode;
    const b = edge.targetNode;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.max(1, Math.sqrt((dx * dx) + (dy * dy)));
    const ideal = edge.targetNode.type === 'unresolved' ? 80 : 95;
    const force = (dist - ideal) * 0.006;
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }
  for (const node of nodes) {
    const centerForce = node.current ? 0.025 : 0.004;
    node.vx += -node.x * centerForce;
    node.vy += -node.y * centerForce;
    if (node === graphDragNode) {
      node.vx = 0;
      node.vy = 0;
      continue;
    }
    node.vx *= 0.82;
    node.vy *= 0.82;
    node.x += Math.max(-12, Math.min(12, node.vx));
    node.y += Math.max(-12, Math.min(12, node.vy));
  }
}

function resetGraphView() {
  graphTransform = { x: 0, y: 0, k: 1 };
  renderGraph();
}

function zoomGraph(factor, clientX, clientY) {
  const rect = graphCanvas.getBoundingClientRect();
  const sx = clientX === undefined ? rect.width / 2 : clientX - rect.left;
  const sy = clientY === undefined ? rect.height / 2 : clientY - rect.top;
  const before = screenToGraph(sx, sy);
  graphTransform.k = Math.max(0.35, Math.min(3, graphTransform.k * factor));
  graphTransform.x = sx - (rect.width / 2) - before.x * graphTransform.k;
  graphTransform.y = sy - (rect.height / 2) - before.y * graphTransform.k;
  renderGraph();
}

function graphNodeAt(clientX, clientY) {
  const rect = graphCanvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  for (let i = graphNodes.length - 1; i >= 0; i -= 1) {
    const node = graphNodes[i];
    const p = graphToScreen(node);
    const r = graphNodeRadius(node) * Math.max(0.75, Math.sqrt(graphTransform.k)) + 5;
    if (((p.x - x) ** 2) + ((p.y - y) ** 2) <= r ** 2) return node;
  }
  return null;
}

function updateGraphTooltip(node, event) {
  if (!graphTooltip) return;
  if (!node) {
    graphTooltip.hidden = true;
    return;
  }
  const detail = node.type === 'note'
    ? `${node.relative || ''} · ${node.in || 0} in / ${node.out || 0} out`
    : `${node.status || 'unresolved'} · ${node.target || ''}`;
  graphTooltip.innerHTML =
    `<span class="graph-tip-title">${escapeHtml(node.label || node.id)}</span>` +
    `<span class="graph-tip-detail">${escapeHtml(detail)}</span>`;
  const rect = graphStage.getBoundingClientRect();
  graphTooltip.style.left = `${Math.min(event.clientX - rect.left + 12, rect.width - 230)}px`;
  graphTooltip.style.top = `${Math.max(8, event.clientY - rect.top + 12)}px`;
  graphTooltip.hidden = false;
}

async function openGraphNode(node) {
  const api = getApi();
  if (!api || !node) return;
  if (node.type === 'note' && node.path) {
    if (sameBrowserPath(node.path, currentPath)) return;
    if (!(await confirmDiscardIfDirty())) return;
    const ok = api.open_path ? await api.open_path(node.path) : false;
    if (!ok) flash('Could not open note');
    return;
  }
  if (node.type === 'unresolved') {
    if (node.status !== 'missing') {
      flash(node.message || 'Wiki link is ambiguous');
      return;
    }
    if (!api.create_wiki_note) return;
    if (!(await confirmDiscardIfDirty())) return;
    const result = await api.create_wiki_note(node.target || node.label || '');
    if (result && (result.status === 'created' || result.status === 'ok')) {
      graphStale = true;
      await refreshBrowserIfVisible(result.path || currentPath);
      await loadGraph();
      flash(result.status === 'created' ? 'Created note' : 'Opened note');
      return;
    }
    flash((result && result.message) || 'Could not create note');
  }
}

if (graphCanvas) {
  graphCanvas.addEventListener('pointerdown', (e) => {
    const node = graphNodeAt(e.clientX, e.clientY);
    graphPointer = {
      x: e.clientX,
      y: e.clientY,
      startX: e.clientX,
      startY: e.clientY,
      panX: graphTransform.x,
      panY: graphTransform.y,
      moved: false,
    };
    graphDragNode = node;
    graphPanning = !node;
    graphCanvas.classList.add('dragging');
    graphCanvas.setPointerCapture(e.pointerId);
  });
  graphCanvas.addEventListener('pointermove', (e) => {
    if (graphPointer) {
      const dx = e.clientX - graphPointer.x;
      const dy = e.clientY - graphPointer.y;
      if (Math.abs(e.clientX - graphPointer.startX) + Math.abs(e.clientY - graphPointer.startY) > 4) {
        graphPointer.moved = true;
      }
      if (graphDragNode) {
        const rect = graphCanvas.getBoundingClientRect();
        const p = screenToGraph(e.clientX - rect.left, e.clientY - rect.top);
        graphDragNode.x = p.x;
        graphDragNode.y = p.y;
        graphDragNode.vx = 0;
        graphDragNode.vy = 0;
      } else if (graphPanning) {
        graphTransform.x = graphPointer.panX + (e.clientX - graphPointer.startX);
        graphTransform.y = graphPointer.panY + (e.clientY - graphPointer.startY);
      }
      graphPointer.x = e.clientX;
      graphPointer.y = e.clientY;
      renderGraph();
      return;
    }
    const node = graphNodeAt(e.clientX, e.clientY);
    if (node !== graphHoverNode) {
      graphHoverNode = node;
      renderGraph();
    }
    updateGraphTooltip(node, e);
  });
  graphCanvas.addEventListener('pointerup', async (e) => {
    const clicked = graphDragNode && graphPointer && !graphPointer.moved ? graphDragNode : null;
    graphDragNode = null;
    graphPanning = false;
    graphCanvas.classList.remove('dragging');
    graphCanvas.releasePointerCapture(e.pointerId);
    graphPointer = null;
    if (clicked) await openGraphNode(clicked);
    startGraphSimulation();
  });
  graphCanvas.addEventListener('pointerleave', () => {
    if (!graphPointer) {
      graphHoverNode = null;
      updateGraphTooltip(null);
      renderGraph();
    }
  });
  graphCanvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    zoomGraph(e.deltaY < 0 ? 1.12 : 0.89, e.clientX, e.clientY);
  }, { passive: false });
}

for (const input of graphModeInputs) {
  input.addEventListener('change', () => {
    updateGraphControlState();
    graphStale = true;
    loadGraph({ resetView: true });
  });
}
graphDepth.addEventListener('input', () => {
  graphDepthValue.textContent = graphDepth.value;
  graphStale = true;
  loadGraph({ resetView: true });
});
graphShowUnresolved.addEventListener('change', () => {
  graphStale = true;
  loadGraph({ resetView: true });
});
graphShowOrphans.addEventListener('change', () => {
  graphStale = true;
  loadGraph({ resetView: true });
});
document.getElementById('btn-graph-refresh').addEventListener('click', () => loadGraph({ resetView: true }));
document.getElementById('btn-graph-focus').addEventListener('click', () => {
  const local = graphModeInputs.find(input => input.value === 'local');
  if (local) local.checked = true;
  updateGraphControlState();
  loadGraph({ resetView: true });
});
document.getElementById('graph-zoom-in').addEventListener('click', () => zoomGraph(1.18));
document.getElementById('graph-zoom-out').addEventListener('click', () => zoomGraph(0.85));
document.getElementById('graph-zoom-reset').addEventListener('click', resetGraphView);
if (window.ResizeObserver && graphStage) {
  new ResizeObserver(() => renderGraph()).observe(graphStage);
}
document.getElementById('btn-graph-full').addEventListener('click', toggleFullscreenGraph);
document.getElementById('btn-graph-close').addEventListener('click', exitFullscreenGraph);

