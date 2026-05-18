import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Bot,
  CircleAlert,
  Crown,
  Eye,
  FastForward,
  Loader2,
  Mic,
  MessageCircle,
  Moon,
  Play,
  RefreshCw,
  Search,
  Settings2,
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
  getPlayerView,
  health,
  runCycle,
  runUntilFinished,
  submitHumanAction,
  submitPlayerAction
} from "./api";
import type {
  AgentDecisionRequest,
  AgentMode,
  Camp,
  GameEventPayload,
  GameState,
  HumanSeatLink,
  LiveMessage,
  PendingHumanAction,
  PersistedEvent,
  PlayerView,
  PlayerState
} from "./types";
import "./styles.css";

const STORAGE_KEY = "werewolf:lastGameId";
const SEAT_TOKEN_STORAGE_KEY = "werewolf:seatTokens";
type SeatTokenStore = Record<string, Record<string, string>>;

function readSeatTokenStore(): SeatTokenStore {
  try {
    const raw = localStorage.getItem(SEAT_TOKEN_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function writeSeatTokenStore(store: SeatTokenStore) {
  try {
    localStorage.setItem(SEAT_TOKEN_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Ignore localStorage failures in private/incognito contexts.
  }
}

function getStoredSeatToken(gameId: string, seatNo: number): string | null {
  return readSeatTokenStore()[gameId]?.[String(seatNo)] ?? null;
}

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

const visibleEventTypes = new Set([
  "night_action",
  "night_resolved",
  "player_death",
  "sheriff_vote_cast",
  "sheriff_elected",
  "sheriff_badge_assigned",
  "sheriff_badge_destroyed",
  "pk_started",
  "sheriff_pk_started",
  "vote_cast",
  "vote_resolved",
  "hunter_shot",
  "hunter_no_shot",
  "idiot_revealed"
]);

const speechEventTypes = new Set(["sheriff_speech", "speech", "pk_speech", "sheriff_pk_speech"]);

function normalizeEvents(items: PersistedEvent[]): PersistedEvent[] {
  const bySequence = new Map<number, PersistedEvent>();
  for (const item of items) {
    if (!bySequence.has(item.sequence)) {
      bySequence.set(item.sequence, item);
    }
  }
  return Array.from(bySequence.values()).sort((a, b) => a.sequence - b.sequence);
}

function isCamp(value: unknown): value is Camp {
  return value === "werewolf" || value === "good";
}

function asNumberArray(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((item): item is number => typeof item === "number") : [];
}

function shouldShowEvent(item: PersistedEvent): boolean {
  const event = item.event;
  if (!visibleEventTypes.has(event.type)) return false;
  if (event.type === "night_resolved" && asNumberArray(event.deaths).length === 0) {
    return false;
  }
  return true;
}

function playerAlive(p: { alive?: boolean; status?: { alive: boolean } }): boolean {
  return p.alive === true || p.status?.alive === true;
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
    case "sheriff_speech":
      return `${seat} 警长竞选发言`;
    case "sheriff_vote_cast":
      return `${seat} 警长投票${target}`;
    case "speech":
      return `${seat} 发言`;
    case "pk_speech":
      return `${seat} PK 发言`;
    case "sheriff_pk_started":
      return "警长竞选平票 PK";
    case "sheriff_pk_speech":
      return `${seat} 警长竞选 PK 发言`;
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
    case "sheriff_badge_assigned":
      return `${event.from_seat_no ?? ""}号移交警徽 → ${event.to_seat_no ?? ""}号`;
    case "sheriff_badge_destroyed":
      return "警徽撕毁";
    case "pk_started":
      return "平票 PK";
    case "hunter_shot":
      return `${seat} 猎人开枪${target}`;
    case "idiot_revealed":
      return `${seat} 白痴翻牌`;
    case "round_summary":
      return `第${event.round ?? "?"}轮 发言摘要`;
    default:
      return event.type;
  }
}

function eventBody(event: GameEventPayload): string {
  if (typeof event.content === "string") return event.content;
  if (event.type === "vote_resolved") {
    return `出局：${event.eliminated_seat_no ?? "无人"}；票型：${compactJson(event.vote_counts)}`;
  }
  if (event.type === "night_resolved") {
    return `死亡：${compactJson(event.deaths)}；原因：${compactJson(event.death_reasons)}`;
  }
  if (event.type === "sheriff_speech") {
    const label = event.run ? "参选" : "不参选";
    return `${label}：${compactJson(event.content ?? "")}`;
  }
  if (event.type === "sheriff_elected") {
    const reason = event.reason ? `原因：${event.reason}` : "";
    const pk = event.pk_tied_seats ? ` PK：${compactJson(event.pk_tied_seats)}` : "";
    return `当选：${event.sheriff_seat_no ?? "无人"}；候选：${compactJson(event.candidates ?? [])}${pk}${reason}`;
  }
  if (event.type === "sheriff_pk_started") {
    return `平票候选人：${compactJson(event.tied_seats)}；票型：${compactJson(event.vote_counts)}`;
  }
  if (event.type === "sheriff_pk_speech") {
    return event.content ? String(event.content) : compactJson(event);
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
  const seatRadius = total >= 12 ? 39 : 42;
  return (
    <div className="round-table-wrap">
      <div className={`round-table ${total >= 12 ? "dense" : ""}`}>
        <div className="table-center">
          <span>{phaseLabels[game.public_state.phase]}</span>
          <strong>第 {game.public_state.round} 轮</strong>
          <p>{activeSpeech ? eventBody(activeSpeech.event) : "等待发言或行动"}</p>
        </div>
        {game.players.map((player, index) => {
          const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;
          const x = 50 + Math.cos(angle) * seatRadius;
          const y = 50 + Math.sin(angle) * seatRadius;
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
                {game.sheriff_seat_no === player.seat_no && <Crown size={12} />}
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

function PlayerRoundTable({
  view,
  activeSeatNo,
  activeSpeech
}: {
  view: PlayerView | null;
  activeSeatNo: number | null;
  activeSpeech: PersistedEvent | null;
}) {
  if (!view) {
    return <div className="empty">还没有玩家视角</div>;
  }

  const total = view.players.length;
  const seatRadius = total >= 12 ? 39 : 42;
  return (
    <div className="round-table-wrap player-round-table">
      <div className={`round-table ${total >= 12 ? "dense" : ""}`}>
        <div className="table-center">
          <span>{phaseLabels[view.phase]}</span>
          <strong>第 {view.round} 轮</strong>
          <p>
            {isCamp(view.winner)
              ? `${campLabels[view.winner]}胜利`
              : activeSpeech
                ? eventBody(activeSpeech.event)
                : "等待公开发言"}
          </p>
        </div>
        {view.players.map((player, index) => {
          const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;
          const x = 50 + Math.cos(angle) * seatRadius;
          const y = 50 + Math.sin(angle) * seatRadius;
          const isActive = activeSeatNo === player.seat_no;
          const isSelf = view.viewer_seat_no === player.seat_no;
          return (
            <article
              className={`table-seat player-seat ${player.alive ? "" : "dead"} ${
                isActive ? "active" : ""
              } ${isSelf ? "self" : ""}`}
              key={player.seat_no}
              style={{ left: `${x}%`, top: `${y}%` }}
            >
              <div className="table-seat-head">
                <strong>{player.seat_no}号</strong>
                {view.sheriff_seat_no === player.seat_no && <Crown size={12} />}
              </div>
              <span>{player.name}</span>
              <small>{player.player_type === "human" ? "真人玩家" : "AI玩家"}</small>
              <em>{player.alive ? "存活" : "死亡"}</em>
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
  const wsRetryRef = React.useRef(0);
  const wsRetryTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [humanSeats, setHumanSeats] = useState<number[]>([]);
  const [selectedSeat, setSelectedSeat] = useState<number | null>(null);
  const [playerView, setPlayerView] = useState<PlayerView | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [actionForm, setActionForm] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);
  const [seatTokenStore, setSeatTokenStore] = useState<SeatTokenStore>(() => readSeatTokenStore());

  const currentGameId = game?.game_id ?? gameIdInput.trim();
  const currentSeatTokens = currentGameId ? seatTokenStore[currentGameId] ?? {} : {};
  const storedSeatLinks: HumanSeatLink[] = currentGameId
    ? Object.entries(currentSeatTokens).map(([seat, token]) => ({
        seat_no: Number(seat),
        token,
        path: `/play/${currentGameId}/${seat}?token=${encodeURIComponent(token)}`
      }))
    : [];
  const playerLinks = game?.human_seat_links?.length ? game.human_seat_links : storedSeatLinks;

  function storeLinks(gameId: string, links: HumanSeatLink[]) {
    const nextStore = {
      ...seatTokenStore,
      [gameId]: {
        ...(seatTokenStore[gameId] ?? {}),
      }
    };
    for (const link of links) {
      nextStore[gameId][String(link.seat_no)] = link.token;
    }
    setSeatTokenStore(nextStore);
    writeSeatTokenStore(nextStore);
  }

  const aliveCount = game?.players.filter((p) => p.status.alive).length ?? 0;
  const wolfAlive =
    game?.players.filter((p) => p.status.alive && p.camp === "werewolf").length ?? 0;

  const orderedEvents = useMemo(() => normalizeEvents(events), [events]);
  const latestEvents = useMemo(
    () => orderedEvents.filter(shouldShowEvent).reverse(),
    [orderedEvents]
  );
  const activeEvent = orderedEvents.length ? orderedEvents[orderedEvents.length - 1].event : null;
  const activeSeatNo = typeof activeEvent?.seat_no === "number" ? activeEvent.seat_no : null;
  const speechEvents = useMemo(
    () => orderedEvents.filter((item) => speechEventTypes.has(item.event.type)),
    [orderedEvents]
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
      wsRetryRef.current = 0;
      if (wsRetryTimerRef.current !== null) {
        clearTimeout(wsRetryTimerRef.current);
        wsRetryTimerRef.current = null;
      }
      return;
    }

    let closedByEffect = false;
    let socket: WebSocket;
    const gameId = game.game_id;

    function connect() {
      socket = new WebSocket(gameEventsWebSocketUrl(gameId));
      setWsStatus("connecting");

      socket.onopen = () => {
        if (!closedByEffect) {
          setWsStatus("live");
          wsRetryRef.current = 0;
        }
      };

      socket.onmessage = (messageEvent) => {
        const message = JSON.parse(messageEvent.data) as LiveMessage;
        if ("error" in message) {
          setError(message.error);
          return;
        }
        if (message.type === "snapshot") {
          setGame(message.game);
          setEvents(normalizeEvents(message.events));
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
            ];
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
        if (closedByEffect) return;
        setWsStatus("closed");
        // Auto-reconnect with backoff: 1s, 2s, 4s, 8s, max 30s
        const delay = Math.min(1000 * Math.pow(2, wsRetryRef.current), 30000);
        wsRetryRef.current += 1;
        wsRetryTimerRef.current = setTimeout(() => {
          if (!closedByEffect) connect();
        }, delay);
      };
    }

    connect();

    return () => {
      closedByEffect = true;
      if (wsRetryTimerRef.current !== null) {
        clearTimeout(wsRetryTimerRef.current);
        wsRetryTimerRef.current = null;
      }
      socket.close();
    };
  }, [game?.game_id]);

  const pendingAction: PendingHumanAction | null =
    game?.runtime_state?.pending_human_action != null
      ? (game.runtime_state.pending_human_action as PendingHumanAction)
      : null;

  const winnerText = isCamp(game?.winner) ? `${campLabels[game.winner]}胜利` : "未决";
  const hasHumanPlayers =
    game?.players.some((player) => player.player_type === "human") ??
    humanSeats.length > 0;
  const autoRunLabel = hasHumanPlayers ? "推进到等待/结束" : "跑到结束";

  async function loadPlayerView(seatNo: number) {
    setViewError(null);
    try {
      const v = await getPlayerView(currentGameId, seatNo, currentSeatTokens[String(seatNo)]);
      setPlayerView(v);
    } catch (err) {
      setViewError(err instanceof Error ? err.message : "加载失败");
    }
  }

  async function handleSubmitHumanAction() {
    if (!game || pendingAction == null) return;
    const seatNo = pendingAction.seat_no;
    const selected = actionForm["selected_action_type"];
    if (typeof selected !== "string") {
      setError("请选择要执行的动作");
      return;
    }
    const actionObj: Record<string, unknown> = { action_type: selected };
    if (selected === "speak") {
      const content = actionForm["speak_content"];
      if (typeof content !== "string" || !content.trim()) {
        setError("发言内容不能为空");
        return;
      }
      actionObj["content"] = content;
    } else if (
      selected === "vote" ||
      selected === "sheriff_vote"
    ) {
      const target = actionForm["target_seat_no"];
      if (target === "abstain") {
        actionObj["target_seat_no"] = null;
      } else if (typeof target === "number") {
        actionObj["target_seat_no"] = target;
      } else {
        setError("请选择投票目标");
        return;
      }
    } else if (
      selected === "werewolf_kill" ||
      selected === "seer_check" ||
      selected === "witch_save" ||
      selected === "witch_poison"
    ) {
      const target = actionForm["target_seat_no"];
      if (typeof target !== "number") {
        setError("请选择目标");
        return;
      }
      actionObj["target_seat_no"] = target;
    }

    const body: AgentDecisionRequest = {
      action: actionObj,
      reasoning_summary: "",
    };

    setSubmitting(true);
    setError(null);
    try {
      const nextGame = await submitHumanAction(
        currentGameId, seatNo, body, currentSeatTokens[String(seatNo)]
      );
      setGame(nextGame);
      setEvents(await getEvents(nextGame.game_id));
      setActionForm({});
      if (selectedSeat != null) {
        await loadPlayerView(selectedSeat);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
      try {
        const latestGame = await getGame(currentGameId);
        setGame(latestGame);
        setEvents(await getEvents(currentGameId));
        if (selectedSeat != null) {
          await loadPlayerView(selectedSeat);
        }
      } catch {
        // Keep the original submission error visible.
      }
    } finally {
      setSubmitting(false);
    }
  }

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
                  onClick={() => {
                    const nextCount = count as 6 | 12;
                    setPlayerCount(nextCount);
                    setHumanSeats((prev) =>
                      prev.filter((s) => s >= 1 && s <= nextCount)
                    );
                  }}
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
                    model,
                    human_seats: humanSeats.length > 0 ? humanSeats : null,
                  });
                  setGame(next);
                  setEvents(await getEvents(next.game_id));
                  setGameIdInput(next.game_id);
                  localStorage.setItem(STORAGE_KEY, next.game_id);
                  setPlayerView(null);
                  setViewError(null);
                  setActionForm({});
                  if (next.human_seat_links) {
                    storeLinks(next.game_id, next.human_seat_links);
                  }
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
              onClick={() => withBusy(autoRunLabel, async () => {
                const next = await runUntilFinished(currentGameId, maxCycles);
                setGame(next);
                setEvents(await getEvents(next.game_id));
              })}
            >
              <FastForward size={16} /> {autoRunLabel}
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

          <div className="seat-config">
            <div className="section-title compact">
              <Settings2 size={16} />
              <h3>席位设置</h3>
            </div>
            <div className="config-grid">
              <button type="button" disabled title="后续支持按身份指定模型">
                <Bot size={14} /> 角色模型
              </button>
              <button type="button" disabled title="后续支持语音转文字接入">
                <Mic size={14} /> 语音输入
              </button>
            </div>
            {(playerCount === 6 || playerCount === 12) && (
              <div className="human-seat-toggle" style={{ marginTop: 8 }}>
                <span style={{ fontSize: 12, color: "#5b6d62", fontWeight: 700 }}>
                  真人席位（可多选）
                </span>
                <div className={`seat-toggle-grid ${playerCount === 12 ? "dense" : ""}`}>
                  {Array.from({ length: playerCount }, (_, i) => i + 1).map((seat) => (
                    <button
                      key={seat}
                      type="button"
                      className={`seat-toggle ${humanSeats.includes(seat) ? "active" : ""}`}
                      onClick={() =>
                        setHumanSeats((prev) =>
                          prev.includes(seat)
                            ? prev.filter((s) => s !== seat)
                            : [...prev, seat].sort((a, b) => a - b)
                        )
                      }
                    >
                      {seat}号
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {playerLinks.length > 0 && (
            <div className="player-links" style={{ marginTop: 12, borderTop: "1px solid #e0e7e2", paddingTop: 10 }}>
              <div className="section-title compact">
                <Users size={14} />
                <h3>玩家入口</h3>
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                {playerLinks.map((link) => (
                  <div key={link.seat_no} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                    <StatusPill>{link.seat_no}号</StatusPill>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#526359", fontFamily: "monospace", fontSize: 11 }}>
                      {window.location.origin}{link.path}
                    </span>
                    <button
                      type="button"
                      className="tiny"
                      onClick={() => {
                        const url = `${window.location.origin}${link.path}`;
                        window.open(url, "_blank");
                      }}
                      style={{ flexShrink: 0, minHeight: 26, padding: "2px 8px", fontSize: 11 }}
                    >
                      打开
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

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
              <h3>发言记录</h3>
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

        <section className="player-action-panel">
          <div className="section-title">
            <Users size={18} />
            <h2>玩家操作</h2>
          </div>

          {/* Seat selector + view loader */}
          <div className="field-row">
            <label>选择座位</label>
            <div className="segmented">
              {Array.from({ length: game?.players.length ?? 6 }, (_, i) => i + 1).map((seat) => (
                <button
                  key={seat}
                  className={`${selectedSeat === seat ? "active" : ""} ${
                    pendingAction?.seat_no === seat ? "pending-highlight" : ""
                  }`}
                  onClick={() => {
                    setSelectedSeat(seat);
                    if (currentGameId) loadPlayerView(seat);
                  }}
                  type="button"
                  disabled={Boolean(busy) || submitting}
                >
                  {seat}号
                </button>
              ))}
            </div>
          </div>

          {!selectedSeat && !pendingAction && (
            <div className="empty slim">选择座位并载入视角，或等待真人操作</div>
          )}

          {/* Pending action indicator */}
          {pendingAction && (
            <div className="pending-banner">
              <CircleAlert size={16} />
              <span>
                等待 <strong>{pendingAction.seat_no}号</strong> 操作（
                {phaseLabels[pendingAction.phase] ?? pendingAction.phase}
                第{pendingAction.round}轮）
              </span>
              {selectedSeat !== pendingAction.seat_no && (
                <button
                  type="button"
                  className="tiny"
                  onClick={() => {
                    setSelectedSeat(pendingAction.seat_no);
                    if (currentGameId) loadPlayerView(pendingAction.seat_no);
                  }}
                >
                  切换到此座位
                </button>
              )}
            </div>
          )}

          {/* Player view info */}
          {playerView && selectedSeat != null && (
            <div className="view-meta">
              <div className="view-meta-row">
                <span>身份</span>
                <strong>
                  {roleLabels[playerView.own_role] ?? playerView.own_role}{" "}
                  <StatusPill tone={playerView.own_camp === "werewolf" ? "bad" : "good"}>
                    {campLabels[playerView.own_camp]}
                  </StatusPill>
                </strong>
              </div>
              {playerView.known_wolf_team.length > 0 && (
                <div className="view-meta-row">
                  <span>狼队友</span>
                  <strong>{playerView.known_wolf_team.map((s) => `${s}号`).join("、")}</strong>
                </div>
              )}
              {Object.keys(playerView.private_info).length > 0 && (
                <div className="view-meta-row">
                  <span>私有信息</span>
                  <pre className="mini-pre">
                    {JSON.stringify(playerView.private_info, null, 2)}
                  </pre>
                </div>
              )}
              <div className="view-meta-row">
                <span>可用动作</span>
                <div className="action-tags">
                  {playerView.available_actions.map((a) => (
                    <StatusPill key={a}>{a}</StatusPill>
                  ))}
                  {!playerView.available_actions.length && "无"}
                </div>
              </div>
            </div>
          )}

          {viewError && (
            <div className="notice error">
              <CircleAlert size={16} />
              {viewError}
            </div>
          )}

          {/* Action form when pending matches selected seat */}
          {pendingAction && selectedSeat === pendingAction.seat_no && (
            <div className="action-form">
              <div className="field-row">
                <label>动作类型</label>
                <div className="segmented">
                  {pendingAction.available_actions.map((a) => (
                    <button
                      key={a}
                      type="button"
                      className={
                        actionForm["selected_action_type"] === a ? "active" : ""
                      }
                      onClick={() =>
                        setActionForm((prev) => ({
                          ...prev,
                          selected_action_type: a,
                          target_seat_no: undefined,
                          speak_content: undefined,
                        }))
                      }
                    >
                      {a}
                    </button>
                  ))}
                </div>
              </div>

              {actionForm["selected_action_type"] === "speak" && (
                <div className="field-row">
                  <label>发言内容</label>
                  <textarea
                    className="textarea"
                    rows={3}
                    placeholder="输入发言..."
                    value={
                      typeof actionForm["speak_content"] === "string"
                        ? (actionForm["speak_content"] as string)
                        : ""
                    }
                    onChange={(e) =>
                      setActionForm((prev) => ({
                        ...prev,
                        speak_content: e.target.value,
                      }))
                    }
                  />
                </div>
              )}

              {(actionForm["selected_action_type"] === "vote" ||
                actionForm["selected_action_type"] === "sheriff_vote") && (
                <div className="field-row">
                  <label>投票目标</label>
                  <div className="target-grid">
                    <button
                      type="button"
                      className={
                        actionForm["target_seat_no"] === "abstain" ? "active" : ""
                      }
                      onClick={() =>
                        setActionForm((prev) => ({
                          ...prev,
                          target_seat_no: "abstain",
                        }))
                      }
                    >
                      弃票
                    </button>
                    {(playerView?.players ?? game?.players ?? [])
                      .filter(playerAlive)
                      .map((p) => (
                        <button
                          key={p.seat_no}
                          type="button"
                          className={
                            actionForm["target_seat_no"] === p.seat_no ? "active" : ""
                          }
                          onClick={() =>
                            setActionForm((prev) => ({
                              ...prev,
                              target_seat_no: p.seat_no,
                            }))
                          }
                        >
                          {p.seat_no}号
                        </button>
                      ))}
                  </div>
                </div>
              )}

              {(actionForm["selected_action_type"] === "werewolf_kill" ||
                actionForm["selected_action_type"] === "seer_check" ||
                actionForm["selected_action_type"] === "witch_poison") && (
                <div className="field-row">
                  <label>目标</label>
                  <div className="target-grid">
                    {(playerView?.players ?? game?.players ?? [])
                      .filter(
                        (p) => playerAlive(p) && p.seat_no !== selectedSeat
                      )
                      .map((p) => (
                        <button
                          key={p.seat_no}
                          type="button"
                          className={
                            actionForm["target_seat_no"] === p.seat_no ? "active" : ""
                          }
                          onClick={() =>
                            setActionForm((prev) => ({
                              ...prev,
                              target_seat_no: p.seat_no,
                            }))
                          }
                        >
                          {p.seat_no}号
                        </button>
                      ))}
                  </div>
                </div>
              )}

              {actionForm["selected_action_type"] === "witch_save" && (
                <div className="field-row">
                  <label>目标</label>
                  <div className="target-grid">
                    {(playerView?.players ?? game?.players ?? [])
                      .filter(playerAlive)
                      .map((p) => (
                        <button
                          key={p.seat_no}
                          type="button"
                          className={
                            actionForm["target_seat_no"] === p.seat_no ? "active" : ""
                          }
                          onClick={() =>
                            setActionForm((prev) => ({
                              ...prev,
                              target_seat_no: p.seat_no,
                            }))
                          }
                        >
                          {p.seat_no}号
                        </button>
                      ))}
                  </div>
                  {pendingAction.private_info?.pending_wolf_kill_target != null && (
                    <div className="hint" style={{ marginTop: 4 }}>
                      建议目标：{String(pendingAction.private_info.pending_wolf_kill_target)}号（被狼击杀）
                    </div>
                  )}
                </div>
              )}

              <button
                className="primary"
                type="button"
                disabled={submitting}
                onClick={() => handleSubmitHumanAction()}
                style={{ marginTop: 8, width: "100%" }}
              >
                {submitting ? (
                  <Loader2 className="spin" size={16} />
                ) : (
                  <Play size={16} />
                )}
                {submitting ? "提交中..." : `提交 ${pendingAction.seat_no}号动作`}
              </button>
            </div>
          )}
        </section>

        <section className="events-panel">
          <div className="section-title">
            <Eye size={18} />
            <h2>系统事件</h2>
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
      </div>
    </main>
  );
}

function PlayerApp({ gameId, seatNo }: { gameId: string; seatNo: number }) {
  const [view, setView] = useState<PlayerView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [actionForm, setActionForm] = useState<Record<string, unknown>>({});

  const params = new URLSearchParams(window.location.search);
  const tokenFromQuery = params.get("token");
  const [token, setToken] = useState<string | null>(() =>
    tokenFromQuery || getStoredSeatToken(gameId, seatNo)
  );

  useEffect(() => {
    if (tokenFromQuery) {
      const store = readSeatTokenStore();
      const nextStore = {
        ...store,
        [gameId]: {
          ...(store[gameId] ?? {}),
          [String(seatNo)]: tokenFromQuery,
        },
      };
      writeSeatTokenStore(nextStore);
      setToken(tokenFromQuery);
    }
  }, [gameId, tokenFromQuery, seatNo]);

  const pendingAction: PendingHumanAction | null = view?.pending_human_action ?? null;

  async function loadView({ silent = false }: { silent?: boolean } = {}) {
    if (!token) {
      if (!silent) setError("缺少 seat token，无法加载玩家视角");
      return;
    }
    if (!silent) {
      setError(null);
      setRefreshing(true);
    }
    try {
      const v = await getPlayerView(gameId, seatNo, token);
      setView(v);
    } catch (err) {
      if (!silent) setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      if (!silent) setRefreshing(false);
    }
  }

  async function handleSubmit() {
    if (!pendingAction) return;
    const selected = actionForm["selected_action_type"];
    if (typeof selected !== "string") { setError("请选择动作"); return; }
    const actionObj: Record<string, unknown> = { action_type: selected };
    if (selected === "speak") {
      const content = actionForm["speak_content"];
      if (typeof content !== "string" || !content.trim()) { setError("发言内容不能为空"); return; }
      actionObj["content"] = content;
    } else if (selected === "vote" || selected === "sheriff_vote") {
      const target = actionForm["target_seat_no"];
      actionObj["target_seat_no"] = target === "abstain" ? null : typeof target === "number" ? target : null;
    } else {
      const target = actionForm["target_seat_no"];
      if (typeof target !== "number") { setError("请选择目标"); return; }
      actionObj["target_seat_no"] = target;
    }
    setBusy(true);
    setError(null);
    try {
      const nextView = await submitPlayerAction(
        gameId,
        seatNo,
        { action: actionObj, reasoning_summary: "" },
        token
      );
      setView(nextView);
      setActionForm({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
      await loadView({ silent: true });
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    loadView();
    const timer = window.setInterval(() => loadView({ silent: true }), 5000);
    return () => window.clearInterval(timer);
  }, [gameId, seatNo, token]);

  const playerEvents = useMemo(
    () =>
      (view?.public_events ?? [])
        .map((event, sequence) => ({ sequence, event, created_at: null })),
    [view?.public_events]
  );
  const playerSpeechEvents = useMemo(
    () =>
      playerEvents.filter(
        (item) => speechEventTypes.has(item.event.type) || item.event.type === "round_summary"
      ),
    [playerEvents]
  );
  const latestPlayerSpeech = playerSpeechEvents.length
    ? playerSpeechEvents[playerSpeechEvents.length - 1]
    : null;
  const activeSpeechSeatNo =
    typeof latestPlayerSpeech?.event.seat_no === "number" ? latestPlayerSpeech.event.seat_no : null;
  const visibleEvents = useMemo(
    () => playerEvents.filter(shouldShowEvent).reverse(),
    [playerEvents]
  );
  const gamePhase = view?.phase ?? "setup";
  const gameRound = view?.round ?? 0;
  const playerWinnerText = isCamp(view?.winner) ? `${campLabels[view.winner]}胜利` : null;
  const playerStatusText =
    playerWinnerText ?? (gamePhase === "ended" ? "已结束" : pendingAction ? "轮到你" : "等待中");

  return (
    <main className="app-shell player-page">
      <header className="topbar">
        <div>
          <div className="eyebrow">Werewolf Agent Team · 玩家</div>
          <h1>{seatNo}号座位 · {view ? (roleLabels[view.own_role] ?? view.own_role) : "载入中..."}</h1>
        </div>
        <div className="topbar-meta">
          <StatusPill tone={token ? "good" : "bad"}>
            {token ? <Wifi size={14} /> : <WifiOff size={14} />}
            {refreshing ? "刷新中" : token ? "已授权" : "缺少 token"}
          </StatusPill>
          <span className="api-base">{gameId}</span>
        </div>
      </header>

      <section className="summary-band">
        <div className="metric"><span>对局</span><strong>{gameId}</strong></div>
        <div className="metric"><span>座位</span><strong>{seatNo}号</strong></div>
        <div className="metric"><span>阶段</span><strong>{phaseLabels[gamePhase]}</strong></div>
        <div className="metric"><span>轮次</span><strong>第 {gameRound} 轮</strong></div>
        <div className="metric"><span>状态</span><strong>{playerStatusText}</strong></div>
        <div className="metric"><span>Game ID</span><strong style={{ fontSize: 12 }}>{gameId}</strong></div>
      </section>

      {error && (
        <div className="notice error" style={{ marginBottom: 12 }}>
          <CircleAlert size={16} /> {error}
          <button type="button" className="tiny" onClick={() => loadView()} style={{ marginLeft: "auto" }}>重试</button>
        </div>
      )}

      <div className="player-workspace">
        {/* Left: player info */}
        <section className="player-info-card">
          <div className="section-title">
            <Eye size={18} />
            <h2>我的信息</h2>
          </div>
          {view ? (
            <div className="view-meta">
              <div className="view-meta-row">
                <span>身份</span>
                <strong>
                  {roleLabels[view.own_role] ?? view.own_role}
                  <StatusPill tone={view.own_camp === "werewolf" ? "bad" : "good"}>
                    {campLabels[view.own_camp]}
                  </StatusPill>
                </strong>
              </div>
              {view.known_wolf_team.length > 0 && (
                <div className="view-meta-row">
                  <span>狼队友</span>
                  <strong>{view.known_wolf_team.map((s) => `${s}号`).join("、")}</strong>
                </div>
              )}
              {Object.keys(view.private_info).length > 0 && (
                <div className="view-meta-row">
                  <span>私有信息</span>
                  <pre className="mini-pre">{JSON.stringify(view.private_info, null, 2)}</pre>
                </div>
              )}
              <div className="view-meta-row">
                <span>可用动作</span>
                <div className="action-tags">
                  {view.available_actions.map((a) => <StatusPill key={a}>{a}</StatusPill>)}
                  {!view.available_actions.length && "无"}
                </div>
              </div>
            </div>
          ) : (
            <div className="empty slim">{token ? "载入中..." : "缺少 token，无法加载视角"}</div>
          )}
        </section>

        {/* Middle: pending action form */}
        <section className="player-action-card">
          <div className="section-title">
            <Play size={18} />
            <h2>当前操作</h2>
          </div>
          {pendingAction && pendingAction.seat_no === seatNo ? (
            <div className="action-form">
              <p style={{ fontSize: 13, color: "#6b5612", marginBottom: 8 }}>
                等待你执行 {phaseLabels[pendingAction.phase]} 第{pendingAction.round}轮动作
              </p>
              <div className="field-row">
                <label>动作类型</label>
                <div className="segmented">
                  {pendingAction.available_actions.map((a) => (
                    <button key={a} type="button" className={actionForm["selected_action_type"] === a ? "active" : ""}
                      onClick={() => setActionForm((prev) => ({ ...prev, selected_action_type: a, target_seat_no: undefined, speak_content: undefined }))}>
                      {a}
                    </button>
                  ))}
                </div>
              </div>
              {actionForm["selected_action_type"] === "speak" && (
                <div className="field-row">
                  <label>发言</label>
                  <textarea className="textarea" rows={3} placeholder="输入发言..."
                    value={typeof actionForm["speak_content"] === "string" ? (actionForm["speak_content"] as string) : ""}
                    onChange={(e) => setActionForm((prev) => ({ ...prev, speak_content: e.target.value }))} />
                </div>
              )}
              {(actionForm["selected_action_type"] === "vote" || actionForm["selected_action_type"] === "sheriff_vote") && (
                <div className="field-row">
                  <label>投票</label>
                  <div className="target-grid">
                    <button type="button" className={actionForm["target_seat_no"] === "abstain" ? "active" : ""}
                      onClick={() => setActionForm((prev) => ({ ...prev, target_seat_no: "abstain" }))}>弃票</button>
                    {(view?.players ?? []).filter(playerAlive).map((p) => (
                      <button key={p.seat_no} type="button" className={actionForm["target_seat_no"] === p.seat_no ? "active" : ""}
                        onClick={() => setActionForm((prev) => ({ ...prev, target_seat_no: p.seat_no }))}>{p.seat_no}号</button>
                    ))}
                  </div>
                </div>
              )}
              {(actionForm["selected_action_type"] === "werewolf_kill" || actionForm["selected_action_type"] === "seer_check" || actionForm["selected_action_type"] === "witch_poison") && (
                <div className="field-row">
                  <label>目标</label>
                  <div className="target-grid">
                    {(view?.players ?? []).filter((p) => playerAlive(p) && p.seat_no !== seatNo).map((p) => (
                      <button key={p.seat_no} type="button" className={actionForm["target_seat_no"] === p.seat_no ? "active" : ""}
                        onClick={() => setActionForm((prev) => ({ ...prev, target_seat_no: p.seat_no }))}>{p.seat_no}号</button>
                    ))}
                  </div>
                </div>
              )}
              {actionForm["selected_action_type"] === "witch_save" && (
                <div className="field-row">
                  <label>目标</label>
                  <div className="target-grid">
                    {(view?.players ?? []).filter(playerAlive).map((p) => (
                      <button key={p.seat_no} type="button" className={actionForm["target_seat_no"] === p.seat_no ? "active" : ""}
                        onClick={() => setActionForm((prev) => ({ ...prev, target_seat_no: p.seat_no }))}>{p.seat_no}号</button>
                    ))}
                  </div>
                  {pendingAction.private_info?.pending_wolf_kill_target != null && (
                    <div className="hint" style={{ marginTop: 4 }}>建议目标：{String(pendingAction.private_info.pending_wolf_kill_target)}号</div>
                  )}
                </div>
              )}
              <button className="primary" type="button" disabled={busy} onClick={handleSubmit} style={{ marginTop: 8, width: "100%" }}>
                {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                {busy ? "提交中..." : `提交 ${seatNo}号动作`}
              </button>
            </div>
          ) : pendingAction && pendingAction.seat_no !== seatNo ? (
            <div className="empty slim">等待 {pendingAction.seat_no}号操作</div>
          ) : (
            <div className="empty slim">当前没有等待你的操作</div>
          )}
        </section>

        {/* Right: public table + speeches + events */}
        <section className="player-events-card">
          <div className="section-title">
            <Users size={18} />
            <h2>圆桌席位</h2>
          </div>
          <PlayerRoundTable
            view={view}
            activeSeatNo={activeSpeechSeatNo}
            activeSpeech={latestPlayerSpeech}
          />

          <div className="section-title compact player-section-gap">
            <MessageCircle size={16} />
            <h3>发言记录</h3>
          </div>
          <div className="speech-list player-speech-list">
            {playerSpeechEvents.map((item) => (
              <article
                className={`speech-item ${
                  item.sequence === latestPlayerSpeech?.sequence ? "active" : ""
                }`}
                key={item.sequence}
              >
                <span>#{item.sequence}</span>
                <strong>
                  {typeof item.event.seat_no === "number" ? `${item.event.seat_no}号` : "摘要"}
                </strong>
                <p>{eventBody(item.event)}</p>
              </article>
            ))}
            {!playerSpeechEvents.length && <div className="empty slim">暂无发言</div>}
          </div>

          <div className="section-title compact player-section-gap">
            <Eye size={16} />
            <h3>系统事件</h3>
          </div>
          <div className="event-list" style={{ maxHeight: 420 }}>
            {visibleEvents.map((item) => (
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
            {!visibleEvents.length && <div className="empty slim">暂无事件</div>}
          </div>
        </section>
      </div>
    </main>
  );
}

function Root() {
  const pathname = window.location.pathname;
  const match = pathname.match(/^\/play\/([^/]+)\/(\d+)/);
  if (match) {
    return <PlayerApp gameId={match[1]} seatNo={parseInt(match[2], 10)} />;
  }
  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
