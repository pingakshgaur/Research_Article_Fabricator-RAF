const BASE = "/api";

// When an admin passcode is set, changing settings needs the session token returned by unlocking (Settings → Admin lock).
let adminToken = "";
try { adminToken = sessionStorage.getItem("raf-admin") || ""; } catch { /* storage unavailable */ }
const setAdminToken = (token) => {
  adminToken = token || "";
  try { adminToken ? sessionStorage.setItem("raf-admin", adminToken) : sessionStorage.removeItem("raf-admin"); } catch { /* ignore */ }
};

async function request(path, { method = "GET", body, form } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(adminToken ? { "X-RAF-Admin": adminToken } : {}) },
    body: form || (body ? JSON.stringify(body) : undefined),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res;
}

const files = (list, field = "files") => {
  const form = new FormData();
  [...list].forEach((f) => form.append(field, f));
  return form;
};

/** Hand a Blob to the browser as a download. */
export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/** Fetch a file route and save it under the name the server gives it. */
async function saveFrom(path, query = "", fallback = "download") {
  const res = await request(path + query);
  const cd = res.headers.get("content-disposition") || "";
  const name = (cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/) || [])[1] || fallback;
  saveBlob(await res.blob(), decodeURIComponent(name));
}

const qs = (params) => {
  const s = new URLSearchParams(params).toString();
  return s ? "?" + s : "";
};

