<script setup>
import {
  Activity,
  Clipboard,
  Download,
  FileDown,
  Gauge,
  History,
  LoaderCircle,
  Moon,
  Play,
  RefreshCw,
  RotateCcw,
  Server,
  Settings2,
  Sun,
  Zap,
} from "@lucide/vue";
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from "vue";

const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(await errorText(res));
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await errorText(res));
    return res.json();
  },
};

async function errorText(res) {
  try {
    const data = await res.json();
    return data.detail || res.statusText;
  } catch {
    return res.statusText;
  }
}

function storedTheme() {
  const saved = window.localStorage.getItem("cdn-ip-probe-theme");
  if (saved === "light" || saved === "night") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "night" : "light";
}

function setDocumentTheme(value) {
  document.documentElement.dataset.theme = value;
  document.documentElement.style.colorScheme = value === "night" ? "dark" : "light";
}

const form = reactive({
  host: "",
  path: "/cdn-cgi/trace",
  scheme: "https",
  port: 443,
  candidates: "candidates/cloudflare_common.txt",
  sample_strategy: "spread",
  sample_per_cidr: 4,
  per_prefix_len: 24,
  sample_per_prefix: 1,
  limit: null,
  repeat: 3,
  concurrency: 8,
  connect_timeout: 3,
  timeout: 6,
  method: "GET",
  http: "h2",
  max_bytes: 4096,
  ok_status: "200",
  top: 15,
});

const defaults = ref(null);
const candidateFiles = ref([]);
const current = ref(null);
const history = ref([]);
const selected = ref(null);
const loading = ref(false);
const error = ref("");
const copied = ref("");
const theme = ref(storedTheme());
const activeNav = ref("dashboard");
const runsSection = ref(null);
const workspaceTop = ref(null);
let timer = null;

setDocumentTheme(theme.value);

const running = computed(() => current.value?.status === "queued" || current.value?.status === "running");
const progress = computed(() => {
  if (!current.value?.total) return 0;
  return Math.round((current.value.completed / current.value.total) * 100);
});
const rows = computed(() => selected.value?.summary || current.value?.rows || []);
const hint = computed(() => selected.value?.hint || null);
const bestIp = computed(() => selected.value?.best_ip || current.value?.best_ip || "");
const statusLabel = computed(() => current.value?.status || "idle");
const activeRunId = computed(() => selected.value?.run_id || current.value?.run_id || "");
const scanTarget = computed(() => {
  const host = form.host || "cdn.example.com";
  const path = form.path || "/";
  return `${form.scheme}://${host}${path}`;
});
const passRate = computed(() => {
  if (!current.value?.completed) return "0%";
  return `${Math.round((current.value.ok / current.value.completed) * 100)}%`;
});
const elapsed = computed(() => {
  if (!current.value?.started_at) return "-";
  const end = current.value.finished_at || Date.now() / 1000;
  return `${Math.max(0, end - current.value.started_at).toFixed(1)}s`;
});
const themeTitle = computed(() => (theme.value === "night" ? "Switch to light" : "Switch to night"));

function applyRequest(req) {
  Object.assign(form, req);
  if (form.limit === undefined) form.limit = null;
}

function toggleTheme() {
  theme.value = theme.value === "night" ? "light" : "night";
  window.localStorage.setItem("cdn-ip-probe-theme", theme.value);
  setDocumentTheme(theme.value);
}

async function showDashboard() {
  activeNav.value = "dashboard";
  await nextTick();
  workspaceTop.value?.scrollIntoView({ block: "start", behavior: "smooth" });
}

async function showRuns() {
  activeNav.value = "runs";
  await loadHistory();
  await nextTick();
  runsSection.value?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  runsSection.value?.focus({ preventScroll: true });
}

async function loadDefaults() {
  error.value = "";
  const data = await api.get("/api/defaults");
  defaults.value = data.request;
  candidateFiles.value = data.candidate_files;
  applyRequest(data.request);
}

async function loadHistory() {
  history.value = await api.get("/api/results");
}

async function refreshSelected(runId) {
  selected.value = await api.get(`/api/results/${runId}`);
}

