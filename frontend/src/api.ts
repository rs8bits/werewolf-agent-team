import type { CreateGameRequest, GameState, PersistedEvent } from "./types";

const DEFAULT_API_BASE = "http://127.0.0.1:8001";

export const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? DEFAULT_API_BASE;

export function gameEventsWebSocketUrl(gameId: string): string {
  const wsBase = API_BASE.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
  return `${wsBase}/ws/games/${encodeURIComponent(gameId)}/events`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? (data as { detail?: unknown }).detail
        : null;
    const message =
      typeof detail === "string"
        ? detail
        : text.trim() || `${response.status} ${response.statusText}`.trim();
    throw new Error(`请求失败：${message}`);
  }
  return data as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {})
      }
    });
    return parseResponse<T>(response);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`无法连接 API：${API_BASE}`);
    }
    throw error;
  }
}

export async function health(): Promise<{ status: string }> {
  return request("/health", { method: "GET" });
}

export async function createGame(body: CreateGameRequest): Promise<GameState> {
  const payload = {
    player_count: body.player_count,
    agent_mode: body.agent_mode,
    model: body.agent_mode === "llm" ? body.model || "qwen3.5-27b" : null
  };
  return request("/games", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getGame(gameId: string): Promise<GameState> {
  return request(`/games/${encodeURIComponent(gameId)}`, { method: "GET" });
}

export async function runCycle(gameId: string): Promise<GameState> {
  return request(`/games/${encodeURIComponent(gameId)}/run-cycle`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function runUntilFinished(
  gameId: string,
  maxCycles: number
): Promise<GameState> {
  return request(`/games/${encodeURIComponent(gameId)}/run-until-finished`, {
    method: "POST",
    body: JSON.stringify({ max_cycles: maxCycles })
  });
}

export async function getEvents(gameId: string): Promise<PersistedEvent[]> {
  return request(`/games/${encodeURIComponent(gameId)}/events`, { method: "GET" });
}