export const api = {
  health: () => request("/health"),
  catalogue: () => request("/segments"),
  projects: () => request("/projects"),
  project: (id) => request(`/projects/${id}`),
  create: (data) => request("/projects", { method: "POST", body: data }),
  update: (id, data) => request(`/projects/${id}`, { method: "PATCH", body: data }),
  remove: (id) => request(`/projects/${id}`, { method: "DELETE" }),
  stage: (id, stage) => request(`/projects/${id}/stage/${stage}`, { method: "POST" }),
  uploadRefs: (id, list) => request(`/projects/${id}/references`, { method: "POST", form: files(list) }),
  removeRef: (id, rid) => request(`/projects/${id}/references/${rid}`, { method: "DELETE" }),
  uploadData: (id, list) => request(`/projects/${id}/datasets`, { method: "POST", form: files(list) }),
  removeData: (id, name) => request(`/projects/${id}/datasets/${encodeURIComponent(name)}`, { method: "DELETE" }),
  tones: () => request("/tones"),
  setTone: (id, tone) => request(`/projects/${id}/tone`, { method: "PUT", body: tone }),
  lengthProfile: (type, words) => request("/length-profile" + qs({ article_type: type, target_words: words })),
  publishStyles: () => request("/publish/styles"),
  setPublishStyle: (id, style) => request(`/projects/${id}/publish-style`, { method: "PUT", body: style }),
  review: (id) => request(`/projects/${id}/review`, { method: "POST" }),
  llmSettings: () => request("/settings/llm"),
  saveLlmSettings: (patch) => request("/settings/llm", { method: "PUT", body: patch }),
  resetLlmSettings: () => request("/settings/llm", { method: "DELETE" }),
  benchmark: () => request("/settings/llm/benchmark", { method: "POST" }),

  // ---- cloud models: the user's own API keys (the key itself is only ever sent, never read back)
  keys: () => request("/settings/llm/keys"),
  addKey: (body) => request("/settings/llm/keys", { method: "POST", body }),
  changeKey: (kid, patch) => request(`/settings/llm/keys/${kid}`, { method: "PATCH", body: patch }),
  removeKey: (kid) => request(`/settings/llm/keys/${kid}`, { method: "DELETE" }),
  orderKeys: (order) => request("/settings/llm/keys-order", { method: "PUT", body: { order } }),
  setLlmMode: (mode) => request("/settings/llm/mode" + qs({ mode }), { method: "PUT" }),
  testKey: (kid) => request(`/settings/llm/keys/${kid}/test`, { method: "POST" }),
  keyModels: (kid) => request(`/settings/llm/keys/${kid}/models`),

  // ---- RAF settings and the admin lock
  appSettings: () => request("/settings/app"),
  saveAppSettings: (patch) => request("/settings/app", { method: "PUT", body: patch }),
  resetAppSettings: () => request("/settings/app", { method: "DELETE" }),
  unlock: (passcode) => request("/settings/admin/unlock", { method: "POST", body: { passcode } }).then((r) => setAdminToken(r.token)),
  lock: () => request("/settings/admin/lock", { method: "POST" }).then(() => setAdminToken("")),
  setPasscode: (passcode) => request("/settings/admin/passcode", { method: "PUT", body: { passcode } }).then((r) => setAdminToken(r.token)),

  setLengths: (id, lengths) => request(`/projects/${id}/lengths`, { method: "PUT", body: { lengths } }),
  generate: (id, data) => request(`/projects/${id}/generate`, { method: "POST", body: data }),
  revise: (id, key, instruction, selection = "") => request(`/projects/${id}/segments/${key}/revise`, { method: "POST", body: { instruction, selection } }),
  tool: (id, key, tool, selection = "", strength = 2) => request(`/projects/${id}/segments/${key}/tool`, { method: "POST", body: { tool, selection, strength } }),
  regenerate: (id, key) => request(`/projects/${id}/segments/${key}/regenerate`, { method: "POST" }),
  edit: (id, key, content) => request(`/projects/${id}/segments/${key}`, { method: "PUT", body: { content } }),
  approve: (id, key, approved) => request(`/projects/${id}/segments/${key}/approve` + qs({ approved }), { method: "POST" }),
  restore: (id, key, index) => request(`/projects/${id}/segments/${key}/restore/${index}`, { method: "POST" }),
  importDoc: (id, file) => request(`/projects/${id}/import`, { method: "POST", form: files([file], "file") }),
  fileUrl: (id, path) => `${BASE}/projects/${id}/files/${path}`,
  download: (id, fmt, draft = false, style = null) =>
    saveFrom(`/projects/${id}/export/${fmt}`, qs({ ...(draft ? { draft: "true" } : {}), ...(style || {}) }), `article.${fmt}`),

  // ---- article structure
  gallery: () => request("/structure/gallery"),
  renameSegment: (id, key, title) => request(`/projects/${id}/structure/titles/${key}`, { method: "PUT", body: { title } }),
  addSegment: (id, body) => request(`/projects/${id}/structure/segments`, { method: "POST", body }),
  editSegment: (id, key, patch) => request(`/projects/${id}/structure/segments/${key}`, { method: "PATCH", body: patch }),
  deleteSegment: (id, key) => request(`/projects/${id}/structure/segments/${key}`, { method: "DELETE" }),
  setOrder: (id, order) => request(`/projects/${id}/structure/order`, { method: "PUT", body: { order } }),
  setIncluded: (id, key, included) => request(`/projects/${id}/structure/included/${key}` + qs({ included }), { method: "PUT" }),
  proposeParts: (id, title, purpose) => request(`/projects/${id}/structure/propose`, { method: "POST", body: { title, purpose } }),
  writeSegment: (id, key) => request(`/projects/${id}/segments/${key}/write`, { method: "POST" }),

  // ---- where the evidence comes from (source modes and the reading list of online sources)
  setSourceMode: (id, mode) => request(`/projects/${id}/source-mode` + qs({ mode }), { method: "PUT" }),
  removeSource: (id, sid) => request(`/projects/${id}/sources/${sid}`, { method: "DELETE" }),
  pinSource: (id, sid, pinned) => request(`/projects/${id}/sources/${sid}/pin` + qs({ pinned }), { method: "PUT" }),

  // ---- format an existing article
  formatUpload: (file) => request("/format", { method: "POST", form: files([file], "file") }),
  formatChecks: (id) => request(`/projects/${id}/format/checks`),
  restyleReferences: (id, style) => request(`/projects/${id}/format/restyle`, { method: "POST", body: { style } }),

  // ---- library
  rename: (id, title) => request(`/projects/${id}/rename`, { method: "POST", body: { title } }),
  duplicate: (id) => request(`/projects/${id}/duplicate`, { method: "POST" }),
  archive: (id, archived) => request(`/projects/${id}/archive` + qs({ archived }), { method: "POST" }),
  backup: (id) => saveFrom(`/projects/${id}/backup`, "", "project.raf.zip"),
  restoreBackup: (file) => request("/projects/restore", { method: "POST", form: files([file], "file") }),

  // ---- history
  history: (id) => request(`/projects/${id}/history`),
  aiStatement: (id) => request(`/projects/${id}/ai-statement`),

  // ---- revisions
  revisions: (id) => request(`/projects/${id}/revisions`),
  saveRevision: (id, name, note = "") => request(`/projects/${id}/revisions`, { method: "POST", body: { name, note } }),
  renameRevision: (id, n, name) => request(`/projects/${id}/revisions/${n}`, { method: "PATCH", body: { name } }),
  deleteRevision: (id, n) => request(`/projects/${id}/revisions/${n}`, { method: "DELETE" }),
  restoreRevision: (id, n, key = "") => request(`/projects/${id}/revisions/${n}/restore` + qs(key ? { key } : {}), { method: "POST" }),
  compare: (id, a, b) => request(`/projects/${id}/compare` + qs({ a, b })),
  exportChanges: (id, fmt, a, b) => saveFrom(`/projects/${id}/compare/export/${fmt}`, qs({ a, b }), `changes.${fmt}`),

  // ---- revision rounds
  rounds: (id) => request(`/projects/${id}/rounds`),
  createRound: (id, comments, name = "") => request(`/projects/${id}/rounds`, { method: "POST", body: { comments, name } }),
  updateRound: (id, rid, patch) => request(`/projects/${id}/rounds/${rid}`, { method: "PUT", body: patch }),
  applyRound: (id, rid) => request(`/projects/${id}/rounds/${rid}/apply`, { method: "POST" }),
  deleteRound: (id, rid) => request(`/projects/${id}/rounds/${rid}`, { method: "DELETE" }),
  letterDocx: (id, rid) => saveFrom(`/projects/${id}/rounds/${rid}/letter.docx`, "", "response.docx"),

  events(id, onEvent) {
    const es = new EventSource(`${BASE}/projects/${id}/events`);
    es.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)); } catch { /* ignore */ }
    };
    return () => es.close();
  },
};
