/* CodeFlow3D Admin Panel — Frontend Logic */

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ─── State ───

let jwt = null;
let apiKey = null;
let currentPage = "dashboard";
let usersPage = 1;
let usersSearch = "";

// ─── DOM refs ───

const loginGate    = document.getElementById("loginGate");
const adminShell   = document.getElementById("adminShell");
const adminEmail   = document.getElementById("adminEmail");
const adminPassword = document.getElementById("adminPassword");
const adminLoginBtn = document.getElementById("adminLoginBtn");
const loginError   = document.getElementById("loginError");
const adminName    = document.getElementById("adminName");
const logoutBtn    = document.getElementById("logoutBtn");
const navLinks     = document.querySelectorAll("[data-page]");
const userSearchInput = document.getElementById("userSearch");
const userSearchBtn   = document.getElementById("userSearchBtn");
const userModal    = document.getElementById("userModal");
const modalClose   = document.getElementById("modalClose");
const modalTitle   = document.getElementById("modalTitle");
const modalBody    = document.getElementById("modalBody");

// ─── Auth ───

function authHeaders() {
    if (apiKey) return { "Content-Type": "application/json", "x-api-key": apiKey };
    return { "Content-Type": "application/json", "Authorization": `Bearer ${jwt}` };
}

async function adminFetch(path, opts = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        ...opts,
        headers: { ...authHeaders(), ...(opts.headers || {}) },
    });
    if (res.status === 401 || res.status === 403) {
        logout();
        throw new Error("Session expired");
    }
    if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Error ${res.status}`);
    }
    return res.json();
}

adminLoginBtn.addEventListener("click", async () => {
    loginError.textContent = "";
    const login = adminEmail.value.trim();
    const pass = adminPassword.value;
    if (!login || !pass) { loginError.textContent = "Fill in all fields."; return; }
    adminLoginBtn.disabled = true;
    adminLoginBtn.textContent = "Signing in...";
    try {
        // Step 1: get JWT
        const loginRes = await fetch(`${API_BASE}/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ login, password: pass }),
        });
        const loginData = await loginRes.json();
        if (!loginRes.ok) throw new Error(loginData.detail || "Login failed");
        jwt = loginData.access_token;

        // Step 2: exchange for API key
        const keyRes = await fetch(`${API_BASE}/auth/api-key`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${jwt}` },
        });
        const keyData = await keyRes.json();
        if (!keyRes.ok) throw new Error(keyData.detail || "Key exchange failed");
        apiKey = keyData.api_key;

        // Step 3: verify admin
        const me = await adminFetch("/admin/me");
        if (!me.is_admin) throw new Error("This account is not an admin");

        sessionStorage.setItem("admin_api_key", apiKey);
        sessionStorage.setItem("admin_username", me.username);
        showAdmin(me.username);
    } catch (err) {
        loginError.textContent = err.message;
    } finally {
        adminLoginBtn.disabled = false;
        adminLoginBtn.textContent = "Sign In";
    }
});

adminPassword.addEventListener("keydown", (e) => {
    if (e.key === "Enter") adminLoginBtn.click();
});

function logout() {
    jwt = null;
    apiKey = null;
    sessionStorage.removeItem("admin_api_key");
    sessionStorage.removeItem("admin_username");
    adminShell.style.display = "none";
    loginGate.style.display = "flex";
}
logoutBtn.addEventListener("click", logout);

// Try to restore session
(function tryRestore() {
    const savedKey = sessionStorage.getItem("admin_api_key");
    const savedName = sessionStorage.getItem("admin_username");
    if (savedKey && savedName) {
        apiKey = savedKey;
        adminFetch("/admin/me")
            .then((me) => { if (me.is_admin) showAdmin(me.username); else logout(); })
            .catch(() => logout());
    }
})();

function showAdmin(username) {
    loginGate.style.display = "none";
    adminShell.style.display = "flex";
    adminName.textContent = `👤 ${username}`;
    navigate("dashboard");
}

// ─── Navigation ───

navLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
        e.preventDefault();
        navigate(link.dataset.page);
    });
});

function navigate(page) {
    currentPage = page;
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
    document.getElementById(`page-${page}`)?.classList.add("active");
    navLinks.forEach((l) => l.classList.toggle("active", l.dataset.page === page));

    if (page === "dashboard") loadDashboard();
    if (page === "users") loadUsers();
    if (page === "settings") loadSettings();
}

// ─── Dashboard ───

async function loadDashboard() {
    try {
        const stats = await adminFetch("/admin/stats");
        document.getElementById("statUsers").textContent = stats.total_users;
        document.getElementById("statActive").textContent = stats.active_users;
        document.getElementById("statSignups").textContent = stats.recent_signups_today;
        document.getElementById("statAnalyses").textContent = stats.total_analyses.toLocaleString();
        document.getElementById("statToday").textContent = stats.analyses_today;
        document.getElementById("statGraphs").textContent = stats.total_saved_graphs;

        const subDiv = document.getElementById("subBreakdown");
        subDiv.innerHTML = Object.entries(stats.subscriptions_by_plan)
            .map(([plan, count]) => `<div><span>${esc(plan)}</span><span>${Number(count).toLocaleString()}</span></div>`)
            .join("") || "<div><span>No subscriptions yet</span><span></span></div>";

        const langDiv = document.getElementById("langBreakdown");
        langDiv.innerHTML = Object.entries(stats.analyses_by_language)
            .sort((a, b) => b[1] - a[1])
            .map(([lang, count]) => `<div><span>${esc(lang)}</span><span>${Number(count).toLocaleString()}</span></div>`)
            .join("") || "<div><span>No analyses yet</span><span></span></div>";
    } catch (err) {
        console.error("Dashboard load failed:", err);
    }
}

// ─── Users ───

userSearchBtn.addEventListener("click", () => {
    usersSearch = userSearchInput.value.trim();
    usersPage = 1;
    loadUsers();
});
userSearchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") userSearchBtn.click();
});

async function loadUsers() {
    try {
        let url = `/admin/users?page=${usersPage}&per_page=25`;
        if (usersSearch) url += `&search=${encodeURIComponent(usersSearch)}`;
        const data = await adminFetch(url);
        renderUsersTable(data);
    } catch (err) {
        console.error("Users load failed:", err);
    }
}

function renderUsersTable(data) {
    const tbody = document.getElementById("usersBody");
    tbody.innerHTML = data.users.map((u) => `
        <tr>
            <td>${u.id}</td>
            <td>${esc(u.username)}</td>
            <td>${esc(u.email)}</td>
            <td class="${u.plan === 'pro' ? 'plan-pro' : u.plan === 'enterprise' ? 'plan-enterprise' : ''}">${esc(u.plan)}</td>
            <td>${u.analysis_count}</td>
            <td>${u.active_api_keys}</td>
            <td class="${u.is_active ? 'status-active' : 'status-inactive'}">${u.is_active ? 'Active' : 'Inactive'}</td>
            <td>${u.is_admin ? '✓' : ''}</td>
            <td>
                <button class="btn-sm btn-view" onclick="window._adminViewUser(${u.id})">View</button>
                <button class="btn-sm btn-edit" onclick="window._adminEditUser(${u.id})">Edit</button>
            </td>
        </tr>
    `).join("");

    // Pagination
    const totalPages = Math.ceil(data.total / data.per_page);
    const pag = document.getElementById("usersPagination");
    let pagHtml = "";
    pagHtml += `<button ${usersPage <= 1 ? "disabled" : ""} onclick="window._adminUsersPage(${usersPage - 1})">← Prev</button>`;
    for (let i = 1; i <= totalPages && i <= 10; i++) {
        pagHtml += `<button class="${i === usersPage ? 'active' : ''}" onclick="window._adminUsersPage(${i})">${i}</button>`;
    }
    if (totalPages > 10) pagHtml += `<span style="color:var(--muted);padding:6px">...${totalPages}</span>`;
    pagHtml += `<button ${usersPage >= totalPages ? "disabled" : ""} onclick="window._adminUsersPage(${usersPage + 1})">Next →</button>`;
    pag.innerHTML = pagHtml;
}

window._adminUsersPage = (p) => { usersPage = p; loadUsers(); };

// ─── User Detail / Edit Modal ───

window._adminViewUser = async (id) => {
    try {
        const u = await adminFetch(`/admin/users/${id}`);
        modalTitle.textContent = `User: ${u.username}`;
        modalBody.innerHTML = `
            <div class="detail-row"><span class="label">ID</span><span>${u.id}</span></div>
            <div class="detail-row"><span class="label">Username</span><span>${esc(u.username)}</span></div>
            <div class="detail-row"><span class="label">Email</span><span>${esc(u.email)}</span></div>
            <div class="detail-row"><span class="label">Active</span><span class="${u.is_active ? 'status-active' : 'status-inactive'}">${u.is_active ? 'Yes' : 'No'}</span></div>
            <div class="detail-row"><span class="label">Admin</span><span>${u.is_admin ? 'Yes' : 'No'}</span></div>
            <div class="detail-row"><span class="label">Plan</span><span>${esc(u.subscription.plan)}</span></div>
            <div class="detail-row"><span class="label">Requests/day</span><span>${u.subscription.requests_per_day}</span></div>
            <div class="detail-row"><span class="label">Analyses</span><span>${u.analysis_count}</span></div>
            <div class="detail-row"><span class="label">Saved Graphs</span><span>${u.saved_graph_count}</span></div>
            <div class="detail-row"><span class="label">Joined</span><span>${new Date(u.created_at).toLocaleDateString()}</span></div>

            <h4 style="margin-top:18px;margin-bottom:8px;">Active API Keys (${u.api_keys.filter(k => k.is_active).length})</h4>
            <div class="key-list">
                ${u.api_keys.filter(k => k.is_active).map((k) => `
                    <div class="key-item">
                        <div>
                            <span class="key-prefix">${esc(k.key_prefix)}...</span>
                            <span style="color:var(--muted);margin-left:8px">${esc(k.name || '')}</span>
                        </div>
                        <div>
                            <span class="key-status status-active">Active</span>
                            <button class="btn-sm btn-danger" onclick="window._adminRevokeKey(${k.id}, ${u.id})">Revoke</button>
                        </div>
                    </div>
                `).join("")}
            </div>
            <div class="form-actions" style="margin-top:14px">
                <button class="btn-sm btn-edit" onclick="window._adminResetKeys(${u.id})">🔄 Reset All Keys</button>
                <button class="btn-sm btn-danger" onclick="window._adminDeleteUser(${u.id})">🗑 Delete User</button>
            </div>
        `;
        userModal.style.display = "flex";
    } catch (err) {
        alert("Failed to load user: " + err.message);
    }
};

window._adminEditUser = async (id) => {
    try {
        const u = await adminFetch(`/admin/users/${id}`);
        modalTitle.textContent = `Edit: ${u.username}`;
        modalBody.innerHTML = `
            <form id="editUserForm">
                <div class="form-group">
                    <label>Username</label>
                    <input name="username" value="${esc(u.username)}" />
                </div>
                <div class="form-group">
                    <label>Email</label>
                    <input name="email" type="email" value="${esc(u.email)}" />
                </div>
                <div class="form-group">
                    <label>Active</label>
                    <select name="is_active">
                        <option value="true" ${u.is_active ? 'selected' : ''}>Active</option>
                        <option value="false" ${!u.is_active ? 'selected' : ''}>Inactive</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Admin</label>
                    <select name="is_admin">
                        <option value="true" ${u.is_admin ? 'selected' : ''}>Yes</option>
                        <option value="false" ${!u.is_admin ? 'selected' : ''}>No</option>
                    </select>
                </div>
                <hr style="border-color:var(--line);margin:16px 0" />
                <h4 style="margin-bottom:10px">Subscription</h4>
                <div class="form-group">
                    <label>Plan</label>
                    <select name="plan" id="editPlanSelect">
                        <option value="free" ${u.subscription.plan === 'free' ? 'selected' : ''}>Free</option>
                        <option value="pro" ${u.subscription.plan === 'pro' ? 'selected' : ''}>Pro</option>
                        <option value="enterprise" ${u.subscription.plan === 'enterprise' ? 'selected' : ''}>Enterprise</option>
                    </select>
                </div>
                <div class="form-group">
                    <label style="display:flex;align-items:center;gap:8px">
                        <span>Requests Per Day</span>
                        <label style="font-size:0.78rem;color:var(--muted);display:flex;align-items:center;gap:4px;cursor:pointer">
                            <input type="checkbox" id="autoRpd" checked style="accent-color:var(--accent)" />
                            Auto (use plan default)
                        </label>
                    </label>
                    <input name="requests_per_day" id="editRpdInput" type="number" value="${u.subscription.requests_per_day}" disabled />
                    <span id="rpdHint" style="font-size:0.75rem;color:var(--muted)"></span>
                </div>
                <div id="editError" class="error-text"></div>
                <div class="form-actions">
                    <button type="submit" class="btn-primary">Save Changes</button>
                    <button type="button" class="btn-secondary" onclick="document.getElementById('userModal').style.display='none'">Cancel</button>
                </div>
            </form>
        `;
        userModal.style.display = "flex";

        // Plan-default auto-fill logic
        const planDefaults = { free: 100, pro: 1000, enterprise: 10000 };
        const autoCheckbox = document.getElementById("autoRpd");
        const rpdInput = document.getElementById("editRpdInput");
        const rpdHint = document.getElementById("rpdHint");
        const planSelect = document.getElementById("editPlanSelect");

        function updateRpdState() {
            const plan = planSelect.value;
            const def = planDefaults[plan] || 100;
            if (autoCheckbox.checked) {
                rpdInput.value = def;
                rpdInput.disabled = true;
                rpdHint.textContent = `Default for ${plan}: ${def.toLocaleString()}/day`;
            } else {
                rpdInput.disabled = false;
                rpdHint.textContent = `Custom override (${plan} default: ${def.toLocaleString()})`;
            }
        }
        autoCheckbox.addEventListener("change", updateRpdState);
        planSelect.addEventListener("change", updateRpdState);
        updateRpdState();

        document.getElementById("editUserForm").addEventListener("submit", async (e) => {
            e.preventDefault();
            const fd = new FormData(e.target);
            const editErr = document.getElementById("editError");
            editErr.textContent = "";

            // Validate username
            const uname = (fd.get("username") || "").trim();
            if (uname.length < 3 || uname.length > 64) { editErr.textContent = "Username must be 3–64 characters."; return; }
            if (!/^[a-zA-Z]/.test(uname)) { editErr.textContent = "Username must start with a letter."; return; }
            if (!/^[a-zA-Z0-9_\-]+$/.test(uname)) { editErr.textContent = "Username can only contain letters, numbers, _ and -."; return; }
            if (/[_\-]{2}/.test(uname)) { editErr.textContent = "Username cannot have consecutive _ or -."; return; }

            // Validate email
            const uemail = (fd.get("email") || "").trim();
            if (!/^[^\s@]+@[^\s@]+\.[a-zA-Z]{2,}$/.test(uemail)) { editErr.textContent = "Please enter a valid email address."; return; }

            try {
                // Update user fields
                await adminFetch(`/admin/users/${id}`, {
                    method: "PATCH",
                    body: JSON.stringify({
                        username: fd.get("username"),
                        email: fd.get("email"),
                        is_active: fd.get("is_active") === "true",
                        is_admin: fd.get("is_admin") === "true",
                    }),
                });
                // Update subscription — pass null for requests_per_day when auto so backend uses plan default
                const rpdValue = autoCheckbox.checked ? null : (parseInt(fd.get("requests_per_day"), 10) || null);
                await adminFetch(`/admin/users/${id}/subscription`, {
                    method: "PUT",
                    body: JSON.stringify({
                        plan: fd.get("plan"),
                        requests_per_day: rpdValue,
                    }),
                });
                userModal.style.display = "none";
                loadUsers();
            } catch (err) {
                editErr.textContent = err.message;
            }
        });
    } catch (err) {
        alert("Failed to load user: " + err.message);
    }
};

window._adminRevokeKey = async (keyId, userId) => {
    if (!confirm("Revoke this API key?")) return;
    try {
        await adminFetch(`/admin/api-keys/${keyId}`, { method: "DELETE" });
        window._adminViewUser(userId); // refresh
    } catch (err) { alert(err.message); }
};

window._adminResetKeys = async (userId) => {
    if (!confirm("Revoke ALL keys for this user and issue a new one?")) return;
    try {
        const res = await adminFetch(`/admin/users/${userId}/api-keys/reset`, { method: "POST" });
        // Show the new key in the modal with a copy button
        modalTitle.textContent = "New API Key Issued";
        modalBody.innerHTML = `
            <p style="color:var(--muted);margin-bottom:12px">All previous keys have been revoked. Copy the new key below — it won't be shown again.</p>
            <div class="new-key-box">
                <code class="new-key-text" id="resetKeyText">${esc(res.api_key)}</code>
                <button class="btn-sm btn-primary" id="copyResetKeyBtn">📋 Copy</button>
            </div>
            <div id="copyKeyStatus" style="margin-top:8px;font-size:0.82rem;color:var(--muted)"></div>
        `;
        userModal.style.display = "flex";
        document.getElementById("copyResetKeyBtn").addEventListener("click", () => {
            navigator.clipboard.writeText(res.api_key).then(() => {
                document.getElementById("copyKeyStatus").textContent = "✅ Copied to clipboard!";
                document.getElementById("copyKeyStatus").style.color = "#4ade80";
            }).catch(() => {
                // Fallback: select the text
                const range = document.createRange();
                range.selectNodeContents(document.getElementById("resetKeyText"));
                window.getSelection().removeAllRanges();
                window.getSelection().addRange(range);
                document.getElementById("copyKeyStatus").textContent = "Selected — press Ctrl+C to copy";
            });
        });
    } catch (err) { alert(err.message); }
};

window._adminDeleteUser = async (userId) => {
    if (!confirm("DELETE this user and all their data? This cannot be undone.")) return;
    try {
        await adminFetch(`/admin/users/${userId}`, { method: "DELETE" });
        userModal.style.display = "none";
        loadUsers();
    } catch (err) { alert(err.message); }
};

// ─── Modal close ───

modalClose.addEventListener("click", () => { userModal.style.display = "none"; });
userModal.addEventListener("click", (e) => {
    if (e.target === userModal) userModal.style.display = "none";
});

// ─── Site Settings ───

async function loadSettings() {
    try {
        const settings = await adminFetch("/admin/settings");
        document.getElementById("settingContactEmail").value = settings.contact_email || "";
        document.getElementById("settingUpgradeInstructions").value = settings.upgrade_instructions || "";
        document.getElementById("settingPriceFree").value = settings.plan_price_free || "0";
        document.getElementById("settingPricePro").value = settings.plan_price_pro || "19";
        document.getElementById("settingPriceEnterprise").value = settings.plan_price_enterprise || "99";
    } catch (err) {
        console.error("Settings load failed:", err);
    }
}

document.getElementById("saveSettingsBtn").addEventListener("click", async () => {
    const btn = document.getElementById("saveSettingsBtn");
    const status = document.getElementById("settingsSaveStatus");
    btn.disabled = true;
    btn.textContent = "Saving...";
    status.textContent = "";
    try {
        await adminFetch("/admin/settings", {
            method: "PUT",
            body: JSON.stringify({
                contact_email: document.getElementById("settingContactEmail").value.trim(),
                upgrade_instructions: document.getElementById("settingUpgradeInstructions").value.trim(),
                plan_price_free: document.getElementById("settingPriceFree").value.trim(),
                plan_price_pro: document.getElementById("settingPricePro").value.trim(),
                plan_price_enterprise: document.getElementById("settingPriceEnterprise").value.trim(),
            }),
        });
        status.textContent = "✅ Settings saved!";
        status.style.color = "#4ade80";
        setTimeout(() => { status.textContent = ""; }, 3000);
    } catch (err) {
        status.textContent = "❌ " + err.message;
        status.style.color = "#fb7185";
    } finally {
        btn.disabled = false;
        btn.textContent = "Save Settings";
    }
});

// ─── Helpers ───

function esc(str) {
    const d = document.createElement("div");
    d.textContent = str || "";
    return d.innerHTML;
}
