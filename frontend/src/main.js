/* Main Controller for CodeFlow3D - PRODUCTION READY */

import { getEditorCode, setLanguage, setEditorCode, isEditorReady, revealLine, setErrorDecoration, clearErrorDecoration } from "./editor_setup.js";
import {
    addNode,
    addEdge,
    updateScene,
    clearScene,
    resetCamera,
    fitCameraToGraph,
    getSceneInfo,
    dispose,
    exportSVG,
    onWindowResize as threeResize,
    flyToStartNode
} from "./three_setup.js";
import { sendCode, testBackendConnection, getTestFlowGraph, setApiKey, clearApiKey, onStaledKey,
    saveGraph, listGraphs, loadGraph, deleteGraph,
    listApiKeys, createApiKey, revokeApiKey,
    loginUser, registerUser, pollTaskResult,
    getMyProfile, getMySubscription, getPublicSettings } from "./api.js";
import { zoomToNodeById } from "./three_setup.js";

/**
 * DOM Elements
 */
const languageSelect = document.getElementById("language");
const generateBtn = document.getElementById("generateBtn");
const testBtn = document.getElementById("testBtn");
const resetBtn = document.getElementById("resetBtn");
const errorBox = document.getElementById("errorBox");
const loadingOverlay = document.getElementById("loadingOverlay");

// New buttons
const exportBtn = document.getElementById("exportBtn");
const saveBtn = document.getElementById("saveBtn");
const graphsBtn = document.getElementById("graphsBtn");
const settingsBtn = document.getElementById("settingsBtn");

// Panels
const panelOverlay = document.getElementById("panelOverlay");
const graphsPanel = document.getElementById("graphsPanel");
const closeGraphsBtn = document.getElementById("closeGraphsBtn");
const settingsPanel = document.getElementById("settingsPanel");
const closeSettingsBtn = document.getElementById("closeSettingsBtn");

// Save form
const saveForm = document.getElementById("saveForm");
const saveTitleInput = document.getElementById("saveTitleInput");
const saveDescInput = document.getElementById("saveDescInput");
const saveConfirmBtn = document.getElementById("saveConfirmBtn");
const saveCancelBtn = document.getElementById("saveCancelBtn");

// Settings inputs
const apiKeysList = document.getElementById("apiKeysList");
const newKeyName = document.getElementById("newKeyName");
const createKeyBtn = document.getElementById("createKeyBtn");
const newKeyDisplay = document.getElementById("newKeyDisplay");
const saveKeyFileBtn = document.getElementById("saveKeyFileBtn");
const settingsUsername = document.getElementById("settingsUsername");
const signOutBtn = document.getElementById("signOutBtn");

// Auth modal
const authModal = document.getElementById("authModal");
const loginTabBtn = document.getElementById("loginTabBtn");
const registerTabBtn = document.getElementById("registerTabBtn");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const loginEmail = document.getElementById("loginEmail");
const loginPassword = document.getElementById("loginPassword");
const loginSubmitBtn = document.getElementById("loginSubmitBtn");
const loginError = document.getElementById("loginError");
const regUsername = document.getElementById("regUsername");
const regEmail = document.getElementById("regEmail");
const regPassword = document.getElementById("regPassword");
const registerSubmitBtn = document.getElementById("registerSubmitBtn");
const registerError = document.getElementById("registerError");
const useKeyLink = document.getElementById("useKeyLink");
const manualKeySection = document.getElementById("manualKeySection");
const manualKeyInput = document.getElementById("manualKeyInput");
const manualKeySubmit = document.getElementById("manualKeySubmit");

let backendConnected = false;
let sceneReady = false;
let lastRenderResult = null; // tracks last successfully rendered graph

// ----------------------------
// Password Strength Checker
// ----------------------------