async function startScan() {
  loading.value = true;
  error.value = "";
  selected.value = null;
  try {
    const payload = { ...form, limit: form.limit || null };
    current.value = await api.post("/api/scans", payload);
    pollScan();
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}

async function pollScan() {
  if (!current.value) return;
  window.clearTimeout(timer);
  try {
    current.value = await api.get(`/api/scans/${current.value.id}`);
    if (current.value.status === "done") {
      await loadHistory();
      if (current.value.run_id) await refreshSelected(current.value.run_id);
      return;
    }
    if (current.value.status === "failed") {
      error.value = current.value.error;
      return;
    }
    timer = window.setTimeout(pollScan, 800);
  } catch (err) {
    error.value = err.message;
  }
}

async function chooseRun(runId) {
  error.value = "";
  await refreshSelected(runId);
}

async function copyText(text, label) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
  copied.value = label;
  window.setTimeout(() => {
    copied.value = "";
  }, 1200);
}

function fileUrl(name) {
  const runId = activeRunId.value;
  return runId ? `/api/results/${runId}/files/${name}` : "#";
}

function fmtMs(value) {
  const num = Number(value || 0);
  return num ? `${num.toFixed(0)} ms` : "-";
}

function fmtRate(value) {
  return `${(Number(value || 0) * 100).toFixed(0)}%`;
}

function fmtSpeed(value) {
  let num = Number(value || 0);
  if (!num) return "-";
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let index = 0;
  while (num >= 1024 && index < units.length - 1) {
    num /= 1024;
    index += 1;
  }
  return `${num >= 10 ? num.toFixed(0) : num.toFixed(1)} ${units[index]}`;
}

function resetDefaults() {
  if (defaults.value) applyRequest(defaults.value);
}

onMounted(async () => {
  try {
    await loadDefaults();
    await loadHistory();
  } catch (err) {
    error.value = err.message;
  }
});

onUnmounted(() => window.clearTimeout(timer));
</script>

