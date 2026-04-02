/* Three.js Setup for CodeFlow3D - PRODUCTION READY WITH OPTIMIZATION */

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

let scene, camera, renderer, controls;
let nodes = {};
let edges = [];

let sharedNodeGeometry;
let sharedNodeMaterial;

// Raycasting state for hover / click
const raycaster = new THREE.Raycaster();
const _mouse = new THREE.Vector2();
let _hoveredId = null;

// Tracking for unused-function nodes (pulse animation + tooltip)
let _unusedNodeIds = new Set();
let _tooltip = null;

// Tracking for loop nodes (popup on click) and infinite loop nodes (pulse)
let _loopNodeMap = {};        // id → { type, condition, is_infinite, line }
let _infiniteLoopNodeIds = new Set();
let _recursiveNodeIds = new Set();
let _loopPopup = null;

// Edge metadata kept separately for SVG export (ArrowHelpers don't expose from/to)
let _edgeData = [];   // [{fromId, toId, color, curvePoints}]

// Persistent edge definitions for dynamic rebuild on node drag
let _edgeDefs = [];   // [{fromId, toId, color}]

// Node drag state
let _draggingId = null;
const _dragPlane  = new THREE.Plane();
const _dragOffset = new THREE.Vector3();
const _dragRaycaster = new THREE.Raycaster();

/**
 * Initialize Three.js Scene
 */
