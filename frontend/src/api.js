/* API handler for CodeFlow3D - PRODUCTION READY */

// In production: VITE_API_URL is NOT set → defaults to "/api" (same-origin proxy via Netlify)
// In development: VITE_API_URL = "http://localhost:8000" (direct to local backend)
const API_BASE = import.meta.env.VITE_API_URL || "/api";
const API_URL = `${API_BASE}/analyze`;
const TEST_URL = `${API_BASE}/test`;
const PING_URL = `${API_BASE}/ping`;

function getApiKey() {
    return localStorage.getItem('cf_api_key') || import.meta.env.VITE_API_KEY || "";
}

export function setApiKey(key) {
    localStorage.setItem('cf_api_key', key);
}

export function clearApiKey() {
    localStorage.removeItem('cf_api_key');
    localStorage.removeItem('cf_username');
}

// Called whenever any authenticated request gets a 401 back.
// main.js registers a handler here to clear the stale key and re-show login.
let _on401Handler = null;
export function onStaledKey(fn) { _on401Handler = fn; }
function _handle401() { if (_on401Handler) _on401Handler(); }

/**
 * Test backend connectivity (retries for Render free-tier cold starts)
 */
/**
 * Test backend connectivity (retries for Render free-tier cold starts).
 * Cold starts on Render free tier can take 60-120+ seconds.
 * @param {function} onStatus - Optional callback(msg) for live status updates
 */
export async function testBackendConnection(onStatus = null) {
    const MAX_RETRIES = 8;
    const PER_ATTEMPT_TIMEOUT = 20000; // 20s per attempt
    const RETRY_DELAY = 3000;          // 3s between retries

    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        try {
            const status = attempt === 1
                ? "Connecting to backend..."
                : `Waking up backend (attempt ${attempt}/${MAX_RETRIES})...`;
            console.log(`🔍 ${status}`);
            if (onStatus) onStatus(status);

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), PER_ATTEMPT_TIMEOUT);
            const response = await fetch(PING_URL, {
                signal: controller.signal,
                cache: "no-store",          // bypass HTTP cache
            });
            clearTimeout(timeoutId);
            const data = await response.json();
            console.log("✅ Backend connected:", data);
            if (onStatus) onStatus(null); // clear status
            return true;
        } catch (error) {
            console.warn(`⏳ Backend attempt ${attempt}/${MAX_RETRIES} failed:`, error.message);
            if (attempt < MAX_RETRIES) {
                if (onStatus) onStatus(`Backend is waking up... retrying in ${RETRY_DELAY / 1000}s (${attempt}/${MAX_RETRIES})`);
                await new Promise(r => setTimeout(r, RETRY_DELAY));
            }
        }
    }
    console.error("❌ Backend connection failed after all retries. URL:", PING_URL);
    if (onStatus) onStatus(null);
    return false;
}

/**
 * Get test/dummy flow graph from backend
 */
export async function getTestFlowGraph() {
    try {
        console.log("🧪 Requesting test flow graph...");
        const response = await fetch(TEST_URL);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log("✅ Test data received:", data);
        return data;
    } catch (error) {
        console.error("❌ Test request failed:", error);
        return {
            nodes: [],
            edges: [],
            loops: [],
            conditionals: [],
            error: error.message
        };
    }
}

/**
 * Send code to backend for analysis (retries once on cold-start failures)
 */
export async function sendCode(language, code) {
    const MAX_SEND_RETRIES = 2; // 1 normal + 1 retry if "Failed to fetch"

    for (let attempt = 1; attempt <= MAX_SEND_RETRIES; attempt++) {
        try {
            const payload = { language, code };

            if (attempt === 1) {
                console.group("📤 API Request");
                console.log("URL:", API_URL);
                console.log("Language:", language);
                console.log("Code length:", code.length);
                console.groupEnd();
            } else {
                console.log(`📤 Retrying analysis (attempt ${attempt})...`);
            }

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 60000); // 60s

            const response = await fetch(API_URL, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "x-api-key": getApiKey()
                },
                body: JSON.stringify(payload),
                signal: controller.signal,
            });
            clearTimeout(timeoutId);

            console.log("📬 Response status:", response.status, response.statusText);

            if (!response.ok) {
                if (response.status === 401) _handle401();
                const errorText = await response.text();
                console.error("❌ HTTP Error:", response.status, errorText);
                throw new Error(
                    `Server Error (${response.status}): ${errorText || "Unknown error"}`
                );
            }

            const data = await response.json();

            console.group("✅ API Response");
            console.log("Nodes:", data.nodes?.length || 0);
            console.log("Edges:", data.edges?.length || 0);
            console.log("Loops:", data.loops?.length || 0);
            console.log("Conditionals:", data.conditionals?.length || 0);
            if (data.error) console.warn("Error:", data.error);
            if (data.debug) console.log("Debug info:", data.debug);
            console.groupEnd();

            return data;
        } catch (error) {
            const isNetworkError = error.message === "Failed to fetch" || error.name === "AbortError";

            // Retry once on network/timeout errors (backend may have been asleep)
            if (isNetworkError && attempt < MAX_SEND_RETRIES) {
                console.warn(`⏳ Network error, waking backend and retrying in 5s...`);
                // Fire a quick ping to help wake the backend before retrying
                try { fetch(PING_URL, { cache: "no-store" }); } catch (_) {}
                await new Promise(r => setTimeout(r, 5000));
                continue;
            }

            console.error("🔴 API Error:", error);
            let msg = error.message || "Failed to connect to server";
            if (error.name === "AbortError") {
                msg = "Request timed out. The backend may be waking up (Render free tier). Please try again in a few seconds.";
            } else if (msg === "Failed to fetch") {
                msg = `Cannot reach backend at ${API_BASE}. The server may still be starting up — please wait 30 seconds and try again.`;
            }
            return {
                nodes: [], edges: [], loops: [], conditionals: [],
                error: msg,
            };
        }
    }
}