const pwRules = {
    len:     { el: document.getElementById("pwRuleLen"),     test: (p) => p.length >= 8 },
    upper:   { el: document.getElementById("pwRuleUpper"),   test: (p) => /[A-Z]/.test(p) },
    lower:   { el: document.getElementById("pwRuleLower"),   test: (p) => /[a-z]/.test(p) },
    digit:   { el: document.getElementById("pwRuleDigit"),   test: (p) => /\d/.test(p) },
    special: { el: document.getElementById("pwRuleSpecial"), test: (p) => /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`]/.test(p) },
};
const pwStrengthFill = document.getElementById("pwStrengthFill");
const pwStrengthLabel = document.getElementById("pwStrengthLabel");
const strengthLabels = ["", "Very Weak", "Weak", "Fair", "Strong", "Very Strong"];

function checkPasswordStrength(password) {
    let score = 0;
    for (const key in pwRules) {
        const rule = pwRules[key];
        const passed = rule.test(password);
        if (rule.el) rule.el.classList.toggle("passed", passed);
        if (passed) score++;
    }
    if (pwStrengthFill) pwStrengthFill.setAttribute("data-score", password ? score : 0);
    if (pwStrengthLabel) {
        pwStrengthLabel.setAttribute("data-score", password ? score : 0);
        pwStrengthLabel.textContent = password ? strengthLabels[score] : "";
    }
    return score;
}

if (regPassword) {
    regPassword.addEventListener("input", () => checkPasswordStrength(regPassword.value));
}

// ----------------------------
// Username Validation Checker
// ----------------------------

const unRules = {
    len:      { el: document.getElementById("unRuleLen"),      test: (u) => u.length >= 3 && u.length <= 64 },
    start:    { el: document.getElementById("unRuleStart"),    test: (u) => /^[a-zA-Z]/.test(u) },
    chars:    { el: document.getElementById("unRuleChars"),    test: (u) => /^[a-zA-Z0-9_\-]+$/.test(u) },
    noDouble: { el: document.getElementById("unRuleNoDouble"), test: (u) => !/[_\-]{2}/.test(u) },
};

function checkUsernameRules(username) {
    let allPassed = true;
    for (const key in unRules) {
        const rule = unRules[key];
        const passed = username.length > 0 ? rule.test(username) : false;
        if (rule.el) rule.el.classList.toggle("passed", passed);
        if (!passed) allPassed = false;
    }
    return allPassed;
}

if (regUsername) {
    regUsername.addEventListener("input", () => checkUsernameRules(regUsername.value.trim()));
}

// ----------------------------
// Helper Functions
// ----------------------------

/**
 * Show error message
 */
let _errorTimer = null;

function showError(message) {
    console.error("❌", message);
    errorBox.textContent = "❌ " + message;
    errorBox.classList.add("show");

    clearTimeout(_errorTimer);
    _errorTimer = setTimeout(() => {
        errorBox.classList.remove("show");
    }, 5000);
}

function showSuccess(message) {
    errorBox.style.background = "rgba(5, 46, 22, 0.95)";
    errorBox.style.borderColor = "rgba(74, 222, 128, 0.46)";
    errorBox.style.color = "#bbf7d0";
    errorBox.textContent = "✅ " + message;
    errorBox.classList.add("show");
    clearTimeout(_errorTimer);
    _errorTimer = setTimeout(() => {
        errorBox.classList.remove("show");
        errorBox.style.cssText = "";
    }, 4000);
}

/**
 * Clear error message
 */
function clearError() {
    errorBox.classList.remove("show");
    errorBox.textContent = "";
}

/**
 * Show loading state
 */
function showLoading(show = true) {
    if (show) {
        loadingOverlay.classList.add("show");
    } else {
        loadingOverlay.classList.remove("show");
    }
}

/**
 * Deterministic node sorting (handles any ID format)
 */
function sortNodesForDeterministicLayout(nodes) {
    return nodes.sort((a, b) => {
        // Nodes without a line number (e.g. START) sort before everything else
        if (a.line == null && b.line == null) {
            const aMatch = a.id.match(/\d+/);
            const bMatch = b.id.match(/\d+/);
            if (aMatch && bMatch) return parseInt(aMatch[0]) - parseInt(bMatch[0]);
            return a.id.localeCompare(b.id);
        }
        if (a.line == null) return -1;
        if (b.line == null) return 1;

        // Primary: ascending line number
        if (a.line !== b.line) return a.line - b.line;

        // Tie-break: creation order via numeric node ID
        const aMatch = a.id.match(/\d+/);
        const bMatch = b.id.match(/\d+/);
        if (aMatch && bMatch) return parseInt(aMatch[0]) - parseInt(bMatch[0]);
        return a.id.localeCompare(b.id);
    });
}

/**
 * Check if graph is too large — warns at 250 nodes but still renders
 */
function checkGraphSize(nodeCount) {
    if (nodeCount > 250) {
        console.warn(`⚠️ Large graph (${nodeCount} nodes). Performance may degrade.`);
        showError(`⚠️ Graph has ${nodeCount} nodes (limit is 250). Display may be slow.`);
        return false;
    }
    if (nodeCount > 80) {
        console.warn(`⚠️ Large graph (${nodeCount} nodes). Layout may be complex.`);
    }
    return true;
}

/**
 * Validate Flow Graph Data
 */
function validateFlowGraph(data) {
    if (!data) {
        throw new Error("No data received from backend");
    }

    const { nodes = [], edges = [], loops = [], conditionals = [] } = data;

    if (!Array.isArray(nodes) || !Array.isArray(edges)) {
        throw new Error("Invalid response format");
    }

    if (nodes.length === 0) {
        throw new Error("No nodes found. Try code with functions or loops.");
    }

    const nodeIds = new Set(nodes.map(n => n.id));
    const validEdges = edges.filter(e => nodeIds.has(e.from) && nodeIds.has(e.to));
    const validLoops = loops.filter(e => nodeIds.has(e.from) && nodeIds.has(e.to));
    const validConditionals = conditionals.filter(
        e => nodeIds.has(e.from) && nodeIds.has(e.to)
    );

    if (validEdges.length < edges.length) {
        const filtered = edges.length - validEdges.length;
        console.warn(`⚠️ Filtered ${filtered} invalid edges`);
    }

    return {
        nodes,
        edges: validEdges,
        loops: validLoops,
        conditionals: validConditionals
    };
}

/**
 * Calculate flow-based layout: parent-centered hierarchical layout.
 * Each branching node fans its children symmetrically beneath it,
 * so branches spread away from their actual parent — not mixed up
 * with unrelated nodes at the same level.
 */
function calculateNodeLayout(nodes, edges) {
    const positions = {};
    if (nodes.length === 0) return positions;

    const X_SPACING = 9;   // generous horizontal spread between siblings
    const Y_SPACING = 7;   // generous vertical separation between levels

    // 1. Build directed adjacency (skip self-loops)
    const childrenOf = {};
    const parentsOf  = {};
    const inDegree   = {};
    nodes.forEach(n => { childrenOf[n.id] = []; parentsOf[n.id] = []; inDegree[n.id] = 0; });
    edges.forEach(e => {
        if (e.from !== e.to && !childrenOf[e.from].includes(e.to)) {
            childrenOf[e.from].push(e.to);
            parentsOf[e.to].push(e.from);
            inDegree[e.to]++;
        }
    });

    // 2. BFS levels — use longest-path to handle convergent edges correctly
    const levels = {};
    const roots = nodes.filter(n => inDegree[n.id] === 0).map(n => n.id);
    if (roots.length === 0) roots.push(nodes[0].id);
    const bfsQueue = [...roots];
    const bfsVis   = new Set(roots);
    roots.forEach(r => { levels[r] = 0; });
    while (bfsQueue.length > 0) {
        const id = bfsQueue.shift();
        for (const child of childrenOf[id]) {
            const proposed = (levels[id] ?? 0) + 1;
            levels[child] = Math.max(levels[child] ?? 0, proposed);
            if (!bfsVis.has(child)) { bfsVis.add(child); bfsQueue.push(child); }
        }
    }
    nodes.forEach(n => { if (levels[n.id] === undefined) levels[n.id] = 0; });

    // 3. Group by level
    const byLevel = {};
    nodes.forEach(n => {
        const lvl = levels[n.id];
        (byLevel[lvl] = byLevel[lvl] || []).push(n.id);
    });

    // 4. Assign X positions top-down, parent-centred
    //    • Root(s) start at x = 0
    //    • For each node, fan its direct children symmetrically around its own x
    //    • Convergent nodes (multiple parents) get the average of parents' x
    //    • After fanning each level, push nodes apart if they would overlap
    const xPos = {};
    roots.forEach((r, i) => { xPos[r] = (i - (roots.length - 1) / 2) * X_SPACING; });

    const sortedLevels = Object.keys(byLevel).map(Number).sort((a, b) => a - b);

    sortedLevels.forEach(lvl => {
        const ids = byLevel[lvl] || [];

        // Derive x for any node that hasn't been placed yet (e.g. convergent nodes)
        ids.forEach(id => {
            if (xPos[id] === undefined) {
                const px = parentsOf[id].filter(p => xPos[p] !== undefined).map(p => xPos[p]);
                xPos[id] = px.length > 0 ? px.reduce((s, x) => s + x, 0) / px.length : 0;
            }
        });

        // Fan each node's children at the next level
        ids.forEach(id => {
            const directKids = childrenOf[id].filter(k => levels[k] === lvl + 1);
            if (directKids.length === 0) return;

            if (directKids.length === 1) {
                // Single child: stack directly below (preserve column alignment)
                if (xPos[directKids[0]] === undefined) xPos[directKids[0]] = xPos[id];
                return;
            }

            // Multiple children: spread symmetrically around parent
            const span = (directKids.length - 1) * X_SPACING;
            directKids.forEach((kid, i) => {
                const proposed = (xPos[id] ?? 0) - span / 2 + i * X_SPACING;
                if (xPos[kid] === undefined) {
                    xPos[kid] = proposed;
                } else {
                    // Convergent child has multiple parents — average the proposals
                    xPos[kid] = (xPos[kid] + proposed) / 2;
                }
            });
        });

        // Resolve collisions at the NEXT level: shift right if nodes overlap
        const nextIds = (byLevel[lvl + 1] || [])
            .filter(id => xPos[id] !== undefined)
            .sort((a, b) => xPos[a] - xPos[b]);
        for (let i = 1; i < nextIds.length; i++) {
            if (xPos[nextIds[i]] < xPos[nextIds[i - 1]] + X_SPACING) {
                xPos[nextIds[i]] = xPos[nextIds[i - 1]] + X_SPACING;
            }
        }
    });

    // 5. Centre the entire graph on x = 0
    const allX = nodes.map(n => xPos[n.id] ?? 0);
    const midX = (Math.min(...allX) + Math.max(...allX)) / 2;
    nodes.forEach(n => { if (xPos[n.id] !== undefined) xPos[n.id] -= midX; });

    // 6. Build final position map
    nodes.forEach(n => {
        positions[n.id] = {
            x: xPos[n.id] ?? 0,
            y: -(levels[n.id] ?? 0) * Y_SPACING,
            z: 0
        };
    });

    return positions;
}

/**
 * Multi-function layout: lay out each function's nodes as its own cluster,
 * then arrange clusters side-by-side horizontally.
 *
 * @param {Array}  nodes          - All nodes from the parse result
 * @param {Array}  intraEdges     - edges + loops + conditionals (intra-function)
 * @param {Object} functionGroups - { funcName: [nodeId, ...] }
 */
function calculateMultiFunctionLayout(nodes, intraEdges, functionGroups) {
    const nodeById = {};
    nodes.forEach(n => { nodeById[n.id] = n; });

    const positions = {};
    const GROUP_X_GAP = 28; // world-units gap between function clusters

    // Sort groups: __toplevel__ first, main second, then alphabetical.
    // Skip groups whose only node is a bare START (no real content).
    const groupNames = Object.keys(functionGroups).sort((a, b) => {
        if (a === '__toplevel__') return -1;
        if (b === '__toplevel__') return 1;
        if (a === 'main')        return -1;
        if (b === 'main')        return 1;
        return a.localeCompare(b);
    }).filter(name => {
        const ids = functionGroups[name] || [];
        if (ids.length === 0) return false;
        // Drop a group that only contains a lone START node with no edges
        if (ids.length === 1) {
            const n = nodeById[ids[0]];
            if (n && (n.label === 'START' || n.label === 'start')) return false;
        }
        return true;
    });

    let currentOffsetX = 0;

    for (const groupName of groupNames) {
        const groupNodeIds = functionGroups[groupName] || [];
        const groupNodes   = groupNodeIds.map(id => nodeById[id]).filter(Boolean);
        if (groupNodes.length === 0) continue;

        // Only edges whose BOTH endpoints are in this group
        const groupNodeSet = new Set(groupNodeIds);
        const groupEdges   = intraEdges.filter(
            e => groupNodeSet.has(e.from) && groupNodeSet.has(e.to)
        );

        // Local hierarchical layout (x centred around 0)
        const local = calculateNodeLayout(groupNodes, groupEdges);

        // Bounding box of this cluster
        const xVals = groupNodes.map(n => local[n.id]?.x ?? 0);
        const minX  = Math.min(...xVals);
        const maxX  = Math.max(...xVals);
        const groupWidth = Math.max(maxX - minX, 8); // minimum width

        // Shift cluster so its left edge sits at currentOffsetX
        const xShift = currentOffsetX - minX;
        groupNodes.forEach(n => {
            const lp = local[n.id] ?? { x: 0, y: 0 };
            positions[n.id] = { x: lp.x + xShift, y: lp.y, z: 0 };
        });

        currentOffsetX += groupWidth + GROUP_X_GAP;
    }

    // Any nodes not placed (e.g. from a missing group) go at origin
    nodes.forEach(n => {
        if (!positions[n.id]) positions[n.id] = { x: 0, y: 0, z: 0 };
    });

    // Centre the whole layout on x = 0
    const allX = Object.values(positions).map(p => p.x);
    if (allX.length > 0) {
        const midX = (Math.min(...allX) + Math.max(...allX)) / 2;
        Object.values(positions).forEach(p => { p.x -= midX; });
    }

    return positions;
}

/**
 * Render Flow Graph
 */
async function renderFlowGraph(result) {
    try {
        if (result.error) {
            showError(result.error);
            if (result.error_line) {
                setErrorDecoration(result.error_line, result.error);
            }
            console.error("Backend error:", result.error);
            return;
        }

        clearErrorDecoration();
        let { nodes, edges, loops, conditionals } = validateFlowGraph(result);

        // Build a set of unused function names for O(1) lookup when rendering nodes
        const unusedNames = new Set(result.unused_functions || []);

        nodes = sortNodesForDeterministicLayout(nodes);

        console.log(`✅ Graph valid: ${nodes.length} nodes, ${edges.length} edges`);
        if (unusedNames.size > 0) {
            console.log(`⚠️ Unused functions detected: ${[...unusedNames].join(", ")}`);
        }

        if (!checkGraphSize(nodes.length)) {
            console.warn("Proceeding with large graph...");
        }

        // Choose layout: multi-function if there are nodes with distinct "func" tags,
        // otherwise fall back to the single flat layout.
        // Layout uses only forward edges (regular + conditional).
        // Loop back-edges are intentionally excluded — they create cycles that
        // corrupt the BFS level assignment, causing nodes to share x=0 and overlap.
        const intraEdges = [...edges, ...conditionals];
        let positions;
        const functionGroups = Object.create(null);
        nodes.forEach(n => {
            const g = n.func || '__toplevel__';
            if (!functionGroups[g]) functionGroups[g] = [];
            functionGroups[g].push(n.id);
        });
        if (Object.keys(functionGroups).length > 1) {
            positions = calculateMultiFunctionLayout(nodes, intraEdges, functionGroups);
        } else {
            positions = calculateNodeLayout(nodes, intraEdges);
        }

        // Build a set of already-colored edge keys to avoid rendering them again as white
        const coloredEdgeKeys = new Set([
            ...loops.map(e => `${e.from}|${e.to}`),
            ...conditionals.map(e => `${e.from}|${e.to}`),
        ]);

        // Track all rendered edges (from|to) to avoid duplicates
        const renderedEdgeKeys = new Set();

        // Build funcName → nodeId map for click-to-zoom in unused panel
        const funcNameToNodeId = {};

        nodes.forEach((node) => {
            const pos = positions[node.id];
            // Detect if this node represents an unused function/method/constructor
            const match = node.label.match(
                /^(?:function|method|constructor|arrow function):\s*(.+)$/i
            );
            const isUnused = match ? unusedNames.has(match[1].trim()) : false;
            if (match) funcNameToNodeId[match[1].trim()] = node.id;

            // Pass loop metadata if present
            const loopInfo = node.loop_type ? {
                type: node.loop_type,
                condition: node.loop_condition || '',
                is_infinite: node.is_infinite || false,
                line: node.line || null
            } : null;

            // Recursion metadata
            const isRecursive = node.recursive || false;
            const recursionType = node.recursion_type || null;

            addNode(node.id, node.label || node.id, pos, isUnused, node.line || null, loopInfo, isRecursive, recursionType);
        });

        edges.forEach(edge => {
            const key = `${edge.from}|${edge.to}`;
            if (!coloredEdgeKeys.has(key) && !renderedEdgeKeys.has(key)) {
                renderedEdgeKeys.add(key);
                addEdge(edge.from, edge.to, { color: 0xffffff });
            }
        });

        loops.forEach(edge => {
            const key = `${edge.from}|${edge.to}`;
            if (!renderedEdgeKeys.has(key)) {
                renderedEdgeKeys.add(key);
                addEdge(edge.from, edge.to, { color: 0x22c55e });
            }
        });

        conditionals.forEach(edge => {
            const key = `${edge.from}|${edge.to}`;
            if (!renderedEdgeKeys.has(key)) {
                renderedEdgeKeys.add(key);
                addEdge(edge.from, edge.to, { color: 0xf59e0b });
            }
        });

        const callEdges = result.call_edges || [];
        callEdges.forEach(edge => {
            const key = `${edge.from}|${edge.to}`;
            if (!renderedEdgeKeys.has(key)) {
                renderedEdgeKeys.add(key);
                addEdge(edge.from, edge.to, { color: 0x06b6d4 }); // cyan — inter-procedural jump
            }
        });

        updateScene();
        fitCameraToGraph();
        updateUnusedPanel(result.unused_functions || [], funcNameToNodeId);
        updateRecursionPanel(result.recursion || {});
        lastRenderResult = result;
        saveBtn.style.display = '';
        exportBtn.style.display = '';
        console.log("🎨 Render complete:", getSceneInfo());

        // On mobile, auto-switch to the graph tab so user sees the result
        if (window._mobileTabSwitchToGraph) window._mobileTabSwitchToGraph();

    } catch (error) {
        console.error("❌ Render error:", error);
        showError(error.message);
    }
}

/**
 * Update the Unused Functions panel in the sidebar.
 * Shows a warning list when any unused functions are detected.
 * Items are clickable — zooms the camera to that node in the 3D scene.
 */
function updateUnusedPanel(unusedFunctions, funcNameToNodeId = {}) {
    const panel = document.getElementById("unusedPanel");
    if (!panel) return;

    if (!unusedFunctions || unusedFunctions.length === 0) {
        panel.classList.remove("show");
        return;
    }

    const countEl = document.getElementById("unusedCount");
    const listEl  = document.getElementById("unusedList");
    if (countEl) countEl.textContent = unusedFunctions.length;
    if (listEl) {
        listEl.innerHTML = unusedFunctions
            .map(fn => `<div class="unused-item unused-item-clickable" data-fn="${escapeHtml(fn)}">\u26A0\uFE0F ${escapeHtml(fn)}</div>`)
            .join("");
        listEl.querySelectorAll('.unused-item-clickable').forEach(item => {
            item.addEventListener('click', () => {
                const nodeId = funcNameToNodeId[item.dataset.fn];
                if (nodeId) zoomToNodeById(nodeId);
            });
        });
    }
    panel.classList.add("show");
}

/**
 * Update the Recursion panel in the sidebar.
 * Shows detected direct and mutual recursion.
 */
function updateRecursionPanel(recursionInfo) {
    const panel = document.getElementById("recursionPanel");
    if (!panel) return;

    const direct = recursionInfo.direct || [];
    const mutual = recursionInfo.mutual || [];

    if (direct.length === 0 && mutual.length === 0) {
        panel.classList.remove("show");
        return;
    }

    const listEl = document.getElementById("recursionList");
    if (listEl) {
        let html = '';
        direct.forEach(fn => {
            html += `<div class="recursion-item">\u21BB <strong>${escapeHtml(fn)}</strong> <span style="opacity:0.7">(direct)</span></div>`;
        });
        mutual.forEach(fn => {
            html += `<div class="recursion-item">\u21BB <strong>${escapeHtml(fn)}</strong> <span style="opacity:0.7">(mutual)</span></div>`;
        });
        listEl.innerHTML = html;
    }

    const countEl = document.getElementById("recursionCount");
    if (countEl) countEl.textContent = direct.length + mutual.length;

    panel.classList.add("show");
}

// ----------------------------
// Event Listeners
// ----------------------------

/**
 * Initialize App
 */
async function initApp() {
    console.log("🚀 CodeFlow3D Initializing...");

    // Recover from stale stored key (e.g. after server DB wipe or key revocation)
    onStaledKey(() => {
        clearApiKey();
        showAuthModal();
    });

    // Gate: show auth modal if no API key is stored
    if (!localStorage.getItem('cf_api_key')) {
        showAuthModal();
        return;
    }

    let sceneCheckAttempts = 0;
    const checkScene = () => {
        if (getSceneInfo().sceneReady) {
            sceneReady = true;
            console.log("✓ Scene ready");
        } else if (sceneCheckAttempts < 10) {
            sceneCheckAttempts++;
            setTimeout(checkScene, 100);
        } else {
            console.warn("⚠️ Scene initialization timed out");
        }
    };
    checkScene();

    console.log("🔍 Testing backend...");
    backendConnected = await testBackendConnection();

    if (!backendConnected) {
        console.warn("⚠️ Backend offline");
        generateBtn.disabled = true;
        generateBtn.textContent = "⚠️ Backend offline";
        showError("Backend is offline. If deployed, wait ~30s for Render free tier to wake up and refresh the page.");
    } else {
        console.log("✅ Backend connected");
        clearError();

        // Ensure username is stored (covers manual key entry & legacy sessions)
        if (!localStorage.getItem('cf_username') || localStorage.getItem('cf_username') === '—') {
            try {
                const profile = await getMyProfile();
                if (profile.username) localStorage.setItem('cf_username', profile.username);
            } catch (_) { /* non-critical */ }
        }
    }

    let editorCheckAttempts = 0;
    const checkEditor = () => {
        if (isEditorReady()) {
            console.log("✓ Editor ready");
        } else if (editorCheckAttempts < 20) {
            editorCheckAttempts++;
            setTimeout(checkEditor, 100);
        } else {
            console.warn("⚠️ Editor initialization timed out");
        }
    };
    checkEditor();

    // Node click → jump to source line in editor
    document.addEventListener('nodeClicked', (e) => {
        if (e.detail && e.detail.line) {
            revealLine(e.detail.line);
        }
    });

    console.log("✅ App initialization complete");

    // Show onboarding tour for first-time users
    _maybeShowTour();
}

/**
 * Handle Language Change
 */
languageSelect.addEventListener("change", () => {
    const lang = languageSelect.value;
    console.log(`🔤 Language: ${lang}`);
    clearError();
    setLanguage(lang);
});

/**
 * Handle Test Button
 */
testBtn.addEventListener("click", async () => {
    console.log("🧪 Testing rendering with dummy data...");
    clearError();
    showLoading(true);
    testBtn.disabled = true;

    try {
        clearScene();
        updateUnusedPanel([]);
        const testData = await getTestFlowGraph();
        await renderFlowGraph(testData);
    } catch (err) {
        console.error("❌ Test error:", err);
        showError(err.message || "Test failed");
    } finally {
        showLoading(false);
        testBtn.disabled = false;
    }
});

/**
 * Handle Reset Camera Button — re-fits camera to the current graph
 */
resetBtn.addEventListener("click", () => {
    console.log("🎥 Fit camera to graph...");
    fitCameraToGraph();
});

/**
 * Handle Find Start Button — flies to the START node
 */
const findStartBtn = document.getElementById("findStartBtn");
if (findStartBtn) {
    findStartBtn.addEventListener("click", () => {
        if (!flyToStartNode()) {
            showError("No START node found in the current graph.");
        }
    });
}

/**
 * Legend panel toggle
 */
const legendToggle = document.getElementById("legendToggle");
const legendPanel = document.getElementById("legendPanel");
if (legendToggle && legendPanel) {
    legendToggle.addEventListener("click", () => {
        const collapsed = legendPanel.classList.toggle("collapsed");
        legendToggle.textContent = collapsed ? "Legend ▸" : "Legend ▾";
    });
}

/**
 * Handle Generate Button
 */
generateBtn.addEventListener("click", async () => {
    const language = languageSelect.value;
    const code = getEditorCode();

    if (!code.trim()) {
        showError("Write some code first");
        return;
    }

    if (!backendConnected) {
        showError("Backend offline. If deployed, wait ~30s for Render free tier to wake up and refresh the page.");
        return;
    }

    if (!sceneReady) {
        showError("Scene initializing, try again");
        return;
    }

    generateBtn.disabled = true;
    generateBtn.textContent = "⏳ Analyzing...";
    clearError();
    showLoading(true);

    try {
        clearScene();
        updateUnusedPanel([]);

        console.group("📊 Analyzing");
        console.log("Language:", language);
        console.log("Code length:", code.length, "characters");
        console.groupEnd();

        const result = await sendCode(language, code);

        // Handle async dispatch: backend returns status="pending" for large analyses
        if (result.status === "pending" && result.task_id) {
            generateBtn.textContent = "⏳ Processing large analysis...";
            const asyncResult = await pollTaskResult(result.task_id, (status, attempt, max) => {
                generateBtn.textContent = `⏳ ${status === "processing" ? "Analyzing" : "Queued"}... (${attempt}/${max})`;
            });

            if (asyncResult.error) {
                showError(asyncResult.error);
                return;
            }

            clearErrorDecoration();
            await renderFlowGraph(asyncResult);
            return;
        }

        if (result.error) {
            showError(result.error);
            if (result.error_line) {
                setErrorDecoration(result.error_line, result.error);
            }
            return;
        }

        clearErrorDecoration();
        await renderFlowGraph(result);

    } catch (err) {
        console.error("🔴 Fatal error:", err);
        showError(err.message || "Unknown error occurred");
    } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = "Generate Flow Map";
        showLoading(false);
    }
});

// ----------------------------
// Auth Modal
// ----------------------------

function showAuthModal() {
    authModal.classList.add("show");
    // Reset to login view
    const authContainer = document.getElementById("authContainer");
    authContainer.classList.remove("active");
    loginEmail.focus();
}

function hideAuthModal() {
    authModal.classList.remove("show");
    // Show tour for first-time users after they've authenticated
    _maybeShowTour();
}

function switchAuthTab(tab) {
    const authContainer = document.getElementById("authContainer");
    if (tab === 'register') {
        authContainer.classList.add("active");
    } else {
        authContainer.classList.remove("active");
    }
}

loginTabBtn.addEventListener("click", () => switchAuthTab("login"));
registerTabBtn.addEventListener("click", () => switchAuthTab("register"));

loginSubmitBtn.addEventListener("click", async () => {
    const login = loginEmail.value.trim();
    const pass = loginPassword.value;
    if (!login || !pass) { loginError.textContent = "Fill in all fields."; return; }
    loginSubmitBtn.disabled = true;
    loginSubmitBtn.textContent = "Signing in...";
    loginError.textContent = "";
    try {
        const { api_key, username } = await loginUser(login, pass);
        setApiKey(api_key);
        localStorage.setItem('cf_username', username);
        hideAuthModal();
        await initApp();
    } catch (err) {
        loginError.textContent = err.message;
    } finally {
        loginSubmitBtn.disabled = false;
        loginSubmitBtn.textContent = "Sign In";
    }
});

// Allow Enter key to submit login
loginPassword.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loginSubmitBtn.click();
});

registerSubmitBtn.addEventListener("click", async () => {
    const user = regUsername.value.trim();
    const email = regEmail.value.trim();
    const pass = regPassword.value;
    if (!user || !email || !pass) { registerError.textContent = "Fill in all fields."; return; }

    // Username validation — all rules must pass
    if (!checkUsernameRules(user)) { registerError.textContent = "Please meet all username requirements."; return; }

    // Email format validation
    if (!/^[^\s@]+@[^\s@]+\.[a-zA-Z]{2,}$/.test(email)) { registerError.textContent = "Please enter a valid email address."; return; }

    // Password strength — all 5 rules must pass
    const score = checkPasswordStrength(pass);
    if (score < 5) { registerError.textContent = "Please meet all password requirements."; return; }

    registerSubmitBtn.disabled = true;
    registerSubmitBtn.textContent = "Creating account...";
    registerError.textContent = "";
    try {
        const { api_key, username } = await registerUser(user, email, pass);
        setApiKey(api_key);
        localStorage.setItem('cf_username', username);
        hideAuthModal();
        await initApp();
    } catch (err) {
        registerError.textContent = err.message;
    } finally {
        registerSubmitBtn.disabled = false;
        registerSubmitBtn.textContent = "Create Account";
    }
});

regPassword.addEventListener("keydown", (e) => {
    if (e.key === "Enter") registerSubmitBtn.click();
});

useKeyLink.addEventListener("click", (e) => {
    e.preventDefault();
    manualKeySection.classList.toggle("auth-form-hidden");
    if (!manualKeySection.classList.contains("auth-form-hidden")) manualKeyInput.focus();
});

manualKeySubmit.addEventListener("click", async () => {
    const val = manualKeyInput.value.trim();
    if (!val) { manualKeyInput.focus(); return; }
    setApiKey(val);
    // Fetch and store username for this key
    try {
        const profile = await getMyProfile();
        if (profile.username) localStorage.setItem('cf_username', profile.username);
    } catch (_) { /* will show '—' if fetch fails */ }
    hideAuthModal();
    await initApp();
});

manualKeyInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") manualKeySubmit.click();
});

// ----------------------------
// Panel Management
// ----------------------------

function openPanel(panel) {
    panelOverlay.classList.add("show");
    panel.classList.add("open");
}

function closeAllPanels() {
    panelOverlay.classList.remove("show");
    graphsPanel.classList.remove("open");
    settingsPanel.classList.remove("open");
}

panelOverlay.addEventListener("click", closeAllPanels);
closeGraphsBtn.addEventListener("click", closeAllPanels);
closeSettingsBtn.addEventListener("click", closeAllPanels);

// --- Export SVG ---

exportBtn.addEventListener("click", () => {
    exportSVG('codeflow-graph.svg');
});

// --- Save Graph form ---

saveBtn.addEventListener("click", () => {
    saveTitleInput.value = "";
    saveDescInput.value = "";
    saveForm.classList.add("show");
    saveTitleInput.focus();
});

saveCancelBtn.addEventListener("click", () => {
    saveForm.classList.remove("show");
});

saveConfirmBtn.addEventListener("click", async () => {
    const title = saveTitleInput.value.trim();
    if (!title) { saveTitleInput.focus(); return; }
    if (!lastRenderResult) return;
    try {
        saveConfirmBtn.disabled = true;
        saveConfirmBtn.textContent = "Saving...";
        await saveGraph(
            title,
            saveDescInput.value.trim() || null,
            getEditorCode(),
            languageSelect.value,
            {
                nodes: lastRenderResult.nodes,
                edges: lastRenderResult.edges,
                loops: lastRenderResult.loops,
                conditionals: lastRenderResult.conditionals,
                call_edges: lastRenderResult.call_edges || [],
                unused_functions: lastRenderResult.unused_functions || [],
            }
        );
        saveForm.classList.remove("show");
        showSuccess(`Graph "${title}" saved!`);
    } catch (err) {
        showError("Save failed: " + err.message);
    } finally {
        saveConfirmBtn.disabled = false;
        saveConfirmBtn.textContent = "Save";
    }
});

// --- Graphs panel ---

async function refreshGraphsList() {
    const listEl = document.getElementById("graphsList");
    listEl.innerHTML = '<div class="graphs-empty">Loading...</div>';
    try {
        const data = await listGraphs();
        const graphs = data.graphs || [];
        if (graphs.length === 0) {
            listEl.innerHTML = '<div class="graphs-empty">No saved graphs yet. Generate a graph and click 💾 Save.</div>';
            return;
        }
        listEl.innerHTML = graphs.map(g => `
            <div class="graph-item">
                <div class="graph-item-title">${escapeHtml(g.title)}</div>
                <div class="graph-item-meta">
                    <span>${g.language || '—'}</span>
                    <span>${new Date(g.created_at).toLocaleDateString()}</span>
                </div>
                <div class="graph-item-actions">
                    <button class="graph-item-btn graph-item-btn-load" data-id="${g.id}">Load</button>
                    <button class="graph-item-btn graph-item-btn-delete" data-id="${g.id}">🗑</button>
                </div>
            </div>
        `).join('');

        listEl.querySelectorAll('.graph-item-btn-load').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = Number(btn.dataset.id);
                try {
                    btn.disabled = true; btn.textContent = '...';
                    const g = await loadGraph(id);
                    setLanguage(g.language);
                    languageSelect.value = g.language;
                    setEditorCode(g.code);
                    closeAllPanels();
                    clearScene();
                    updateUnusedPanel([]);
                    await renderFlowGraph(g.graph_data);
                } catch (err) {
                    showError("Load failed: " + err.message);
                } finally {
                    btn.disabled = false; btn.textContent = 'Load';
                }
            });
        });

        listEl.querySelectorAll('.graph-item-btn-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = Number(btn.dataset.id);
                if (!confirm('Delete this saved graph?')) return;
                try {
                    btn.disabled = true;
                    await deleteGraph(id);
                    await refreshGraphsList();
                } catch (err) {
                    showError("Delete failed: " + err.message);
                    btn.disabled = false;
                }
            });
        });
    } catch (err) {
        listEl.innerHTML = `<div class="graphs-empty">Failed to load graphs: ${escapeHtml(err.message)}</div>`;
    }
}

graphsBtn.addEventListener("click", async () => {
    openPanel(graphsPanel);
    await refreshGraphsList();
});

// --- Settings panel ---

async function refreshApiKeysList() {
    apiKeysList.innerHTML = '<div class="graphs-empty" style="padding:8px 0">Loading...</div>';
    try {
        const data = await listApiKeys();
        const keys = (data.api_keys || []).filter(k => k.is_active);
        if (keys.length === 0) {
            apiKeysList.innerHTML = '<div class="graphs-empty" style="padding:8px 0">No active API keys.</div>';
            return;
        }
        apiKeysList.innerHTML = keys.map(k => `
            <div class="api-key-item">
                <div class="api-key-item-info">
                    <div class="api-key-item-name">${escapeHtml(k.name || 'Unnamed')}</div>
                    <div class="api-key-item-prefix">${escapeHtml(k.key_prefix)}…</div>
                </div>
                <button class="api-key-revoke-btn" data-id="${k.id}">Revoke</button>
            </div>
        `).join('');
        apiKeysList.querySelectorAll('.api-key-revoke-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Revoke this API key? This cannot be undone.')) return;
                try {
                    btn.disabled = true;
                    await revokeApiKey(Number(btn.dataset.id));
                    await refreshApiKeysList();
                } catch (err) {
                    showError("Revoke failed: " + err.message);
                    btn.disabled = false;
                }
            });
        });
    } catch (err) {
        apiKeysList.innerHTML = `<div class="graphs-empty" style="padding:8px 0">Failed to load keys: ${escapeHtml(err.message)}</div>`;
    }
}

settingsBtn.addEventListener("click", async () => {
    const username = localStorage.getItem('cf_username') || '—';
    settingsUsername.textContent = username;
    newKeyDisplay.classList.remove("show");
    saveKeyFileBtn.style.display = "none";
    _lastCreatedKey = null;
    openPanel(settingsPanel);
    await refreshApiKeysList();
    await refreshSubscriptionInfo();
});

signOutBtn.addEventListener("click", () => {
    if (!confirm('Sign out? You will need to sign in again to use the app.')) return;
    localStorage.removeItem('cf_api_key');
    localStorage.removeItem('cf_username');
    closeAllPanels();
    showAuthModal();
});

// --- Subscription Info & Upgrade ---

async function refreshSubscriptionInfo() {
    const subInfoEl = document.getElementById("subscriptionInfo");
    const upgradeSectionEl = document.getElementById("upgradeSection");
    if (!subInfoEl || !upgradeSectionEl) return;

    subInfoEl.innerHTML = '<div style="color:var(--muted);font-size:12px">Loading...</div>';
    upgradeSectionEl.innerHTML = '';

    try {
        const [sub, settings] = await Promise.all([
            getMySubscription(),
            getPublicSettings()
        ]);

        const planLabels = { free: "Free", pro: "Pro", enterprise: "Enterprise" };
        const planColors = { free: "#94a3b8", pro: "#f59e0b", enterprise: "#a855f7" };
        const currentPlan = sub.plan || "free";

        subInfoEl.innerHTML = `
            <div class="sub-current-plan">
                <span class="sub-plan-badge" style="background:${planColors[currentPlan] || '#94a3b8'}">${planLabels[currentPlan] || currentPlan}</span>
                <span class="sub-plan-detail">${sub.requests_per_day} requests/day</span>
            </div>
            <div class="sub-usage">
                <div class="sub-usage-bar-track">
                    <div class="sub-usage-bar-fill" style="width:${Math.min(100, (sub.requests_used_today / sub.requests_per_day) * 100)}%"></div>
                </div>
                <span class="sub-usage-text">${sub.requests_used_today} / ${sub.requests_per_day} used today</span>
            </div>
        `;

        // Build plan pricing cards + upgrade section
        const plans = [
            { key: "free", label: "Free", price: settings.plan_price_free || "0" },
            { key: "pro", label: "Pro", price: settings.plan_price_pro || "19" },
            { key: "enterprise", label: "Enterprise", price: settings.plan_price_enterprise || "99" },
        ];

        const contactEmail = settings.contact_email || "admin@codeflow3d.com";
        const upgradeInstructions = settings.upgrade_instructions || "Contact admin to upgrade your plan.";

        upgradeSectionEl.innerHTML = `
            <div class="upgrade-title">Upgrade Plan</div>
            <div class="upgrade-plans">
                ${plans.map(p => `
                    <div class="upgrade-plan-card ${p.key === currentPlan ? 'upgrade-plan-current' : ''}">
                        <div class="upgrade-plan-name">${escapeHtml(p.label)}</div>
                        <div class="upgrade-plan-price">$${escapeHtml(p.price)}<span class="upgrade-plan-period">/mo</span></div>
                        ${p.key === currentPlan ? '<div class="upgrade-plan-tag">Current</div>' : ''}
                    </div>
                `).join('')}
            </div>
            <div class="upgrade-instructions">
                <p>${escapeHtml(upgradeInstructions)}</p>
                <a href="mailto:${escapeHtml(contactEmail)}?subject=Plan%20Upgrade%20Request&body=Username:%20${encodeURIComponent(localStorage.getItem('cf_username') || '')}%0ACurrent%20Plan:%20${encodeURIComponent(currentPlan)}%0ADesired%20Plan:%20" class="upgrade-email-link">
                    📧 ${escapeHtml(contactEmail)}
                </a>
            </div>
        `;
    } catch (err) {
        subInfoEl.innerHTML = `<div style="color:#f87171;font-size:12px">Failed to load subscription info</div>`;
        console.error("Subscription info error:", err);
    }
}

let _lastCreatedKey = null; // Temporarily holds raw key for save-to-file

createKeyBtn.addEventListener("click", async () => {
    const name = newKeyName.value.trim();
    if (!name) { newKeyName.focus(); return; }
    try {
        createKeyBtn.disabled = true;
        const data = await createApiKey(name);
        _lastCreatedKey = { name, api_key: data.api_key };
        newKeyDisplay.textContent = `⚠️ Save this key — shown once:\n${data.api_key}`;
        newKeyDisplay.classList.add("show");
        saveKeyFileBtn.style.display = "";
        newKeyName.value = "";
        await refreshApiKeysList();
    } catch (err) {
        showError("Create key failed: " + err.message);
    } finally {
        createKeyBtn.disabled = false;
    }
});

saveKeyFileBtn.addEventListener("click", () => {
    if (!_lastCreatedKey) return;
    const payload = {
        service: "CodeFlow3D",
        key_name: _lastCreatedKey.name,
        api_key: _lastCreatedKey.api_key,
        created_at: new Date().toISOString(),
        note: "Keep this file safe. The API key cannot be retrieved again."
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `codeflow3d-api-key-${_lastCreatedKey.name.replace(/\s+/g, '-').toLowerCase()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showSuccess("API key saved to file!");
});

// --- Utility ---

function escapeHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/**
 * Cleanup on page unload
 */
window.addEventListener("beforeunload", () => {
    console.log("👋 Cleaning up...");
    dispose();
});

/**
 * Initialize on DOM ready
 */
document.addEventListener("DOMContentLoaded", initApp);

/* ─── Panel resizer (drag to resize + collapse) ─────────────────────────── */
(function initResizer() {
    const resizer     = document.getElementById("panelResizer");
    const editorSec   = document.getElementById("editorSection");
    const collapseBtn = document.getElementById("resizerCollapseBtn");
    if (!resizer || !editorSec || !collapseBtn) return;

    const container = editorSec.parentElement;
    let dragging    = false;
    let startX      = 0;
    let startWidth  = 0;

    // ── Drag start ────────────────────────────────────────────────────────
    resizer.addEventListener("mousedown", (e) => {
        if (e.target === collapseBtn) return; // let button handle its own click
        e.preventDefault();
        e.stopPropagation(); // prevent Monaco keyboard handler from receiving this
        dragging   = true;
        startX     = e.clientX;
        startWidth = editorSec.getBoundingClientRect().width;
        resizer.classList.add("dragging");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
    });

    document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        const delta        = e.clientX - startX;
        const containerW   = container.getBoundingClientRect().width;
        const newWidth     = Math.max(200, Math.min(containerW * 0.80, startWidth + delta));
        editorSec.style.width = newWidth + "px";
        // If it was collapsed, un-collapse on drag out
        if (editorSec.classList.contains("collapsed")) {
            editorSec.classList.remove("collapsed");
        }
        // Notify Three.js that the canvas may have grown
        requestAnimationFrame(threeResize);
    });

    document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        resizer.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
    });

    // ── Collapse / expand button ──────────────────────────────────────────
    collapseBtn.addEventListener("click", () => {
        const isCollapsed = editorSec.classList.toggle("collapsed");
        collapseBtn.title = isCollapsed ? "Expand editor" : "Collapse editor";
        // Restore last explicit width when expanding
        if (!isCollapsed && !editorSec.style.width) {
            editorSec.style.width = "38%";
        }
        // Let the CSS transition finish (~280ms) before telling Three.js to resize
        setTimeout(threeResize, 300);
    });
})();