function initThree() {
    console.log("🎨 Initializing Three.js scene...");

    const canvas = document.getElementById("three-canvas");

    if (!canvas) {
        console.error("❌ Canvas element not found!");
        return;
    }

    let width = canvas.clientWidth;
    let height = canvas.clientHeight;

    if (width === 0 || height === 0) {
        console.warn("⚠️ Canvas has zero dimensions, using fallback");
        width = window.innerWidth * 0.5;
        height = window.innerHeight * 0.5;
    }

    console.log(`✓ Canvas size: ${width}x${height}`);

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x020617);

    // Camera
    camera = new THREE.PerspectiveCamera(
        75,
        width / height,
        0.1,
        1000
    );
    camera.position.set(0, 10, 20);

    // Renderer
    try {
        renderer = new THREE.WebGLRenderer({
            canvas,
            antialias: true,
            alpha: true,
            powerPreference: "high-performance"
        });
        renderer.setSize(width, height);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFShadowMap;
        console.log("✓ Renderer initialized");
    } catch (error) {
        console.error("❌ Renderer initialization failed:", error);
        return;
    }

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(10, 10, 10);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.width = 2048;
    directionalLight.shadow.mapSize.height = 2048;
    scene.add(directionalLight);

    // Helpers
    const gridHelper = new THREE.GridHelper(50, 50, 0x444444, 0x222222);
    scene.add(gridHelper);

    const axesHelper = new THREE.AxesHelper(5);
    scene.add(axesHelper);

    // Shared geometries — slightly larger sphere for better visibility
    sharedNodeGeometry = new THREE.SphereGeometry(0.65, 32, 32);
    sharedNodeMaterial = new THREE.MeshStandardMaterial({
        color: 0x38bdf8,
        metalness: 0.3,
        roughness: 0.7
    });

    // OrbitControls — left-drag pans (intuitive for flowcharts), scroll zooms,
    // right-drag rotates for 3D inspection.
    try {
        controls = new OrbitControls(camera, renderer.domElement);
        controls.enableZoom    = true;
        controls.enablePan     = true;
        controls.enableRotate  = true;
        controls.autoRotate    = false;
        controls.dampingFactor = 0.07;
        controls.enableDamping = true;
        controls.zoomSpeed     = 1.4;
        controls.panSpeed      = 1.2;
        // Remap buttons: left=pan, middle=zoom, right=rotate
        controls.mouseButtons = {
            LEFT:   THREE.MOUSE.PAN,
            MIDDLE: THREE.MOUSE.DOLLY,
            RIGHT:  THREE.MOUSE.ROTATE
        };
        // Touch mapping: one-finger=pan (matches LEFT=PAN), two-finger=dolly+rotate
        controls.touches = {
            ONE: THREE.TOUCH.PAN,
            TWO: THREE.TOUCH.DOLLY_ROTATE
        };
        console.log("✓ OrbitControls enabled");
    } catch (error) {
        console.error("❌ OrbitControls failed:", error);
    }

    // Raycasting — hover highlight + click-to-focus on nodes.
    // Left-button drag on a node moves it; otherwise OrbitControls handles panning.
    let _mouseDownX = 0, _mouseDownY = 0;
    renderer.domElement.addEventListener("mousemove", _onMouseMove);

    renderer.domElement.addEventListener("mousedown", (e) => {
        _mouseDownX = e.clientX;
        _mouseDownY = e.clientY;

        if (e.button !== 0) return; // only left-button initiates node drag

        // Raycast to detect hit on a node
        const rect = renderer.domElement.getBoundingClientRect();
        const mx = ((e.clientX - rect.left) / rect.width)  *  2 - 1;
        const my = -((e.clientY - rect.top)  / rect.height) *  2 + 1;

        const downRay = new THREE.Raycaster();
        downRay.setFromCamera(new THREE.Vector2(mx, my), camera);
        const meshes  = Object.values(nodes).map(n => n.mesh).filter(Boolean);
        const sprites = Object.values(nodes).map(n => n.sprite).filter(Boolean);
        const hits    = downRay.intersectObjects([...meshes, ...sprites]);
        if (!hits.length) return;

        const hitId = Object.keys(nodes).find(id =>
            nodes[id].mesh === hits[0].object || nodes[id].sprite === hits[0].object
        );
        if (!hitId || hitId === '_debug') return;

        // Begin drag: disable orbit controls so they don't fight the drag
        _draggingId = hitId;
        controls.enabled = false;
        renderer.domElement.style.cursor = 'grabbing';

        // Camera-facing plane at node position so mouse tracks world position
        _dragPlane.setFromNormalAndCoplanarPoint(
            camera.getWorldDirection(new THREE.Vector3()).negate(),
            nodes[hitId].mesh.position
        );
        const planeHit = new THREE.Vector3();
        if (downRay.ray.intersectPlane(_dragPlane, planeHit)) {
            _dragOffset.subVectors(nodes[hitId].mesh.position, planeHit);
        } else {
            _dragOffset.set(0, 0, 0);
        }
    });

    renderer.domElement.addEventListener("mouseup", () => {
        if (_draggingId) {
            _draggingId = null;
            controls.enabled = true;
            renderer.domElement.style.cursor = _hoveredId ? 'pointer' : 'default';
        }
    });

    // ── Touch events — mirroring mouse handlers for mobile devices ───────
    let _touchStartX = 0, _touchStartY = 0;

    renderer.domElement.addEventListener("touchstart", (e) => {
        if (e.touches.length !== 1) return; // only single-finger initiates node drag
        const touch = e.touches[0];
        _touchStartX = touch.clientX;
        _touchStartY = touch.clientY;

        const rect = renderer.domElement.getBoundingClientRect();
        const mx = ((touch.clientX - rect.left) / rect.width)  *  2 - 1;
        const my = -((touch.clientY - rect.top)  / rect.height) *  2 + 1;

        const downRay = new THREE.Raycaster();
        downRay.setFromCamera(new THREE.Vector2(mx, my), camera);
        const meshes  = Object.values(nodes).map(n => n.mesh).filter(Boolean);
        const sprites = Object.values(nodes).map(n => n.sprite).filter(Boolean);
        const hits    = downRay.intersectObjects([...meshes, ...sprites]);
        if (!hits.length) return;

        const hitId = Object.keys(nodes).find(id =>
            nodes[id].mesh === hits[0].object || nodes[id].sprite === hits[0].object
        );
        if (!hitId || hitId === '_debug') return;

        _draggingId = hitId;
        controls.enabled = false;

        _dragPlane.setFromNormalAndCoplanarPoint(
            camera.getWorldDirection(new THREE.Vector3()).negate(),
            nodes[hitId].mesh.position
        );
        const planeHit = new THREE.Vector3();
        if (downRay.ray.intersectPlane(_dragPlane, planeHit)) {
            _dragOffset.subVectors(nodes[hitId].mesh.position, planeHit);
        } else {
            _dragOffset.set(0, 0, 0);
        }
    }, { passive: true });

    renderer.domElement.addEventListener("touchmove", (e) => {
        if (!_draggingId || e.touches.length !== 1) return;
        const touch = e.touches[0];

        const rect = renderer.domElement.getBoundingClientRect();
        _dragRaycaster.setFromCamera(new THREE.Vector2(
            ((touch.clientX - rect.left) / rect.width)  *  2 - 1,
            -((touch.clientY - rect.top)  / rect.height) *  2 + 1
        ), camera);
        const newPos = new THREE.Vector3();
        if (_dragRaycaster.ray.intersectPlane(_dragPlane, newPos)) {
            newPos.add(_dragOffset);
            const node = nodes[_draggingId];
            node.position.x = newPos.x;
            node.position.y = newPos.y;
            node.position.z = newPos.z;
            node.mesh.position.copy(newPos);
            const spriteOffsetY = (node.label && node.label.toLowerCase() === 'start') ? 2.2 : 1.6;
            node.sprite.position.set(newPos.x, newPos.y + spriteOffsetY, newPos.z);
            if (node.ring) node.ring.position.set(newPos.x, newPos.y, newPos.z);
            _rebuildEdgesForNode(_draggingId);
        }

        // Update tooltip position to follow finger
        if (_tooltip && _tooltip.style.display === 'block') {
            _tooltip.style.left = (touch.clientX + 14) + 'px';
            _tooltip.style.top  = (touch.clientY - 40) + 'px';
        }
    }, { passive: true });

    renderer.domElement.addEventListener("touchend", (e) => {
        if (_draggingId) {
            // Check if it was a tap (not a drag) to trigger click behaviour
            const wasDrag = _draggingId;
            _draggingId = null;
            controls.enabled = true;

            if (e.changedTouches.length > 0) {
                const touch = e.changedTouches[0];
                const dx = touch.clientX - _touchStartX;
                const dy = touch.clientY - _touchStartY;
                if (Math.sqrt(dx * dx + dy * dy) < 10) {
                    // Tap on node — trigger fly-to
                    const nodeData = nodes[wasDrag];
                    _flyToNode(wasDrag);
                    if (nodeData && nodeData.lineNumber) {
                        document.dispatchEvent(new CustomEvent('nodeClicked', {
                            detail: { id: wasDrag, line: nodeData.lineNumber, label: nodeData.label }
                        }));
                    }
                }
            }
        }
        // Hide tooltip on touch end
        if (_tooltip) _tooltip.style.display = 'none';
    });

    renderer.domElement.addEventListener("click", (e) => {
        const dx = e.clientX - _mouseDownX;
        const dy = e.clientY - _mouseDownY;
        if (Math.sqrt(dx * dx + dy * dy) >= 5) return; // drag — ignore

        // Fresh raycast at the exact click position (reliable, ignores stale _hoveredId)
        if (!renderer || !camera || !scene) return;
        const rect = renderer.domElement.getBoundingClientRect();
        const cx = ((e.clientX - rect.left)  / rect.width)  *  2 - 1;
        const cy = -((e.clientY - rect.top)  / rect.height) *  2 + 1;

        const clickRay = new THREE.Raycaster();
        clickRay.setFromCamera(new THREE.Vector2(cx, cy), camera);
        const meshes   = Object.values(nodes).map(n => n.mesh).filter(Boolean);
        const sprites  = Object.values(nodes).map(n => n.sprite).filter(Boolean);
        const hits = clickRay.intersectObjects([...meshes, ...sprites]);

        if (!hits.length) return;

        // Prefer sprite hits over sphere hits — sprites are the visible labels users intend to click.
        // A sphere from another node may sit physically closer to the camera in 3D space and win
        // hits[0] even though the user aimed at a visible sprite behind it.
        const spriteHit = hits.find(h => sprites.includes(h.object));
        const chosenHit = spriteHit || hits[0];

        const clickedId = Object.keys(nodes).find(id =>
            nodes[id].mesh === chosenHit.object || nodes[id].sprite === chosenHit.object
        );
        if (!clickedId) return;

        _flyToNode(clickedId);

        // Emit node-click event so editor can jump to the source line
        const clickedNode = nodes[clickedId];
        if (clickedNode && clickedNode.lineNumber) {
            document.dispatchEvent(new CustomEvent('nodeClicked', {
                detail: { id: clickedId, line: clickedNode.lineNumber, label: clickedNode.label }
            }));
        }
    });

    // Event listeners — window resize only; panel resizes are handled by main.js
    window.addEventListener("resize", onWindowResize);

    // Debug node
    addNode("_debug", "🟢 Scene Ready", { x: 0, y: 0, z: 0 });

    // Tooltip DOM element — reuse if already present so repeated initThree
    // calls (e.g. after dispose()) don't accumulate orphan elements.
    _tooltip = document.getElementById('node-tooltip');
    if (!_tooltip) {
        _tooltip = document.createElement('div');
        _tooltip.id = 'node-tooltip';
        document.body.appendChild(_tooltip);
    }

    // Loop popup DOM reference + close button
    _loopPopup = document.getElementById('loopPopup');
    const loopPopupCloseBtn = document.getElementById('loopPopupClose');
    if (loopPopupCloseBtn) {
        loopPopupCloseBtn.addEventListener('click', () => {
            if (_loopPopup) _loopPopup.classList.remove('show');
        });
    }

    // Start animation loop
    animate();
    console.log("✅ Three.js initialized successfully");
}

