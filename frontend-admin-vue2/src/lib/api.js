export const API_BASE = getApiBase();

export async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers: new Headers(options.headers),
  });
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
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

function getApiBase() {
  const configured = import.meta.env && import.meta.env.VITE_API_BASE;
  if (configured) return configured.replace(/\/$/, "");
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}