/* ─── Mobile tab bar ─────────────────────────────────────────────────────── */
(function initMobileTabs() {
    const tabBar     = document.getElementById("mobileTabBar");
    const tabEditor  = document.getElementById("tabEditorBtn");
    const tabGraph   = document.getElementById("tabGraphBtn");
    if (!tabBar) return;

    function switchTab(tab) {
        document.body.setAttribute("data-mobile-tab", tab);
        tabEditor.classList.toggle("active", tab === "editor");
        tabGraph.classList.toggle("active",  tab === "graph");
        // Remove notification dot when graph tab is viewed
        if (tab === "graph") {
            tabGraph.classList.remove("has-graph");
            // Force Three.js to re-fit because canvas was hidden during render
            setTimeout(threeResize, 50);
        }
    }

    tabBar.addEventListener("click", e => {
        const btn = e.target.closest(".mobile-tab");
        if (!btn) return;
        switchTab(btn.dataset.tab);
    });

    // Start on editor tab
    switchTab("editor");

    // Expose so renderFlowGraph can auto-switch to graph tab on mobile
    window._mobileTabSwitchToGraph = () => {
        if (window.innerWidth <= 700) {
            tabGraph.classList.add("has-graph");
            switchTab("graph");
        }
    };
})();

// ----------------------------
// Debug Utilities
// ----------------------------