/**
 * Escape HTML special characters to prevent XSS in innerHTML.
 */
function _escapeHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/**
 * Hover handler — highlights the node under the cursor and changes cursor style.
 * Also handles active node dragging when _draggingId is set.
 */
function _onMouseMove(event) {
    if (!renderer || !camera || !scene) return;

    // ── Node drag ────────────────────────────────────────────────────────────
    if (_draggingId) {
        const rect = renderer.domElement.getBoundingClientRect();
        _dragRaycaster.setFromCamera(new THREE.Vector2(
            ((event.clientX - rect.left) / rect.width)  *  2 - 1,
            -((event.clientY - rect.top)  / rect.height) *  2 + 1
        ), camera);
        const newPos = new THREE.Vector3();
        if (_dragRaycaster.ray.intersectPlane(_dragPlane, newPos)) {
            newPos.add(_dragOffset);
            const node = nodes[_draggingId];
            node.position.x = newPos.x;
            node.position.y = newPos.y;
            node.position.z = newPos.z;
            node.mesh.position.copy(newPos);
            const spriteOffsetY = (node.label && node.label.toLowerCase() === 'start') ? 2.2 : 1.6;
            node.sprite.position.set(newPos.x, newPos.y + spriteOffsetY, newPos.z);
            if (node.ring) node.ring.position.set(newPos.x, newPos.y, newPos.z);
            _rebuildEdgesForNode(_draggingId);
        }
        return;
    }

    // ── Hover highlight ──────────────────────────────────────────────────────
    const rect = renderer.domElement.getBoundingClientRect();
    _mouse.x =  ((event.clientX - rect.left)  / rect.width)  *  2 - 1;
    _mouse.y = -((event.clientY - rect.top)   / rect.height) *  2 + 1;

    raycaster.setFromCamera(_mouse, camera);
    const meshes  = Object.values(nodes).map(n => n.mesh).filter(Boolean);
    const sprites = Object.values(nodes).map(n => n.sprite).filter(Boolean);
    const hits    = raycaster.intersectObjects([...meshes, ...sprites]);

    const hitId = hits.length > 0
        ? Object.keys(nodes).find(id =>
            nodes[id].mesh === hits[0].object || nodes[id].sprite === hits[0].object)
        : null;

    if (hitId !== _hoveredId) {
        // Un-highlight previous
        if (_hoveredId && nodes[_hoveredId]) {
            nodes[_hoveredId].material.emissiveIntensity = 0.15;
        }
        _hoveredId = hitId;
        // Highlight current
        if (_hoveredId && nodes[_hoveredId]) {
            nodes[_hoveredId].material.emissiveIntensity = 0.7;
        }
        renderer.domElement.style.cursor = _hoveredId ? 'pointer' : 'default';
        // Toggle tooltip on hover: unused function OR loop node
        if (_tooltip) {
            const hovNode = _hoveredId ? nodes[_hoveredId] : null;
            if (hovNode && hovNode.isUnused) {
                // Rose-red styling for unused function
                _tooltip.style.border     = '1px solid rgba(244,63,94,0.6)';
                _tooltip.style.background = 'rgba(38,10,24,0.95)';
                _tooltip.style.color      = '#fecdd3';
                _tooltip.style.boxShadow  = '0 8px 20px rgba(244,63,94,0.30)';
                _tooltip.style.display    = 'block';
                const lineHtml = hovNode.lineNumber ? `<br>Line ${hovNode.lineNumber}` : '';
                _tooltip.innerHTML = `<strong style="color:#fb7185;display:block;margin-bottom:3px">⚠️ UNUSED FUNCTION</strong>"${_escapeHtml(hovNode.funcName)}" is never called.${lineHtml}`;
            } else if (hovNode && hovNode.loopInfo) {
                // Purple styling matching loop node color
                _tooltip.style.border     = '1px solid rgba(168,85,247,0.6)';
                _tooltip.style.background = 'rgba(22,6,38,0.95)';
                _tooltip.style.color      = '#e9d5ff';
                _tooltip.style.boxShadow  = '0 8px 20px rgba(168,85,247,0.30)';
                _tooltip.style.display    = 'block';
                const { type, condition, is_infinite, line } = hovNode.loopInfo;
                const infBadge = is_infinite ? ' &nbsp;<span style="background:#a855f7;color:#fff;padding:1px 6px;border-radius:999px;font-size:10px;">∞ Infinite</span>' : '';
                const condHtml = condition ? `<br>Condition: <code style="color:#d8b4fe">${_escapeHtml(condition)}</code>` : '';
                const lineHtml = line ? `<br>Line ${line}` : '';
                _tooltip.innerHTML = `<strong style="color:#c084fc;display:block;margin-bottom:3px">🔁 ${(type || 'loop').toUpperCase()} LOOP${infBadge}</strong>${condHtml}${lineHtml}`;
            } else if (hovNode) {
                // Show the full label for any node (useful when label was truncated
                // in the sprite canvas at >22 chars).
                if (hovNode.label && hovNode.label.length > 22) {
                    _tooltip.style.border     = '1px solid rgba(148,163,184,0.4)';
                    _tooltip.style.background = 'rgba(15,23,42,0.95)';
                    _tooltip.style.color      = '#e2e8f0';
                    _tooltip.style.boxShadow  = '0 4px 12px rgba(0,0,0,0.40)';
                    _tooltip.style.display    = 'block';
                    _tooltip.innerHTML = _escapeHtml(hovNode.label);
                } else {
                    _tooltip.style.display = 'none';
                }
            } else {
                _tooltip.style.display = 'none';
            }
        }
    }
    // Keep tooltip following the mouse every frame
    if (_tooltip && _tooltip.style.display === 'block') {
        _tooltip.style.left = (event.clientX + 14) + 'px';
        _tooltip.style.top  = (event.clientY - 10) + 'px';
    }
}

/**
 * Smoothly fly the camera to focus on a node by its ID.
 */
function _flyToNode(id) {
    if (!nodes[id] || !camera || !controls) return;
    const node = nodes[id];
    const { x: tx, y: ty, z: tz } = node.position;

    const fromPos    = camera.position.clone();
    const fromTarget = controls.target.clone();
    const toTarget   = new THREE.Vector3(tx, ty, tz);
    const toPos      = new THREE.Vector3(tx, ty + 1.5, tz + 4);

    const startTime = performance.now();
    const DURATION  = 550;

    function step() {
        const t = Math.min((performance.now() - startTime) / DURATION, 1);
        const ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
        camera.position.lerpVectors(fromPos, toPos, ease);
        controls.target.lerpVectors(fromTarget, toTarget, ease);
        controls.update();
        if (t < 1) requestAnimationFrame(step);
    }
    step();
}

