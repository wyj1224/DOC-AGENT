export const API_BASE = getApiBase();

export async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers,
  });
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
}

const ADMIN_TOKEN_KEY = "doc_agent_admin_token";

// Requests that change shared data need the admin token; ask once and remember it in this browser.
export async function adminRequest(path, options = {}) {
  let token = readAdminToken();
  if (!token) {
    token = (window.prompt("请输入管理员口令") || "").trim();
    if (!token) throw new Error("需要管理员口令");
  }
  const headers = new Headers(options.headers);
  headers.set("X-Admin-Token", token);
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers,
  });
  if (response.status === 401) {
    writeAdminToken("");
    throw new Error(await responseError(response));
  }
  if (!response.ok) throw new Error(await responseError(response));
  writeAdminToken(token);
  return response.json();
}

function readAdminToken() {
  try {
    return window.localStorage.getItem(ADMIN_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function writeAdminToken(token) {
  try {
    if (token) window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
    else window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    // Storage may be unavailable; the user is simply asked again next time.
  }
}

export async function streamAgentCheck(form, onEvent, signal) {
  const response = await fetch(`${API_BASE}/agent/check/stream`, {
    method: "POST",
    credentials: "include",
    body: form,
    signal,
  });
  if (!response.ok) throw new Error(await responseError(response));
  if (!response.body) throw new Error("当前浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += value
      ? decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n")
      : decoder.decode().replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    frames.filter(Boolean).forEach((frame) => onEvent(parseEvent(frame)));
    if (done) break;
  }
  if (buffer.trim()) onEvent(parseEvent(buffer));
}

export async function downloadWordDocument(documentId, fileName) {
  const response = await fetch(`${API_BASE}/word/documents/${documentId}/download`, {
    credentials: "include",
  });
  if (!response.ok) throw new Error(await responseError(response));
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

export function errorMessage(error) {
  if (!(error instanceof Error)) return "请求失败";
  if (error.message === "Load failed" || error.message === "Failed to fetch") {
    return "请求失败：请确认后端服务已经启动。";
  }
  return error.message;
}

async function responseError(response) {
  const text = await response.text();
  try {
    const detail = JSON.parse(text).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // Use raw response.
  }
  return text || response.statusText;
}

function parseEvent(frame) {
  let type = "delta";
  const dataLines = [];
  frame.split("\n").forEach((line) => {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  });
  const dataText = dataLines.join("\n");
  return { type, data: dataText ? JSON.parse(dataText) : {} };
}

function getApiBase() {
  const configured = import.meta.env && import.meta.env.VITE_API_BASE;
  if (configured) return configured.replace(/\/$/, "");
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}