window.testFlowGraph = async () => {
    console.log("🧪 Running test...");
    clearScene();
    const data = await getTestFlowGraph();
    await renderFlowGraph(data);
};

window.showSceneInfo = () => {
    console.table(getSceneInfo());
};

window.showCodeLength = () => {
    console.log("Code length:", getEditorCode().length);
};

window.resetView = () => {
    resetCamera();
};

// ─── Onboarding Tour ──────────────────────────────────────────────────────────

const TOUR_STEPS = [
    {
        target: null, // welcome — no highlight
        title: "Welcome to CodeFlow3D! 👋",
        body: "This tool turns your source code into an <strong>interactive 3D control flow graph</strong>. Functions, loops, branches — all visualized as a navigable map.<br><br>Let's take a quick tour to get you started.",
        position: "center"
    },
    {
        target: "#editor",
        title: "① Write or Paste Code",
        body: "This is the <strong>code editor</strong> (powered by Monaco — same as VS Code). Paste your code here, or write from scratch. It supports syntax highlighting for all supported languages.",
        position: "right",
        mobileTab: "editor"
    },
    {
        target: "#language",
        title: "② Pick Your Language",
        body: "Select the programming language of your code: <strong>C, C++, Python, Java, JavaScript</strong>, or TypeScript. This tells the parser how to analyze it.",
        position: "below"
    },
    {
        target: "#generateBtn",
        title: "③ Generate the Flow Map",
        body: "Click <strong>Generate Flow Map</strong> to send your code for analysis. The backend parses it and builds a control flow graph — nodes for each block, edges for the execution paths.",
        position: "below"
    },
    {
        target: "#three-canvas",
        title: "④ Explore the 3D Graph",
        body: window.innerWidth <= 700
            ? "Your code's flow appears here as an interactive 3D graph.<br><br><strong>Controls:</strong><br>• <kbd>One-finger drag</kbd> — Pan the view<br>• <kbd>Pinch</kbd> — Zoom in/out<br>• <kbd>Two-finger drag</kbd> — Rotate<br>• <kbd>Tap a node</kbd> — Zoom to it & jump to source line<br>• <kbd>Long-press & drag a node</kbd> — Reposition it"
            : "Your code's flow appears here as an interactive 3D graph.<br><br><strong>Controls:</strong><br>• <kbd>Left-click drag</kbd> — Pan the view<br>• <kbd>Scroll</kbd> — Zoom in/out<br>• <kbd>Right-click drag</kbd> — Rotate<br>• <kbd>Click a node</kbd> — Zoom to it & jump to source line<br>• <kbd>Drag a node</kbd> — Reposition it",
        position: window.innerWidth <= 700 ? "center" : "left",
        mobileTab: "graph"
    },
    {
        target: "#findStartBtn",
        title: "⑤ Find the Start Node",
        body: "Lost in a big graph? Click <strong>🟢 Start</strong> to fly the camera straight to the entry point. The START node is larger and has a green glow ring so you can spot it easily.",
        position: "below"
    },
    {
        target: "#resetBtn",
        title: "⑥ Reset the Camera",
        body: "Click <strong>🎥 Reset</strong> to zoom out and fit the entire graph back into view. Useful after zooming deep into a section.",
        position: "below"
    },
    {
        target: "#legendToggle",
        title: "⑦ Node Legend",
        body: "Click <strong>Legend</strong> to see what each node color means — green for START, blue for functions, purple for loops, amber for conditionals, red for returns, and more.",
        position: "left",
        mobileTab: "graph"
    },
    {
        target: "#settingsBtn",
        title: "⑧ Settings & API Keys",
        body: "Manage your account, view your subscription plan, and create or revoke API keys here. You can also sign out from the settings panel.",
        position: "below"
    },
    {
        target: "#graphsBtn",
        title: "⑨ Save & Load Graphs",
        body: "After generating a graph, click <strong>💾 Save</strong> (appears after generation) to keep it. Click <strong>📂 Graphs</strong> to browse and reload your saved graphs anytime.",
        position: "below"
    },
    {
        target: null,
        title: "You're All Set! 🚀",
        body: "That's everything you need to start. Paste some code, hit <strong>Generate Flow Map</strong>, and explore your code in 3D.<br><br>You can replay this tour anytime by clicking the <strong>❓ Help</strong> button in the top bar.",
        position: "center"
    }
];