/**
 * Show the loop info popup for a clicked loop node.
 * Always looks up DOM elements fresh — avoids stale cached references.
 */
function _showLoopPopup(nodeId) {
    const nodeData = nodes[nodeId];
    if (!nodeData || !nodeData.loopInfo) return;

    const popup = _loopPopup || document.getElementById('loopPopup');
    if (!popup) return;

    const { type, condition, is_infinite, line } = nodeData.loopInfo;

    const titleEl   = document.getElementById('loopPopupTitle');
    const typeEl    = document.getElementById('loopPopupType');
    const condEl    = document.getElementById('loopPopupCondition');
    const lineEl    = document.getElementById('loopPopupLine');
    const infoBadge = document.getElementById('loopPopupInfinite');

    if (titleEl)   titleEl.textContent  = (type || 'loop') + ' loop';
    if (typeEl)    typeEl.textContent   = type || '—';
    if (condEl)    condEl.textContent   = condition || '(none)';
    if (lineEl)    lineEl.textContent   = line ? `Line ${line}` : '—';
    if (infoBadge) infoBadge.style.display = is_infinite ? 'inline-block' : 'none';

    popup.classList.add('show');
}

/**
 * Click handler — kept for hover-cursor logic; actual click is handled inline above.
 */
function _onMouseClick() {
    // intentionally empty — logic moved to the inline canvas click listener
    // to allow fresh raycasting at exact click coordinates
}

/**
 * Public: fly camera to any node by its id (called from main.js).
 */
export function zoomToNodeById(id) {
    _flyToNode(id);
}

/**
 * Public: fly camera to the first START node in the graph.
 * Returns true if a START node was found, false otherwise.
 */
export function flyToStartNode() {
    for (const [id, data] of Object.entries(nodes)) {
        if (data.label && data.label.toLowerCase() === 'start') {
            _flyToNode(id);
            return true;
        }
    }
    return false;
}

/**
 * Resize Handler — also exported so external callers (panel resizer) can trigger it.
 */
export function onWindowResize() {
    const canvas = document.getElementById("three-canvas");
    if (!canvas) return;

    // Clear any inline size Three.js stamped previously so CSS layout
    // (flex: 1 / width: 100%) can recalculate the correct dimensions first.
    canvas.style.width  = '';
    canvas.style.height = '';

    // Use the visualization section's inner size for accuracy
    const section = canvas.closest('.visualization-section') || canvas.parentElement;
    let width  = section ? section.clientWidth  - 20 : canvas.clientWidth;
    let height = section ? section.clientHeight - 20 : canvas.clientHeight;

    if (width <= 0 || height <= 0) {
        width  = window.innerWidth  * 0.5;
        height = window.innerHeight * 0.5;
    }

    if (camera && renderer) {
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height);
    }
}

/**
 * Animation Loop
 */
function animate() {
    requestAnimationFrame(animate);

    // Pulse unused-function nodes (red throb)
    if (_unusedNodeIds.size > 0) {
        const pulse = 0.35 + 0.55 * (Math.sin(performance.now() / 500) * 0.5 + 0.5);
        _unusedNodeIds.forEach(id => {
            if (nodes[id] && _hoveredId !== id)
                nodes[id].material.emissiveIntensity = pulse;
        });
    }

    // Pulse infinite-loop nodes (purple glow)
    if (_infiniteLoopNodeIds.size > 0) {
        const loopPulse = 0.4 + 0.6 * (Math.sin(performance.now() / 420) * 0.5 + 0.5);
        _infiniteLoopNodeIds.forEach(id => {
            if (nodes[id] && _hoveredId !== id)
                nodes[id].material.emissiveIntensity = loopPulse;
        });
    }

    // Pulse recursive call nodes (red-pink throb)
    if (_recursiveNodeIds.size > 0) {
        const recPulse = 0.3 + 0.5 * (Math.sin(performance.now() / 380) * 0.5 + 0.5);
        _recursiveNodeIds.forEach(id => {
            if (nodes[id] && _hoveredId !== id)
                nodes[id].material.emissiveIntensity = recPulse;
        });
    }

    if (controls) {
        controls.update();
    }

    if (renderer && scene && camera) {
        renderer.render(scene, camera);
    }
}

/**
 * Determine node color from its label (matches vision node types)
 *
 * Parser labels follow the pattern  "type: name"  (e.g. "call: normalLoops",
 * "function: trickyLoop").  We extract the TYPE PREFIX before the colon and
 * match on that first — so a call named "loopHandler" stays cyan, and a
 * function named "formatData" stays blue.  Structural labels that have no
 * colon (e.g. "for loop", "if condition", "START") fall through to the
 * content-based checks below.
 */
function getNodeColor(label, isUnused = false, isRecursive = false) {
    if (isUnused) return 0xf43f5e;  // rose-red — dead code
    if (isRecursive) return 0xff6b6b; // bright red-pink — recursive call

    const l      = label.toLowerCase();
    const prefix = l.includes(':') ? l.split(':')[0].trim() : null;

    // ── Prefix-based (colon-prefixed labels: "call: x", "function: x", …) ──
    if (prefix === 'call')                                             return 0x06b6d4; // cyan
    if (prefix === 'function'    || prefix === 'method' ||
        prefix === 'constructor' || prefix === 'arrow function')      return 0x38bdf8; // blue
    if (prefix === 'class'       || prefix === 'struct')              return 0x818cf8; // indigo
    if (prefix === 'catch' || prefix === 'except')                    return 0xf97316; // orange

    // ── Content-based (structural labels with no colon) ──────────────────
    if (l === 'start' || l.startsWith('start'))                       return 0x10b981; // green
    if (l === 'return' || l.startsWith('return'))                     return 0xef4444; // red
    if (l === 'break')                                                return 0xfb923c; // orange-400 — loop exit
    if (l === 'continue')                                             return 0x34d399; // emerald-400 — loop skip
    if (l === 'throw')                                                return 0xef4444; // red — exception throw
    if (l === 'finally' || l === 'try-else')                          return 0xfbbf24; // amber-400 — cleanup
    if (l.startsWith('with') || l.startsWith('async with'))           return 0x60a5fa; // blue-400 — context manager
    if (l.startsWith('if')    || l.startsWith('elif') ||
        l.startsWith('else')  || l.includes('switch'))                return 0xf59e0b; // amber
    if (l.includes('for loop') || l.includes('while loop') ||
        l.includes('do-while') || l === 'loop' ||
        l.startsWith('for (')  || l.startsWith('while ('))            return 0xa855f7; // purple
    if (l.startsWith('try')   || l.startsWith('catch') ||
        l.startsWith('except'))                                       return 0xf97316; // orange
    if (l.startsWith('case ')  || l === 'default')                    return 0xfbbf24; // amber-400 — switch cases
    return 0x94a3b8; // slate gray — assignment, declaration, etc.
}

