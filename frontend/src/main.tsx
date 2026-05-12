import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BadgeCheck,
  Bot,
  CircleAlert,
  Crown,
  Eye,
  FastForward,
  Loader2,
  MessageCircle,
  Moon,
  Play,
  RefreshCw,
  Search,
  Shield,
  Swords,
  Users,
  Wifi,
  WifiOff
} from "lucide-react";
import {
  API_BASE,
  createGame,
  gameEventsWebSocketUrl,
  getEvents,
  getGame,
  health,
  runCycle,
  runUntilFinished
} from "./api";
import type {
  AgentMode,
  Camp,
  GameEventPayload,
  GameState,
  LiveMessage,
  PersistedEvent,
  PlayerState
} from "./types";
import "./styles.css";

const STORAGE_KEY = "werewolf:lastGameId";

const phaseLabels: Record<string, string> = {
  setup: "准备",
  night: "夜晚",
  day: "白天",
  vote: "投票",
  ended: "结束"
};

const roleLabels: Record<string, string> = {
  werewolf: "狼人",
  seer: "预言家",
  witch: "女巫",
  villager: "平民",
  hunter: "猎人",
  idiot: "白痴",
  guard: "守卫"
};

const campLabels: Record<Camp, string> = {
  werewolf: "狼人",
  good: "好人"
};

function isCamp(value: unknown): value is Camp {
  return value === "werewolf" || value === "good";
}

function compactJson(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value, null, 2);
}

function eventTitle(event: GameEventPayload): string {
  const seat = typeof event.seat_no === "number" ? `${event.seat_no}号` : "";
  const target =
    typeof event.target_seat_no === "number" ? ` → ${event.target_seat_no}号` : "";
  switch (event.type) {
    case "night_action":
      return `${seat} ${event.action_type ?? "夜间行动"}${target}`;
    case "speech":
      return `${seat} 发言`;
    case "vote_cast":
      return `${seat} 投票${target}`;
    case "vote_resolved":
      return "投票结算";
    case "night_resolved":
      return "夜晚结算";
    case "player_death":
      return `${seat} 死亡`;
    case "sheriff_elected":
      return "警长竞选结果";
    case "pk_started":
      return "平票 PK";
    case "hunter_shot":
      return `${seat} 猎人开枪${target}`;
    case "idiot_revealed":
      return `${seat} 白痴翻牌`;
    default:
      return event.type;
  }
}

function eventBody(event: GameEventPayload): string {
  if (typeof event.content === "string") return event.content;
  if (typeof event.reasoning_summary === "string") return event.reasoning_summary;
  if (event.type === "vote_resolved") {
    return `出局：${event.eliminated_seat_no ?? "无人"}；票型：${compactJson(event.vote_counts)}`;
  }
  if (event.type === "night_resolved") {
    return `死亡：${compactJson(event.deaths)}；原因：${compactJson(event.death_reasons)}`;
  }
  return compactJson(event);
}

function StatusPill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

function playerSubtitle(player: PlayerState): string {
  return `${roleLabels[player.role] ?? player.role} / ${campLabels[player.camp]}`;
}