let _tourStep = 0;
const _tourOverlay   = document.getElementById("tourOverlay");
const _tourCard      = document.getElementById("tourCard");
const _tourSpotlight = document.getElementById("tourSpotlight");
const _tourTitle     = document.getElementById("tourTitle");
const _tourBody      = document.getElementById("tourBody");
const _tourIndicator = document.getElementById("tourStepIndicator");
const _tourNextBtn   = document.getElementById("tourNextBtn");
const _tourBackBtn   = document.getElementById("tourBackBtn");
const _tourSkipBtn   = document.getElementById("tourSkipBtn");

function _renderTourStep() {
    const step = TOUR_STEPS[_tourStep];
    const totalSteps = TOUR_STEPS.length;

    // Step dots
    _tourIndicator.innerHTML = TOUR_STEPS.map((_, i) => {
        const cls = i < _tourStep ? "tour-step-dot done" : (i === _tourStep ? "tour-step-dot active" : "tour-step-dot");
        return `<span class="${cls}"></span>`;
    }).join("");

    _tourTitle.textContent = step.title;
    // On mobile, regenerate body text for steps that have dynamic content
    if (typeof step.body === "function") {
        _tourBody.innerHTML = step.body();
    } else {
        _tourBody.innerHTML = step.body;
    }

    // Button labels
    _tourBackBtn.style.display = _tourStep === 0 ? "none" : "";
    _tourNextBtn.textContent = _tourStep === totalSteps - 1 ? "Get Started" : "Next";
    _tourSkipBtn.style.display = _tourStep === totalSteps - 1 ? "none" : "";

    // On mobile, switch to the correct tab so the target element is visible
    if (window.innerWidth <= 700 && step.mobileTab) {
        const tabEditor = document.getElementById("tabEditorBtn");
        const tabGraph  = document.getElementById("tabGraphBtn");
        document.body.setAttribute("data-mobile-tab", step.mobileTab);
        if (tabEditor) tabEditor.classList.toggle("active", step.mobileTab === "editor");
        if (tabGraph)  tabGraph.classList.toggle("active",  step.mobileTab === "graph");
        if (step.mobileTab === "graph") {
            setTimeout(threeResize, 50);
        }
    }

    // Spotlight + card positioning
    const target = step.target ? document.querySelector(step.target) : null;

    if (!target || step.position === "center") {
        // Center the card, hide spotlight
        _tourSpotlight.style.display = "none";
        _tourCard.style.left = "50%";
        _tourCard.style.top = "50%";
        _tourCard.style.transform = "translate(-50%, -50%)";
        return;
    }

    _tourSpotlight.style.display = "block";
    _tourCard.style.transform = "";

    const rect = target.getBoundingClientRect();
    const pad = 8;

    _tourSpotlight.style.left   = (rect.left - pad) + "px";
    _tourSpotlight.style.top    = (rect.top - pad) + "px";
    _tourSpotlight.style.width  = (rect.width + pad * 2) + "px";
    _tourSpotlight.style.height = (rect.height + pad * 2) + "px";

    // Position card relative to spotlight, always clamped inside viewport
    const cardW = 370;
    const cardH = _tourCard.offsetHeight || 280;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const margin = 16;

    let cardLeft, cardTop;

    if (step.position === "right") {
        cardLeft = rect.right + 20;
        cardTop  = rect.top;
    } else if (step.position === "left") {
        cardLeft = rect.left - cardW - 20;
        cardTop  = rect.top;
    } else { // "below"
        cardLeft = rect.left;
        cardTop  = rect.bottom + 16;
    }

    // If card would go below viewport, place it above the target instead
    if (cardTop + cardH > vh - margin) {
        cardTop = rect.top - cardH - 16;
    }
    // If still off-screen (above viewport), just pin near top
    if (cardTop < margin) {
        cardTop = margin;
    }

    // Horizontal clamping
    cardLeft = Math.max(margin, Math.min(cardLeft, vw - cardW - margin));

    _tourCard.style.left = cardLeft + "px";
    _tourCard.style.top  = cardTop + "px";
}

function startTour() {
    _tourStep = 0;
    _tourOverlay.classList.add("show");
    _renderTourStep();
}

function endTour() {
    _tourOverlay.classList.remove("show");
    localStorage.setItem("cf_tour_done", "1");
}

_tourNextBtn.addEventListener("click", () => {
    if (_tourStep >= TOUR_STEPS.length - 1) {
        endTour();
    } else {
        _tourStep++;
        _renderTourStep();
    }
});

_tourBackBtn.addEventListener("click", () => {
    if (_tourStep > 0) {
        _tourStep--;
        _renderTourStep();
    }
});

_tourSkipBtn.addEventListener("click", endTour);

// Help button — always available
const helpBtn = document.getElementById("helpBtn");
if (helpBtn) {
    helpBtn.addEventListener("click", startTour);
}

// Auto-show tour on first visit (after auth is done)
function _maybeShowTour() {
    if (!localStorage.getItem("cf_tour_done") && localStorage.getItem("cf_api_key")) {
        setTimeout(startTour, 800);
    }
}