/**
 * Add a Node (colored by type)
 * @param {string}  id        - Unique node ID
 * @param {string}  label     - Display label
 * @param {object}  position  - {x, y, z}
 * @param {boolean} isUnused  - If true, node is highlighted as unused/dead code
 * @param {number|null} lineNumber - Source line number when available
 */
export function addNode(id, label, position = { x: 0, y: 0, z: 0 }, isUnused = false, lineNumber = null, loopInfo = null, isRecursive = false, recursionType = null) {
    if (nodes[id]) return;

    if (!scene) {
        console.error("❌ Scene not initialized");
        return;
    }

    const z = position.z || 0;

    const isInfiniteLoop = loopInfo && loopInfo.is_infinite;
    const isStart = label.toLowerCase() === 'start';
    const color = getNodeColor(label, isUnused, isRecursive);
    const material = new THREE.MeshStandardMaterial({
        color,
        metalness: 0.3,
        roughness: 0.6,
        emissive: color,
        emissiveIntensity: isStart ? 0.7 : (isInfiniteLoop ? 0.5 : (isRecursive ? 0.45 : 0.15))
    });

    // START node gets a larger sphere to stand out
    const geometry = isStart
        ? new THREE.SphereGeometry(1.1, 32, 32)
        : sharedNodeGeometry;
    const sphere = new THREE.Mesh(geometry, material);

    sphere.position.set(position.x || 0, position.y || 0, z);
    sphere.castShadow = true;
    sphere.receiveShadow = true;

    // Add a pulsing glow ring around the START node
    let startRing = null;
    if (isStart) {
        const ringGeo = new THREE.RingGeometry(1.4, 1.8, 48);
        const ringMat = new THREE.MeshBasicMaterial({
            color: 0x10b981,
            transparent: true,
            opacity: 0.45,
            side: THREE.DoubleSide
        });
        startRing = new THREE.Mesh(ringGeo, ringMat);
        startRing.position.copy(sphere.position);
        startRing.rotation.x = -Math.PI / 2;
        startRing.userData._startRing = true;
        scene.add(startRing);
    }

    scene.add(sphere);

    // Extract clean function name for the unused-node tooltip
    const funcName = isUnused
        ? (label.match(/:\s*(.+)$/) || [, label])[1].trim()
        : label;

    // Add label as sprite — high-res canvas for crisp close-up zoom
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    canvas.width  = 512;
    const spriteHeight = (isUnused || isInfiniteLoop || isRecursive) ? 126 : 112;
    canvas.height = spriteHeight;

    if (isInfiniteLoop) {
        // Two-layer infinite-loop label: purple header banner + condition
        const condText = (loopInfo.condition || '').length > 18
            ? loopInfo.condition.slice(0, 16) + '\u2026'
            : (loopInfo.condition || '\u221e');
        context.fillStyle = "#120520";
        context.fillRect(0, 0, 512, 126);
        context.fillStyle = "#a855f7";
        context.fillRect(2, 2, 508, 36);
        context.font = "bold 22px Arial";
        context.fillStyle = "#ffffff";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText("\u221e  INFINITE LOOP", 256, 20);
        context.strokeStyle = '#a855f7';
        context.lineWidth = 3;
        context.setLineDash([8, 4]);
        context.strokeRect(2, 2, 508, 122);
        context.setLineDash([]);
        context.font = "bold 24px Arial";
        context.fillStyle = "#d8b4fe";
        context.fillText(condText, 256, 66);
        if (lineNumber) {
            context.font = "bold 18px Arial";
            context.fillStyle = "#e9d5ff";
            context.fillText(`Line ${lineNumber}`, 256, 102);
        }
    } else if (isUnused) {
        // Two-layer warning label: red header banner + function name
        context.fillStyle = "#1a0510";
        context.fillRect(0, 0, 512, 126);
        context.fillStyle = "#f43f5e";
        context.fillRect(2, 2, 508, 36);
        context.font = "bold 22px Arial";
        context.fillStyle = "#ffffff";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText("\u26A0  UNUSED FUNCTION", 256, 20);
        context.strokeStyle = '#f43f5e';
        context.lineWidth = 3;
        context.setLineDash([8, 4]);
        context.strokeRect(2, 2, 508, 122);
        context.setLineDash([]);
        context.font = "bold 24px Arial";
        context.fillStyle = "#fda4af";
        const nameText = funcName.length > 20 ? funcName.slice(0, 18) + '\u2026' : funcName;
        context.fillText(nameText, 256, 66);
        if (lineNumber) {
            context.font = "bold 18px Arial";
            context.fillStyle = "#fecdd3";
            context.fillText(`Line ${lineNumber}`, 256, 102);
        }
    } else if (isRecursive) {
        // Recursive call label: red-pink header + call info
        const recLabel = recursionType === 'direct' ? '\u21BB  DIRECT RECURSION' : '\u21BB  MUTUAL RECURSION';
        const callName = label.replace(/^call:\s*/i, '');
        const nameText = callName.length > 20 ? callName.slice(0, 18) + '\u2026' : callName;
        context.fillStyle = "#1a0a0a";
        context.fillRect(0, 0, 512, 126);
        context.fillStyle = "#ff6b6b";
        context.fillRect(2, 2, 508, 36);
        context.font = "bold 22px Arial";
        context.fillStyle = "#ffffff";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(recLabel, 256, 20);
        context.strokeStyle = '#ff6b6b';
        context.lineWidth = 3;
        context.setLineDash([8, 4]);
        context.strokeRect(2, 2, 508, 122);
        context.setLineDash([]);
        context.font = "bold 24px Arial";
        context.fillStyle = "#fca5a5";
        context.fillText(nameText, 256, 66);
        if (lineNumber) {
            context.font = "bold 18px Arial";
            context.fillStyle = "#fecaca";
            context.fillText(`Line ${lineNumber}`, 256, 102);
        }
    } else if (isStart) {
        // Special START node label — bright green banner
        context.fillStyle = "#052e16";
        context.fillRect(0, 0, 512, 112);
        context.fillStyle = "#10b981";
        context.fillRect(2, 2, 508, 36);
        context.font = "bold 24px Arial";
        context.fillStyle = "#ffffff";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText("\u25B6  START", 256, 20);
        context.strokeStyle = '#10b981';
        context.lineWidth = 4;
        context.strokeRect(2, 2, 508, 108);
        context.font = "bold 20px Arial";
        context.fillStyle = "#6ee7b7";
        context.fillText("Entry Point", 256, 68);
    } else {
        const hexColor = '#' + color.toString(16).padStart(6, '0');
        context.fillStyle = "#0f172a";
        context.fillRect(0, 0, 512, 112);
        context.strokeStyle = hexColor;
        context.lineWidth = 3;
        context.strokeRect(2, 2, 508, 108);
        context.font = "bold 24px Arial";
        context.fillStyle = "#ffffff";
        context.textAlign  = "center";
        context.textBaseline = "middle";
        const text = label.length > 22 ? label.slice(0, 20) + '\u2026' : label;
        context.fillText(text, 256, lineNumber ? 42 : 56);
        if (lineNumber) {
            context.font = "bold 18px Arial";
            context.fillStyle = "#cbd5e1";
            context.fillText(`Line ${lineNumber}`, 256, 82);
        }
    }

    const texture = new THREE.CanvasTexture(canvas);
    const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
    const sprite = new THREE.Sprite(spriteMaterial);
    const bigSprite = isUnused || isInfiniteLoop || isStart || isRecursive;
    sprite.scale.set(bigSprite ? 4.2 : 3.2, bigSprite ? 1.3 : 0.98, 1);
    sprite.position.copy(sphere.position);
    sprite.position.y += isStart ? 2.2 : 1.6;
    scene.add(sprite);

    nodes[id] = {
        mesh: sphere,
        material: material,
        label: label,
        position: { x: position.x || 0, y: position.y || 0, z: z },
        sprite: sprite,
        texture: texture,
        spriteMaterial: spriteMaterial,
        isUnused: isUnused,
        funcName: funcName,
        lineNumber: lineNumber,
        loopInfo: loopInfo,
        ring: startRing
    };
    if (isUnused) _unusedNodeIds.add(id);
    if (isInfiniteLoop) _infiniteLoopNodeIds.add(id);
    if (isRecursive) _recursiveNodeIds.add(id);

    console.log(`✓ Node added: ${id} (${label})`);
}

