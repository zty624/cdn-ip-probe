<script setup>
import {
  Activity,
  Clipboard,
  Download,
  LoaderCircle,
  Play,
  RefreshCw,
  RotateCcw,
} from "@lucide/vue";
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";

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
let timer = null;

const running = computed(() => current.value?.status === "queued" || current.value?.status === "running");
const progress = computed(() => {
  if (!current.value?.total) return 0;
  return Math.round((current.value.completed / current.value.total) * 100);
});
const rows = computed(() => selected.value?.summary || current.value?.rows || []);
const hint = computed(() => selected.value?.hint || null);
const bestIp = computed(() => selected.value?.best_ip || current.value?.best_ip || "");

function applyRequest(req) {
  Object.assign(form, req);
  if (form.limit === undefined) form.limit = null;
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
  const runId = selected.value?.run_id || current.value?.run_id;
  return runId ? `/api/results/${runId}/files/${name}` : "#";
}

function fmtMs(value) {
  const num = Number(value || 0);
  return num ? `${num.toFixed(0)} ms` : "-";
}

function fmtRate(value) {
  return `${(Number(value || 0) * 100).toFixed(0)}%`;
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
  <main class="app">
    <header class="topbar">
      <div>
        <h1>CDN IP Probe</h1>
        <p>{{ form.host }}{{ form.path }}</p>
      </div>
      <div class="top-actions">
        <button class="icon-btn" title="Reload" @click="loadHistory">
          <RefreshCw :size="18" />
        </button>
        <button class="primary" :disabled="running || loading" @click="startScan">
          <LoaderCircle v-if="running || loading" class="spin" :size="18" />
          <Play v-else :size="18" />
          <span>{{ running ? "Scanning" : "Start Scan" }}</span>
        </button>
      </div>
    </header>

    <section v-if="error" class="error">{{ error }}</section>

    <section class="grid">
      <aside class="panel config">
        <div class="panel-head">
          <h2>Scan</h2>
          <button class="icon-btn" title="Reset" @click="resetDefaults">
            <RotateCcw :size="17" />
          </button>
        </div>

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
          <button :class="{ active: form.scheme === 'https' }" @click="form.scheme = 'https'">HTTPS</button>
          <button :class="{ active: form.scheme === 'http' }" @click="form.scheme = 'http'">HTTP</button>
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
          <button :class="{ active: form.sample_strategy === 'spread' }" @click="form.sample_strategy = 'spread'">
            Spread
          </button>
          <button
            :class="{ active: form.sample_strategy === 'per-prefix' }"
            @click="form.sample_strategy = 'per-prefix'"
          >
            /Prefix
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
      </aside>

      <section class="panel results">
        <div class="panel-head">
          <h2>Results</h2>
          <div class="status">
            <Activity :size="17" />
            <span>{{ current?.status || "idle" }}</span>
          </div>
        </div>

        <div class="meters">
          <div>
            <span>Progress</span>
            <strong>{{ progress }}%</strong>
          </div>
          <div>
            <span>Completed</span>
            <strong>{{ current?.completed || 0 }}/{{ current?.total || 0 }}</strong>
          </div>
          <div>
            <span>OK</span>
            <strong>{{ current?.ok || 0 }}</strong>
          </div>
          <div>
            <span>Best</span>
            <strong>{{ bestIp || "-" }}</strong>
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
                <td>{{ Number(row.speed_bps_avg || 0).toFixed(0) }}</td>
                <td>{{ row.http_codes || "-" }}</td>
                <td>
                  <button class="icon-btn small" title="Copy IP" @click="copyText(row.ip, row.ip)">
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

      <aside class="panel side">
        <div class="panel-head">
          <h2>History</h2>
          <button class="icon-btn" title="Refresh" @click="loadHistory">
            <RefreshCw :size="17" />
          </button>
        </div>

        <div class="runs">
          <button
            v-for="run in history"
            :key="run.run_id"
            :class="{ active: selected?.run_id === run.run_id }"
            @click="chooseRun(run.run_id)"
          >
            <span>{{ run.run_id }}</span>
            <strong>{{ run.best_ip || "-" }}</strong>
          </button>
        </div>

        <div class="hint">
          <h2>Connection</h2>
          <dl>
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
          <button class="ghost" @click="copyText(JSON.stringify(hint || {}, null, 2), 'connection')">
            <Clipboard :size="16" />
            <span>{{ copied === "connection" ? "Copied" : "Copy JSON" }}</span>
          </button>
        </div>

        <div class="downloads">
          <h2>Files</h2>
          <a v-for="name in selected?.files || []" :key="name" :href="fileUrl(name)">
            <Download :size="15" />
            <span>{{ name }}</span>
          </a>
        </div>
      </aside>
    </section>
  </main>
</template>
