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
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : `请求失败：${response.status}`);
  }
  return data as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  return parseResponse<T>(response);
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
