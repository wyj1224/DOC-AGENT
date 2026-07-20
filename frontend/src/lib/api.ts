export const API_BASE = getApiBase();
export const AUTH_TOKEN_KEY = "clause_agent_access_token";

export type AgentStreamEvent = {
  type: "status" | "result" | "delta" | "done" | "error";
  data: Record<string, unknown>;
};

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = authorizedHeaders(options?.headers);
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
}

export async function streamAgentCheck(
  form: FormData,
  onEvent: (event: AgentStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/agent/check/stream`, {
    method: "POST",
    headers: authorizedHeaders(),
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
    buffer = frames.pop() ?? "";
    frames.filter(Boolean).forEach((frame) => onEvent(parseEvent(frame)));
    if (done) break;
  }
  if (buffer.trim()) onEvent(parseEvent(buffer));
}

export async function downloadWordDocument(documentId: number, fileName: string): Promise<void> {
  const response = await fetch(`${API_BASE}/word/documents/${documentId}/download`, {
    headers: authorizedHeaders(),
  });
  if (!response.ok) throw new Error(await responseError(response));
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

export function saveAccessToken(token: string) {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAccessToken() {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
}

export function hasAccessToken() {
  return Boolean(window.localStorage.getItem(AUTH_TOKEN_KEY));
}

export function errorMessage(error: unknown) {
  if (!(error instanceof Error)) return "请求失败";
  if (error.message === "Load failed" || error.message === "Failed to fetch") {
    return "请求失败：请确认后端服务已经启动。";
  }
  return error.message;
}

function authorizedHeaders(initial?: HeadersInit) {
  const headers = new Headers(initial);
  const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

async function responseError(response: Response) {
  const text = await response.text();
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // Use the raw response below.
  }
  return text || response.statusText;
}

function parseEvent(frame: string): AgentStreamEvent {
  let type: AgentStreamEvent["type"] = "delta";
  const dataLines: string[] = [];
  frame.split("\n").forEach((line) => {
    if (line.startsWith("event:")) type = line.slice(6).trim() as AgentStreamEvent["type"];
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  });
  const dataText = dataLines.join("\n");
  return { type, data: dataText ? JSON.parse(dataText) : {} };
}

function getApiBase() {
  const configured = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE;
  return configured ? configured.replace(/\/$/, "") : "http://127.0.0.1:8000";
}