<template>
  <main class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <Zap :size="22" />
        </div>
        <div>
          <strong>CDN IP Probe</strong>
          <span>Edge scanner</span>
        </div>
      </div>

      <nav class="nav-list" aria-label="Primary">
        <button :class="{ active: activeNav === 'dashboard' }" type="button" @click="showDashboard">
          <Gauge :size="18" />
          <span>Dashboard</span>
        </button>
        <button :class="{ active: activeNav === 'runs' }" type="button" @click="showRuns">
          <History :size="18" />
          <span>Runs</span>
        </button>
      </nav>

      <section ref="runsSection" class="sidebar-section" :class="{ spotlight: activeNav === 'runs' }" tabindex="-1">
        <div class="section-label">
          <span>Recent Runs</span>
          <button class="icon-btn small" title="Refresh history" type="button" @click="loadHistory">
            <RefreshCw :size="15" />
          </button>
        </div>
        <div class="runs">
          <button
            v-for="run in history"
            :key="run.run_id"
            :class="{ active: selected?.run_id === run.run_id }"
            type="button"
            @click="chooseRun(run.run_id)"
          >
            <span>{{ run.run_id }}</span>
            <strong>{{ run.best_ip || "-" }}</strong>
          </button>
          <p v-if="!history.length" class="muted-note">No saved runs</p>
        </div>
      </section>
    </aside>

    <section ref="workspaceTop" class="workspace">
      <header class="topbar">
        <div class="title-block">
          <span class="eyebrow">Probe Console</span>
          <h1>{{ form.host || "cdn.example.com" }}</h1>
          <p>{{ scanTarget }}</p>
        </div>
        <div class="top-actions">
          <button class="theme-toggle" :title="themeTitle" type="button" @click="toggleTheme">
            <Sun v-if="theme === 'night'" :size="17" />
            <Moon v-else :size="17" />
            <span>{{ theme === "night" ? "Light" : "Night" }}</span>
          </button>
          <button class="icon-btn" title="Reload history" type="button" @click="loadHistory">
            <RefreshCw :size="18" />
          </button>
          <button class="primary" :disabled="running || loading" type="button" @click="startScan">
            <LoaderCircle v-if="running || loading" class="spin" :size="18" />
            <Play v-else :size="18" />
            <span>{{ running ? "Scanning" : "Start Scan" }}</span>
          </button>
        </div>
      </header>

      <section v-if="error" class="error">{{ error }}</section>

      <section class="summary-strip" aria-label="Scan summary">
        <div class="stat-tile">
          <span>Status</span>
          <strong>{{ statusLabel }}</strong>
        </div>
        <div class="stat-tile">
          <span>Progress</span>
          <strong>{{ progress }}%</strong>
        </div>
        <div class="stat-tile">
          <span>Pass Rate</span>
          <strong>{{ passRate }}</strong>
        </div>
        <div class="stat-tile">
          <span>Best IP</span>
          <strong class="mono">{{ bestIp || "-" }}</strong>
        </div>
      </section>

      <section class="content-grid">
        <aside class="panel config-panel">
          <div class="panel-head">
            <div>
              <Settings2 :size="17" />
              <h2>Scan Config</h2>
            </div>
            <button class="icon-btn small" title="Reset defaults" type="button" @click="resetDefaults">
              <RotateCcw :size="15" />
            </button>
          </div>

          <div class="field-stack">
            <label>
              <span>Host</span>
              <input v-model.trim="form.host" placeholder="cdn.example.com" />
            </label>

            <div class="two">
              <label>
                <span>Path</span>
                <input v-model.trim="form.path" />
              </label>
              <label>
                <span>Port</span>
                <input v-model.number="form.port" type="number" min="1" max="65535" />
              </label>
            </div>

            <div class="segmented">
              <button :class="{ active: form.scheme === 'https' }" type="button" @click="form.scheme = 'https'">
                HTTPS
              </button>
              <button :class="{ active: form.scheme === 'http' }" type="button" @click="form.scheme = 'http'">
                HTTP
              </button>
            </div>

            <label>
              <span>Candidates</span>
              <select v-model="form.candidates">
                <option v-for="file in candidateFiles" :key="file" :value="file">{{ file }}</option>
              </select>
            </label>

            <div class="two">
              <label>
                <span>Repeat</span>
                <input v-model.number="form.repeat" type="number" min="1" max="20" />
              </label>
              <label>
                <span>Concurrency</span>
                <input v-model.number="form.concurrency" type="number" min="1" max="128" />
              </label>
            </div>

            <div class="two">
              <label>
                <span>Connect</span>
                <input v-model.number="form.connect_timeout" type="number" min="0.1" max="30" step="0.1" />
              </label>
              <label>
                <span>Timeout</span>
                <input v-model.number="form.timeout" type="number" min="0.1" max="120" step="0.1" />
              </label>
            </div>

            <div class="two">
              <label>
                <span>HTTP</span>
                <select v-model="form.http">
                  <option value="auto">auto</option>
                  <option value="h1">h1</option>
                  <option value="h2">h2</option>
                  <option value="h3">h3</option>
                </select>
              </label>
              <label>
                <span>Method</span>
                <select v-model="form.method">
                  <option>GET</option>
                  <option>HEAD</option>
                </select>
              </label>
            </div>

            <div class="two">
              <label>
                <span>OK Status</span>
                <input v-model.trim="form.ok_status" />
              </label>
              <label>
                <span>Top</span>
                <input v-model.number="form.top" type="number" min="1" max="100" />
              </label>
            </div>

            <div class="segmented">
              <button
                :class="{ active: form.sample_strategy === 'spread' }"
                type="button"
                @click="form.sample_strategy = 'spread'"
              >
                Spread
              </button>
              <button
                :class="{ active: form.sample_strategy === 'per-prefix' }"
                type="button"
                @click="form.sample_strategy = 'per-prefix'"
              >
                Prefix
              </button>
            </div>

            <div v-if="form.sample_strategy === 'spread'" class="two">
              <label>
                <span>Per CIDR</span>
                <input v-model.number="form.sample_per_cidr" type="number" min="1" max="256" />
              </label>
              <label>
                <span>Limit</span>
                <input v-model.number="form.limit" type="number" min="1" placeholder="none" />
              </label>
            </div>

            <div v-else class="two">
              <label>
                <span>Prefix</span>
                <input v-model.number="form.per_prefix_len" type="number" min="0" max="128" />
              </label>
              <label>
                <span>Per Prefix</span>
                <input v-model.number="form.sample_per_prefix" type="number" min="1" max="256" />
              </label>
            </div>
          </div>
        </aside>

        <section class="panel results-panel">
          <div class="panel-head">
            <div>
              <Activity :size="17" />
              <h2>Probe Results</h2>
            </div>
            <div class="status-pill">
              <span class="pulse" :class="{ live: running }"></span>
              <span>{{ statusLabel }}</span>
            </div>
          </div>

          <div class="result-meta">
            <div>
              <span>Completed</span>
              <strong>{{ current?.completed || 0 }}/{{ current?.total || 0 }}</strong>
            </div>
            <div>
              <span>OK</span>
              <strong>{{ current?.ok || 0 }}</strong>
            </div>
            <div>
              <span>Elapsed</span>
              <strong>{{ elapsed }}</strong>
            </div>
          </div>

          <div class="progress">
            <span :style="{ width: `${progress}%` }"></span>
          </div>

          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>IP</th>
                  <th>OK</th>
                  <th>Total</th>
                  <th>TTFB</th>
                  <th>TLS</th>
                  <th>Speed</th>
                  <th>Code</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in rows" :key="row.ip">
                  <td>{{ index + 1 }}</td>
                  <td class="mono">{{ row.ip }}</td>
                  <td>{{ row.success }}/{{ row.attempts }} · {{ fmtRate(row.success_rate) }}</td>
                  <td>{{ fmtMs(row.total_ms_p50) }}</td>
                  <td>{{ fmtMs(row.ttfb_ms_p50) }}</td>
                  <td>{{ fmtMs(row.tls_ms_p50) }}</td>
                  <td>{{ fmtSpeed(row.speed_bps_avg) }}</td>
                  <td>{{ row.http_codes || "-" }}</td>
                  <td>
                    <button
                      class="icon-btn small"
                      :title="copied === row.ip ? 'Copied' : 'Copy IP'"
                      type="button"
                      @click="copyText(row.ip, row.ip)"
                    >
                      <Clipboard :size="15" />
                    </button>
                  </td>
                </tr>
                <tr v-if="!rows.length">
                  <td colspan="9" class="empty">No rows</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <aside class="panel detail-panel">
          <div class="panel-head">
            <div>
              <Server :size="17" />
              <h2>Connection</h2>
            </div>
          </div>

          <dl class="connection-list">
            <div>
              <dt>IP</dt>
              <dd class="mono">{{ hint?.connect_address || bestIp || "-" }}</dd>
            </div>
            <div>
              <dt>SNI</dt>
              <dd class="mono">{{ hint?.keep_sni || form.host || "-" }}</dd>
            </div>
            <div>
              <dt>Host</dt>
              <dd class="mono">{{ hint?.keep_host_header || form.host || "-" }}</dd>
            </div>
            <div>
              <dt>Port</dt>
              <dd class="mono">{{ hint?.keep_port || form.port || "-" }}</dd>
            </div>
          </dl>

          <button class="ghost" type="button" @click="copyText(JSON.stringify(hint || {}, null, 2), 'connection')">
            <Clipboard :size="16" />
            <span>{{ copied === "connection" ? "Copied" : "Copy JSON" }}</span>
          </button>

          <section class="downloads">
            <div class="downloads-head">
              <FileDown :size="16" />
              <h2>Files</h2>
            </div>
            <a v-for="name in selected?.files || []" :key="name" :href="fileUrl(name)">
              <Download :size="15" />
              <span>{{ name }}</span>
            </a>
            <p v-if="!(selected?.files || []).length" class="muted-note">No files selected</p>
          </section>
        </aside>
      </section>
    </section>
  </main>
</template>
