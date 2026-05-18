export type GamePhase = "setup" | "night" | "day" | "vote" | "ended";
export type AgentMode = "scripted" | "llm";
export type Camp = "werewolf" | "good";

export interface PlayerStatus {
  alive: boolean;
  can_vote: boolean;
}

export interface PlayerState {
  seat_no: number;
  name: string;
  player_type: "ai" | "human";
  role: string;
  camp: Camp;
  status: PlayerStatus;
}

export interface PublicState {
  round: number;
  phase: GamePhase;
  alive_players: number[];
  dead_players: number[];
  public_events: GameEventPayload[];
}

export interface GameEventPayload {
  type: string;
  [key: string]: unknown;
}

export interface VisiblePlayer {
  seat_no: number;
  name: string;
  player_type: "ai" | "human";
  alive: boolean;
  can_vote: boolean;
}

export interface PlayerView {
  game_id: string;
  viewer_seat_no: number;
  round: number;
  phase: GamePhase;
  players: VisiblePlayer[];
  public_events: GameEventPayload[];
  own_role: string;
  own_camp: Camp;
  known_wolf_team: number[];
  sheriff_seat_no?: number | null;
  private_info: Record<string, unknown>;
  available_actions: string[];
  pending_human_action?: PendingHumanAction | null;
  winner?: Camp | null;
}

export interface PendingHumanAction {
  seat_no: number;
  action_type: string;
  round: number;
  phase: GamePhase;
  available_actions: string[];
  private_info: Record<string, unknown>;
}

export interface AgentDecisionRequest {
  action: Record<string, unknown>;
  reasoning_summary?: string;
}

export interface HumanSeatLink {
  seat_no: number;
  token: string;
  path: string;
}

export interface PersistedEvent {
  sequence: number;
  event: GameEventPayload;
  created_at: string | null;
}

export interface GameState {
  game_id: string;
  agent_mode?: AgentMode;
  model?: string | null;
  rule_config?: Record<string, unknown>;
  public_state: PublicState;
  players: PlayerState[];
  truth_state?: Record<string, unknown>;
  runtime_state?: Record<string, unknown>;
  sheriff_seat_no?: number | null;
  winner?: Camp | null;
  human_seat_links?: HumanSeatLink[];
}

export interface CreateGameRequest {
  player_count: 6 | 12;
  agent_mode: AgentMode;
  model?: string | null;
  human_seats?: number[] | null;
}

export type LiveMessage =
  | {
      type: "snapshot";
      game_id: string;
      game: GameState;
      events: PersistedEvent[];
    }
  | {
      type: "event";
      game_id: string;
      sequence: number;
      event: GameEventPayload;
      game?: GameState;
    }
  | {
      type: "state";
      status: string;
      game: GameState;
    }
  | {
      type: "ping";
      game_id: string;
    }
  | {
      error: string;
    };