/**
 * Poll an async task until it completes or fails.
 * @param {string} taskId - Celery task ID from /analyze
 * @param {function} onProgress - Optional callback for status updates
 * @returns {Promise<object>} The graph result
 */
export async function pollTaskResult(taskId, onProgress = null) {
    const POLL_INTERVAL = 2000;  // 2 seconds
    const MAX_ATTEMPTS = 30;     // 60 seconds total

    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        try {
            const res = await fetch(`${API_BASE}/task/${taskId}`, {
                headers: { "x-api-key": getApiKey() },
            });

            if (!res.ok) {
                if (res.status === 401) _handle401();
                throw new Error(`Task poll failed: ${res.status}`);
            }

            const data = await res.json();

            if (onProgress) onProgress(data.status, attempt + 1, MAX_ATTEMPTS);

            if (data.status === "success") {
                console.log("✅ Async task complete:", taskId);
                return data.result;
            }

            if (data.status === "error") {
                console.error("❌ Async task failed:", data.error);
                return {
                    nodes: [], edges: [], loops: [], conditionals: [],
                    error: data.error || "Analysis failed",
                };
            }

            // Still pending/processing — wait and retry
            await new Promise(r => setTimeout(r, POLL_INTERVAL));
        } catch (error) {
            console.error("🔴 Poll error:", error);
            if (attempt === MAX_ATTEMPTS - 1) {
                return {
                    nodes: [], edges: [], loops: [], conditionals: [],
                    error: "Analysis timed out. Try again later.",
                };
            }
            await new Promise(r => setTimeout(r, POLL_INTERVAL));
        }
    }

    return {
        nodes: [], edges: [], loops: [], conditionals: [],
        error: "Analysis timed out after 60 seconds.",
    };
}

// --- Saved Graphs ---

async function graphsRequest(path, method = 'GET', body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json', 'x-api-key': getApiKey() },
    };
    if (body) opts.body = JSON.stringify(body);

    // Retry once on network errors (cold start)
    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const res = await fetch(`${API_BASE}${path}`, opts);
            if (!res.ok) {
                if (res.status === 401) _handle401();
                const text = await res.text();
                throw new Error(`${res.status}: ${text}`);
            }
            return res.json();
        } catch (err) {
            if (attempt === 0 && (err.message === "Failed to fetch" || err.name === "TypeError")) {
                console.warn(`⏳ ${path} failed, retrying after wake-up delay...`);
                await new Promise(r => setTimeout(r, 4000));
                continue;
            }
            throw err;
        }
    }
}

export async function saveGraph(title, description, code, language, graphData, isPublic = false) {
    return graphsRequest('/graphs', 'POST', { title, description, code, language, graph_data: graphData, is_public: isPublic });
}

export async function listGraphs() {
    return graphsRequest('/graphs');
}

export async function loadGraph(id) {
    return graphsRequest(`/graphs/${id}`);
}

export async function deleteGraph(id) {
    return graphsRequest(`/graphs/${id}`, 'DELETE');
}

// --- API Key Management ---

export async function listApiKeys() {
    return graphsRequest('/api-keys');
}

export async function createApiKey(name) {
    return graphsRequest('/api-keys', 'POST', { name });
}

export async function revokeApiKey(id) {
    return graphsRequest(`/api-keys/${id}`, 'DELETE');
}

// --- Authentication ---

async function authPost(path, body) {
    const res = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch {
        throw new Error(res.ok ? 'Invalid server response' : `Error ${res.status}: ${text.slice(0, 120)}`);
    }
    if (!res.ok) {
        let msg = `Error ${res.status}`;
        if (typeof data.detail === 'string') {
            msg = data.detail;
        } else if (Array.isArray(data.detail)) {
            msg = data.detail.map(e => e.msg || JSON.stringify(e)).join('; ');
        }
        throw new Error(msg);
    }
    return data;
}

export async function exchangeTokenForKey(jwt) {
    const res = await fetch(`${API_BASE}/auth/api-key`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${jwt}` },
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch {
        throw new Error(res.ok ? 'Invalid server response' : `Error ${res.status}: ${text.slice(0, 120)}`);
    }
    if (!res.ok) {
        let msg = `Error ${res.status}`;
        if (typeof data.detail === 'string') {
            msg = data.detail;
        } else if (Array.isArray(data.detail)) {
            msg = data.detail.map(e => e.msg || JSON.stringify(e)).join('; ');
        }
        throw new Error(msg);
    }
    return data; // { api_key, username }
}

export async function loginUser(login, password) {
    const { access_token, username } = await authPost('/login', { login, password });
    const { api_key } = await exchangeTokenForKey(access_token);
    return { api_key, username };
}

export async function registerUser(username, email, password) {
    const data = await authPost('/register', { username, email, password });
    return { api_key: data.api_key, username: data.username };
}

// --- User Profile ---

export async function getMyProfile() {
    return graphsRequest('/me');
}

// --- User Subscription ---

export async function getMySubscription() {
    return graphsRequest('/me/subscription');
}

// --- Public Site Settings ---

export async function getPublicSettings() {
    const res = await fetch(`${API_BASE}/settings/public`);
    if (!res.ok) throw new Error(`Error ${res.status}`);
    return res.json();
}