function RoundTable({
  game,
  activeSeatNo,
  activeSpeech
}: {
  game: GameState | null;
  activeSeatNo: number | null;
  activeSpeech: PersistedEvent | null;
}) {
  if (!game) {
    return <div className="empty">还没有对局</div>;
  }

  const total = game.players.length;
  return (
    <div className="round-table-wrap">
      <div className="round-table">
        <div className="table-center">
          <span>{phaseLabels[game.public_state.phase]}</span>
          <strong>第 {game.public_state.round} 轮</strong>
          <p>{activeSpeech ? eventBody(activeSpeech.event) : "等待发言或行动"}</p>
        </div>
        {game.players.map((player, index) => {
          const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;
          const x = 50 + Math.cos(angle) * 42;
          const y = 50 + Math.sin(angle) * 42;
          const isActive = activeSeatNo === player.seat_no;
          return (
            <article
              className={`table-seat ${player.camp} ${player.status.alive ? "" : "dead"} ${
                isActive ? "active" : ""
              }`}
              key={player.seat_no}
              style={{ left: `${x}%`, top: `${y}%` }}
            >
              <div className="table-seat-head">
                <strong>{player.seat_no}号</strong>
                {game.sheriff_seat_no === player.seat_no && <Crown size={14} />}
              </div>
              <span>{player.name}</span>
              <small>{playerSubtitle(player)}</small>
              <em>{player.status.alive ? "存活" : "死亡"}</em>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function App() {
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "down">("checking");
  const [playerCount, setPlayerCount] = useState<6 | 12>(12);
  const [agentMode, setAgentMode] = useState<AgentMode>("scripted");
  const [model, setModel] = useState("qwen3.5-27b");
  const [maxCycles, setMaxCycles] = useState(10);
  const [gameIdInput, setGameIdInput] = useState(() => localStorage.getItem(STORAGE_KEY) ?? "");
  const [game, setGame] = useState<GameState | null>(null);
  const [events, setEvents] = useState<PersistedEvent[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wsStatus, setWsStatus] = useState<"idle" | "connecting" | "live" | "closed">("idle");

  const currentGameId = game?.game_id ?? gameIdInput.trim();
  const aliveCount = game?.players.filter((p) => p.status.alive).length ?? 0;
  const wolfAlive =
    game?.players.filter((p) => p.status.alive && p.camp === "werewolf").length ?? 0;

  const latestEvents = useMemo(() => [...events].reverse(), [events]);
  const activeEvent = events.length ? events[events.length - 1].event : null;
  const activeSeatNo = typeof activeEvent?.seat_no === "number" ? activeEvent.seat_no : null;
  const speechEvents = useMemo(
    () => events.filter((item) => item.event.type === "speech" || item.event.type === "pk_speech"),
    [events]
  );
  const latestSpeech = speechEvents.length ? speechEvents[speechEvents.length - 1] : null;

  async function withBusy(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(null);
    }
  }

  async function loadGame(gameId: string) {
    const trimmed = gameId.trim();
    if (!trimmed) throw new Error("请输入 game_id");
    const [nextGame, nextEvents] = await Promise.all([getGame(trimmed), getEvents(trimmed)]);
    setGame(nextGame);
    setEvents(nextEvents);
    setGameIdInput(trimmed);
    localStorage.setItem(STORAGE_KEY, trimmed);
  }

  async function refreshHealth() {
    try {
      await health();
      setApiStatus("ok");
    } catch {
      setApiStatus("down");
    }
  }

  useEffect(() => {
    refreshHealth();
    const lastGameId = localStorage.getItem(STORAGE_KEY);
    if (lastGameId) {
      loadGame(lastGameId).catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (!game?.game_id) {
      setWsStatus("idle");
      return;
    }

    let closedByEffect = false;
    const socket = new WebSocket(gameEventsWebSocketUrl(game.game_id));
    setWsStatus("connecting");

    socket.onopen = () => {
      if (!closedByEffect) setWsStatus("live");
    };

    socket.onmessage = (messageEvent) => {
      const message = JSON.parse(messageEvent.data) as LiveMessage;
      if ("error" in message) {
        setError(message.error);
        return;
      }
      if (message.type === "snapshot") {
        setGame(message.game);
        setEvents(message.events);
        return;
      }
      if (message.type === "event") {
        if (message.game) setGame(message.game);
        setEvents((current) => {
          if (current.some((item) => item.sequence === message.sequence)) {
            return current;
          }
          return [
            ...current,
            {
              sequence: message.sequence,
              event: message.event,
              created_at: null
            }
          ].sort((a, b) => a.sequence - b.sequence);
        });
        return;
      }
      if (message.type === "state") {
        setGame(message.game);
      }
    };

    socket.onerror = () => {
      if (!closedByEffect) setWsStatus("closed");
    };

    socket.onclose = () => {
      if (!closedByEffect) setWsStatus("closed");
    };

    return () => {
      closedByEffect = true;
      socket.close();
    };
  }, [game?.game_id]);

  const winnerText = isCamp(game?.winner) ? `${campLabels[game.winner]}胜利` : "未决";

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">Werewolf Agent Team</div>
          <h1>狼人杀对局控制台</h1>
        </div>
        <div className="topbar-meta">
          <StatusPill tone={wsStatus === "live" ? "good" : wsStatus === "closed" ? "bad" : "warn"}>
            {wsStatus === "live" ? <Wifi size={14} /> : <WifiOff size={14} />} WS{" "}
            {wsStatus === "live"
              ? "实时"
              : wsStatus === "connecting"
                ? "连接中"
                : wsStatus === "closed"
                  ? "断开"
                  : "待连接"}
          </StatusPill>
          <StatusPill tone={apiStatus === "ok" ? "good" : apiStatus === "down" ? "bad" : "warn"}>
            <Activity size={14} /> API {apiStatus === "ok" ? "在线" : apiStatus === "down" ? "离线" : "检查中"}
          </StatusPill>
          <span className="api-base">{API_BASE}</span>
        </div>
      </header>

      <section className="summary-band">
        <div className="metric">
          <span>Game ID</span>
          <strong>{game?.game_id ?? "未载入"}</strong>
        </div>
        <div className="metric">
          <span>阶段</span>
          <strong>{phaseLabels[game?.public_state.phase ?? "setup"]}</strong>
        </div>
        <div className="metric">
          <span>轮次</span>
          <strong>{game?.public_state.round ?? 0}</strong>
        </div>
        <div className="metric">
          <span>存活</span>
          <strong>{game ? `${aliveCount}/${game.players.length}` : "-"}</strong>
        </div>
        <div className="metric">
          <span>狼存活</span>
          <strong>{game ? wolfAlive : "-"}</strong>
        </div>
        <div className="metric">
          <span>胜负</span>
          <strong>{winnerText}</strong>
        </div>
      </section>

      <div className="workspace">
        <section className="control-panel">
          <div className="section-title">
            <Play size={18} />
            <h2>开局与运行</h2>
          </div>

          <div className="field-row">
            <label>人数</label>
            <div className="segmented">
              {[6, 12].map((count) => (
                <button
                  key={count}
                  className={playerCount === count ? "active" : ""}
                  onClick={() => setPlayerCount(count as 6 | 12)}
                  type="button"
                >
                  {count} 人
                </button>
              ))}
            </div>
          </div>

          <div className="field-row">
            <label>Agent</label>
            <div className="segmented">
              <button
                className={agentMode === "scripted" ? "active" : ""}
                onClick={() => setAgentMode("scripted")}
                type="button"
              >
                脚本
              </button>
              <button
                className={agentMode === "llm" ? "active" : ""}
                onClick={() => setAgentMode("llm")}
                type="button"
              >
                Qwen
              </button>
            </div>
          </div>

          <div className="field-row">
            <label htmlFor="model">模型</label>
            <input
              id="model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              disabled={agentMode === "scripted"}
            />
          </div>

          <div className="button-grid">
            <button
              className="primary"
              type="button"
              disabled={Boolean(busy)}
              onClick={() =>
                withBusy(agentMode === "llm" ? "创建 Qwen 对局" : "创建对局", async () => {
                  const next = await createGame({
                    player_count: playerCount,
                    agent_mode: agentMode,
                    model
                  });
                  setGame(next);
                  setEvents(await getEvents(next.game_id));
                  setGameIdInput(next.game_id);
                  localStorage.setItem(STORAGE_KEY, next.game_id);
                })
              }
            >
              <Users size={16} /> 创建对局
            </button>
            <button
              type="button"
              disabled={!currentGameId || Boolean(busy)}
              onClick={() => withBusy("运行一轮", async () => {
                const next = await runCycle(currentGameId);
                setGame(next);
                setEvents(await getEvents(next.game_id));
              })}
            >
              <Moon size={16} /> 运行一轮
            </button>
            <button
              type="button"
              disabled={!currentGameId || Boolean(busy)}
              onClick={() => withBusy("运行至结束", async () => {
                const next = await runUntilFinished(currentGameId, maxCycles);
                setGame(next);
                setEvents(await getEvents(next.game_id));
              })}
            >
              <FastForward size={16} /> 跑到结束
            </button>
            <button
              type="button"
              disabled={!currentGameId || Boolean(busy)}
              onClick={() => withBusy("刷新", () => loadGame(currentGameId))}
            >
              <RefreshCw size={16} /> 刷新
            </button>
          </div>

          <div className="field-row">
            <label htmlFor="max-cycles">最大轮数</label>
            <input
              id="max-cycles"
              type="number"
              min={1}
              max={200}
              value={maxCycles}
              onChange={(event) => setMaxCycles(Number(event.target.value))}
            />
          </div>

          <div className="load-row">
            <input
              value={gameIdInput}
              onChange={(event) => setGameIdInput(event.target.value)}
              placeholder="输入已有 game_id"
            />
            <button
              type="button"
              disabled={Boolean(busy)}
              onClick={() => withBusy("载入对局", () => loadGame(gameIdInput))}
            >
              <Search size={16} /> 载入
            </button>
          </div>

          {busy && (
            <div className="notice">
              <Loader2 className="spin" size={16} />
              {busy}中{agentMode === "llm" ? "，真实模型调用可能较慢" : ""}
            </div>
          )}
          {error && (
            <div className="notice error">
              <CircleAlert size={16} />
              {error}
            </div>
          )}
        </section>

        <section className="players-panel">
          <div className="section-title">
            <Swords size={18} />
            <h2>圆桌席位</h2>
          </div>
          <RoundTable game={game} activeSeatNo={activeSeatNo} activeSpeech={latestSpeech} />
          <div className="speech-order">
            <div className="section-title compact">
              <MessageCircle size={16} />
              <h3>发言顺序</h3>
            </div>
            <div className="speech-list">
              {speechEvents.map((item) => (
                <article
                  className={`speech-item ${
                    activeSeatNo === item.event.seat_no ? "active" : ""
                  }`}
                  key={item.sequence}
                >
                  <span>#{item.sequence}</span>
                  <strong>{item.event.seat_no as number}号</strong>
                  <p>{eventBody(item.event)}</p>
                </article>
              ))}
              {!speechEvents.length && <div className="empty slim">暂无发言</div>}
            </div>
          </div>
        </section>

        <section className="events-panel">
          <div className="section-title">
            <Eye size={18} />
            <h2>事件日志</h2>
          </div>
          <div className="event-list">
            {latestEvents.map((item) => (
              <article className="event-row" key={item.sequence}>
                <div className="event-meta">
                  <span>#{item.sequence}</span>
                  <StatusPill>{item.event.type}</StatusPill>
                </div>
                <div>
                  <h3>{eventTitle(item.event)}</h3>
                  <p>{eventBody(item.event)}</p>
                </div>
              </article>
            ))}
            {!latestEvents.length && <div className="empty">暂无事件</div>}
          </div>
        </section>

        <section className="state-panel">
          <div className="section-title">
            <Shield size={18} />
            <h2>规则校验</h2>
          </div>
          <div className="state-block">
            <h3>
              <BadgeCheck size={15} /> 运行状态
            </h3>
            <pre>{compactJson(game?.runtime_state ?? {})}</pre>
          </div>
          <div className="state-block">
            <h3>
              <Bot size={15} /> 真相状态
            </h3>
            <pre>{compactJson(game?.truth_state ?? {})}</pre>
          </div>
        </section>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