/**
 * Internal: build the 3D line + arrow cones for one edge and push into `edges`
 * and `_edgeData`.  Called by addEdge() and _rebuildEdgesForNode().
 *
 * Routing strategy:
 *  • Edges connect node sphere surfaces, not centers.
 *  • Back-edges (loops/upward): arc through positive Z to avoid all nodes.
 *  • Blocked forward edges: lateral + Z offset pushed away from every blocking
 *    node on the path with generous clearance.
 *  • Clean forward edges: small per-edge lane stagger so parallel edges don't overlap.
 *  • Arrow cones placed along the curve — count scales with arc length so long
 *    edges get more arrows (1 per ~4 world units, min 1, max 5).
 */
function _buildEdge3D(fromId, toId, color) {
    const fromNode = nodes[fromId];
    const toNode   = nodes[toId];
    if (!fromNode || !toNode) return;

    const SPHERE_R = 0.65;

    const sx = fromNode.position.x, sy = fromNode.position.y, sz = fromNode.position.z;
    const ex = toNode.position.x,   ey = toNode.position.y,   ez = toNode.position.z;

    const dx    = ex - sx, dy = ey - sy;
    const len2d = Math.sqrt(dx * dx + dy * dy);

    if (len2d < 0.01) return;

    const ux = dx / len2d, uy = dy / len2d;
    const start = new THREE.Vector3(sx + ux * SPHERE_R, sy + uy * SPHERE_R, sz);
    const end   = new THREE.Vector3(ex - ux * SPHERE_R, ey - uy * SPHERE_R, ez);

    const midX  = (sx + ex) / 2;
    const midY  = (sy + ey) / 2;
    const perpX = -dy / len2d;
    const perpY =  dx / len2d;

    const isBackEdge = ey >= sy - 0.5;
    let ctrl;

    if (isBackEdge) {
        const span   = Math.sqrt(dx * dx + dy * dy);
        const zBulge = 6.5 + span * 0.35;
        ctrl = new THREE.Vector3(midX, midY, sz + zBulge);
    } else {
        const NODE_CLEAR = 3.5;
        let maxNeeded = 0;
        let pushSide  = 1;

        Object.entries(nodes).forEach(([id, n]) => {
            if (id === fromId || id === toId || id === '_debug') return;
            const nx = n.position.x, ny = n.position.y;
            const t = ((nx - sx) * dx + (ny - sy) * dy) / (len2d * len2d);
            if (t <= 0.05 || t >= 0.95) return;
            const closestX = sx + t * dx;
            const closestY = sy + t * dy;
            const dist = Math.sqrt((nx - closestX) ** 2 + (ny - closestY) ** 2);
            if (dist < NODE_CLEAR) {
                const needed = NODE_CLEAR - dist + 2.5;
                if (needed > maxNeeded) {
                    maxNeeded = needed;
                    const cross = (nx - sx) * dy - (ny - sy) * dx;
                    pushSide = cross > 0.01 ? -1 : 1;
                }
            }
        });

        if (maxNeeded > 0) {
            const lateral = pushSide * Math.max(maxNeeded * 0.9, 2.0);
            const zLift   = maxNeeded * 0.9 + 2.5;
            ctrl = new THREE.Vector3(
                midX + perpX * lateral * 2.8,
                midY + perpY * lateral * 2.8,
                sz + zLift
            );
        } else {
            const lane = ((edges.length % 5) - 2) * 0.4;
            ctrl = new THREE.Vector3(
                midX + perpX * lane * 2,
                midY + perpY * lane * 2,
                sz
            );
        }
    }

    const curve  = new THREE.QuadraticBezierCurve3(start, ctrl, end);
    const points = curve.getPoints(48);
    const arcLen = curve.getLength();

    // Line
    const geo  = new THREE.BufferGeometry().setFromPoints(points);
    const mat  = new THREE.LineBasicMaterial({ color });
    const line = new THREE.Line(geo, mat);
    scene.add(line);

    // ── Arrows: 1 per ~4 world-units of arc length, min 1, max 5 ─────────────
    const arrowCount = Math.max(1, Math.min(5, Math.floor(arcLen / 4)));
    const cones = [];
    for (let i = 0; i < arrowCount; i++) {
        // Spread evenly in the range [0.35, 0.85] so arrows stay away from nodes
        const t = arrowCount === 1
            ? 0.75
            : 0.35 + (i / (arrowCount - 1)) * 0.50;

        const arrowIdx = Math.floor(t * (points.length - 1));
        const arrowPos = points[arrowIdx].clone();
        const pBack    = points[Math.max(arrowIdx - 3, 0)];
        const pFwd     = points[Math.min(arrowIdx + 3, points.length - 1)];
        const arrowDir = new THREE.Vector3().subVectors(pFwd, pBack).normalize();

        const cone = new THREE.Mesh(
            new THREE.ConeGeometry(0.20, 0.52, 8),
            new THREE.MeshBasicMaterial({ color })
        );
        cone.position.copy(arrowPos);
        cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), arrowDir);
        scene.add(cone);
        cones.push(cone);
    }

    edges.push({ line, cones, fromId, toId });
    _edgeData.push({ fromId, toId, color, curvePoints: points });
}

