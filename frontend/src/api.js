const BASE = "/api";

async function request(path, { method = "GET", body, form } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
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
  lengthProfile: (type, words) => request(`/length-profile?article_type=${encodeURIComponent(type)}&target_words=${words}`),
  publishStyles: () => request("/publish/styles"),
  setPublishStyle: (id, style) => request(`/projects/${id}/publish-style`, { method: "PUT", body: style }),
  review: (id) => request(`/projects/${id}/review`, { method: "POST" }),
  llmSettings: () => request("/settings/llm"),
  saveLlmSettings: (patch) => request("/settings/llm", { method: "PUT", body: patch }),
  resetLlmSettings: () => request("/settings/llm", { method: "DELETE" }),
  benchmark: () => request("/settings/llm/benchmark", { method: "POST" }),
  setLengths: (id, lengths) => request(`/projects/${id}/lengths`, { method: "PUT", body: { lengths } }),
  generate: (id, data) => request(`/projects/${id}/generate`, { method: "POST", body: data }),
  revise: (id, key, instruction, selection = "") => request(`/projects/${id}/segments/${key}/revise`, { method: "POST", body: { instruction, selection } }),
  tool: (id, key, tool, selection = "") => request(`/projects/${id}/segments/${key}/tool`, { method: "POST", body: { tool, selection } }),
  regenerate: (id, key) => request(`/projects/${id}/segments/${key}/regenerate`, { method: "POST" }),
  edit: (id, key, content) => request(`/projects/${id}/segments/${key}`, { method: "PUT", body: { content } }),
  approve: (id, key, approved) => request(`/projects/${id}/segments/${key}/approve?approved=${approved}`, { method: "POST" }),
  restore: (id, key, index) => request(`/projects/${id}/segments/${key}/restore/${index}`, { method: "POST" }),
  importDoc: (id, file) => request(`/projects/${id}/import`, { method: "POST", form: files([file], "file") }),
  fileUrl: (id, path) => `${BASE}/projects/${id}/files/${path}`,
  async download(id, fmt, draft = false, style = null) {
    const params = new URLSearchParams({ ...(draft ? { draft: "true" } : {}), ...(style || {}) });
    const res = await request(`/projects/${id}/export/${fmt}${params.toString() ? `?${params}` : ""}`);
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const name = (cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/) || [])[1] || `article.${fmt}`;
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: decodeURIComponent(name) });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  },
  events(id, onEvent) {
    const es = new EventSource(`${BASE}/projects/${id}/events`);
    es.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)); } catch { /* ignore */ }
    };
    return () => es.close();
  },
};