/**
 * Remove and rebuild all edges connected to a given node (called during drag).
 */
function _rebuildEdgesForNode(nodeId) {
    // Defs for all edges touching this node
    const defsToRebuild = _edgeDefs.filter(d => d.fromId === nodeId || d.toId === nodeId);
    if (defsToRebuild.length === 0) return;

    // Remove affected 3D objects
    for (let i = edges.length - 1; i >= 0; i--) {
        const e = edges[i];
        if (e.fromId !== nodeId && e.toId !== nodeId) continue;
        if (e.line) { e.line.geometry.dispose(); e.line.material.dispose(); scene.remove(e.line); }
        if (e.cones) e.cones.forEach(c => { c.geometry.dispose(); c.material.dispose(); scene.remove(c); });
        if (e.cone)  { e.cone.geometry.dispose(); e.cone.material.dispose(); scene.remove(e.cone); } // legacy
        edges.splice(i, 1);
    }

    // Remove from SVG export cache
    _edgeData = _edgeData.filter(d => d.fromId !== nodeId && d.toId !== nodeId);

    // Rebuild
    defsToRebuild.forEach(d => _buildEdge3D(d.fromId, d.toId, d.color));
}

/**
 * Add a Directed Edge (public — stores definition then builds 3D objects).
 */
export function addEdge(fromId, toId, options = {}) {
    if (!scene) {
        console.error("❌ Scene not initialized");
        return;
    }

    const fromNode = nodes[fromId];
    const toNode   = nodes[toId];

    if (!fromNode || !toNode) {
        console.warn(`⚠️ Edge missing nodes: ${fromId} → ${toId}`);
        return;
    }

    const color = options.color || 0xffffff;

    // Store persistent definition so edges can be rebuilt when nodes move
    _edgeDefs.push({ fromId, toId, color });

    _buildEdge3D(fromId, toId, color);

    console.log(`✓ Edge added: ${fromId} → ${toId}`);
}

/**
 * Update Scene
 */
export function updateScene() {
    if (renderer && scene && camera) {
        renderer.render(scene, camera);
    }
}

/**
 * Clear Scene (with full memory cleanup)
 */
export function clearScene() {
    console.log("🗑️ Clearing scene and freeing memory...");

    Object.values(nodes).forEach(n => {
        if (n.mesh) {
            scene.remove(n.mesh);
        }
        if (n.material) {
            n.material.dispose();
        }
        if (n.sprite) {
            scene.remove(n.sprite);
        }
        if (n.texture) {
            n.texture.dispose();
        }
        if (n.spriteMaterial) {
            n.spriteMaterial.dispose();
        }
        if (n.ring) {
            scene.remove(n.ring);
            if (n.ring.geometry) n.ring.geometry.dispose();
            if (n.ring.material) n.ring.material.dispose();
        }
    });

    edges.forEach(e => {
        if (e.line) {
            if (e.line.geometry) e.line.geometry.dispose();
            if (e.line.material) e.line.material.dispose();
            scene.remove(e.line);
        }
        if (e.cones) {
            e.cones.forEach(c => {
                if (c.geometry) c.geometry.dispose();
                if (c.material) c.material.dispose();
                scene.remove(c);
            });
        }
        if (e.cone) {  // legacy single-cone entry
            if (e.cone.geometry) e.cone.geometry.dispose();
            if (e.cone.material) e.cone.material.dispose();
            scene.remove(e.cone);
        }
    });

    nodes = {};
    edges = [];
    _edgeData = [];
    _edgeDefs = [];
    _unusedNodeIds = new Set();
    _loopNodeMap = {};
    _infiniteLoopNodeIds = new Set();
    _recursiveNodeIds = new Set();
    if (_tooltip) _tooltip.style.display = 'none';
    if (_loopPopup) _loopPopup.classList.remove('show');

    console.log("✓ Scene cleared and memory freed");
}

/**
 * Reset Camera to Default View
 */
export function resetCamera() {
    if (!camera || !controls) return;

    camera.position.set(0, 10, 20);
    controls.target.set(0, 0, 0);
    controls.update();

    console.log("✓ Camera reset");
}

/**
 * Fit camera to show all nodes.
 * Positions the camera slightly above and in front of the graph centre
 * and animates smoothly into place.
 */
export function fitCameraToGraph() {
    if (!camera || !controls) return;

    const nodeList = Object.values(nodes);
    if (nodeList.length === 0) return;

    // Bounding box
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    let minZ = Infinity, maxZ = -Infinity;
    nodeList.forEach(n => {
        const { x, y, z } = n.position;
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
        if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
    });

    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const cz = (minZ + maxZ) / 2;

    const sizeX   = maxX - minX;
    const sizeY   = maxY - minY;
    const maxSize = Math.max(sizeX, sizeY, 12);

    // Camera sits above-and-forward, looking at graph centre —
    // angled so the top-to-bottom flow is clearly visible.
    // Cap distance so large graphs don't zoom out excessively.
    const rawDist = maxSize * 1.2;
    const dist = Math.min(rawDist, 50);
    const toPos    = new THREE.Vector3(cx, cy + dist * 0.45, cz + dist * 0.7);
    const toTarget = new THREE.Vector3(cx, cy, cz);

    // Smooth fly-in
    const fromPos    = camera.position.clone();
    const fromTarget = controls.target.clone();
    const startTime  = performance.now();
    const DURATION   = 600;

    function step() {
        const t    = Math.min((performance.now() - startTime) / DURATION, 1);
        const ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
        camera.position.lerpVectors(fromPos, toPos, ease);
        controls.target.lerpVectors(fromTarget, toTarget, ease);
        controls.update();
        if (t < 1) requestAnimationFrame(step);
    }
    step();

    console.log(`✓ Camera fitted: centre=(${cx.toFixed(1)}, ${cy.toFixed(1)}), span=${maxSize.toFixed(1)}`);
}

/**
 * Get Scene Info (Debug)
 */
export function getSceneInfo() {
    return {
        nodeCount: Object.keys(nodes).length,
        edgeCount: edges.length,
        cameraPosition: camera ? {
            x: camera.position.x.toFixed(2),
            y: camera.position.y.toFixed(2),
            z: camera.position.z.toFixed(2)
        } : null,
        sceneReady: !!scene && !!renderer && !!camera,
        memory: {
            nodeGeometries: "shared (1x)",
            materials: "shared (1x)"
        }
    };
}

/**
 * Dispose all resources
 */
export function dispose() {
    console.log("🧹 Disposing Three.js resources...");

    clearScene();

    // Remove named event listeners (anonymous handlers can't be removed by reference).
    if (renderer) {
        renderer.domElement.removeEventListener('mousemove', _onMouseMove);
    }
    window.removeEventListener('resize', onWindowResize);

    if (sharedNodeGeometry) sharedNodeGeometry.dispose();
    if (sharedNodeMaterial) sharedNodeMaterial.dispose();

    if (renderer) renderer.dispose();

    console.log("✓ All resources disposed");
}

/**
 * Export the current graph as a scalable SVG file.
 * Projects every node and edge from 3D world-space to 2D screen-space using
 * the current camera, then writes crisp SVG shapes — infinitely zoomable.
 */
export function exportSVG(filename = 'codeflow-graph.svg') {
    if (!renderer || !scene || !camera) {
        console.warn('Scene not ready for export');
        return;
    }
    renderer.render(scene, camera);

    // Use a large fixed canvas so labels are readable even on small screens
    const W = 3200;
    const H = 2000;

    // Clone camera with the export aspect so projection matches the output size
    const exportCam = camera.clone();
    exportCam.aspect = W / H;
    exportCam.updateProjectionMatrix();

    function project(x, y, z) {
        const v = new THREE.Vector3(x, y, z).project(exportCam);
        return { x: (v.x + 1) / 2 * W, y: (-v.y + 1) / 2 * H, behind: v.z > 1 };
    }

    // ── SVG header + defs ─────────────────────────────────────────────────
    let svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs>
  <filter id="glow" x="-40%" y="-40%" width="180%" height="180%">
    <feGaussianBlur stdDeviation="6" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <marker id="ah-w" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
    <path d="M0,0 L0,6 L8,3 z" fill="rgba(255,255,255,0.75)"/>
  </marker>
  <marker id="ah-g" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
    <path d="M0,0 L0,6 L8,3 z" fill="#22c55e"/>
  </marker>
  <marker id="ah-a" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
    <path d="M0,0 L0,6 L8,3 z" fill="#f59e0b"/>
  </marker>
  <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
    <path d="M 50 0 L 0 0 0 50" fill="none" stroke="rgba(148,163,184,0.07)" stroke-width="1"/>
  </pattern>
</defs>
<rect width="${W}" height="${H}" fill="#0f172a"/>
<rect width="${W}" height="${H}" fill="url(#grid)"/>`;

    // ── Edges ─────────────────────────────────────────────────────────────
    _edgeData.forEach(({ fromId, toId, color, curvePoints }) => {
        const fn = nodes[fromId], tn = nodes[toId];
        if (!fn || !tn) return;
        const hexCol = '#' + color.toString(16).padStart(6, '0');
        const markId = color === 0x22c55e ? 'ah-g' : color === 0xf59e0b ? 'ah-a' : 'ah-w';

        if (curvePoints && curvePoints.length > 1) {
            // Project every Bézier sample point and build a polyline
            const pts = curvePoints
                .map(p => {
                    const pp = project(p.x, p.y, p.z);
                    return pp.behind ? null : `${pp.x.toFixed(1)},${pp.y.toFixed(1)}`;
                })
                .filter(Boolean)
                .join(' ');
            if (pts) {
                svg += `\n  <polyline points="${pts}" fill="none" stroke="${hexCol}" stroke-width="1.8" stroke-opacity="0.75" marker-end="url(#${markId})"/>`;
            }
        } else {
            // Fallback: straight line (legacy / missing curve data)
            const p1 = project(fn.position.x, fn.position.y, fn.position.z);
            const p2 = project(tn.position.x, tn.position.y, tn.position.z);
            if (p1.behind || p2.behind) return;
            const dx = p2.x - p1.x, dy = p2.y - p1.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const ex2 = p2.x - (dx / dist) * 22, ey2 = p2.y - (dy / dist) * 22;
            svg += `\n  <line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${ex2.toFixed(1)}" y2="${ey2.toFixed(1)}" stroke="${hexCol}" stroke-width="1.8" stroke-opacity="0.75" marker-end="url(#${markId})"/>`;
        }
    });

    // ── Nodes ─────────────────────────────────────────────────────────────
    Object.entries(nodes).forEach(([id, n]) => {
        if (!n.mesh || id === '_debug') return;
        const p = project(n.position.x, n.position.y, n.position.z);
        if (p.behind) return;

        const hexCol  = '#' + n.material.color.getHexString();
        const isInf   = n.loopInfo && n.loopInfo.is_infinite;
        const glowAtt = isInf ? ' filter="url(#glow)"' : '';

        // Node circle
        svg += `\n  <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="16" fill="${hexCol}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"${glowAtt}/>`;

        // Label pill background + text
        const raw  = n.label;
        const text = raw.length > 30 ? raw.slice(0, 28) + '\u2026' : raw;
        const safeText = _escapeHtml(text);
        const tw   = Math.min(text.length * 7.8 + 20, 280);
        const rx   = p.x - tw / 2, ry = p.y - 46;
        svg += `\n  <rect x="${rx.toFixed(1)}" y="${ry.toFixed(1)}" width="${tw.toFixed(1)}" height="22" rx="5" fill="rgba(15,23,42,0.88)" stroke="${hexCol}" stroke-width="0.8" stroke-opacity="0.55"/>`;
        svg += `\n  <text x="${p.x.toFixed(1)}" y="${(p.y - 35).toFixed(1)}" text-anchor="middle" dominant-baseline="middle" fill="#e2e8f0" font-family="IBM Plex Mono,monospace" font-size="11.5" font-weight="600">${safeText}</text>`;

        if (n.lineNumber) {
            svg += `\n  <text x="${p.x.toFixed(1)}" y="${(p.y + 31).toFixed(1)}" text-anchor="middle" fill="rgba(148,163,184,0.7)" font-family="monospace" font-size="9">Line ${n.lineNumber}</text>`;
        }

        // Infinite loop badge
        if (isInf) {
            svg += `\n  <text x="${p.x.toFixed(1)}" y="${(p.y - 8).toFixed(1)}" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-size="10" font-weight="bold">\u221e</text>`;
        }
    });

    svg += '\n</svg>';

    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/** @deprecated Use exportSVG instead */
export function exportCanvasPNG(filename = 'codeflow-graph.png') {
    if (!renderer || !scene || !camera) return;
    renderer.render(scene, camera);
    const url = renderer.domElement.toDataURL('image/png');
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
}

/**
 * Initialize on load
 */
document.addEventListener("DOMContentLoaded", initThree);