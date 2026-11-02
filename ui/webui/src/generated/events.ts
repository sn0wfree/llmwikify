// AUTO-GENERATED FILE — do not edit by hand.
//
// Source of truth: src/llmwikify/apps/chat/agent/events.py (EVENT_SPECS)
// Regenerate:       python scripts/gen_webui_types.py
// Verify (CI):      python scripts/gen_webui_types.py --check


import type { ResearchRunStatus } from '../types/research';

export type ChatStreamEvent =
  | { type: 'session_created'; session_id: string }
  | { type: 'session_init'; session_id: string }
  | { type: 'user_message'; content: string }
  | { type: 'message_delta'; content: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call_start'; tool: string; args: Record<string, unknown>; call_id: string }
  | { type: 'tool_call_end'; tool: string; result: unknown; call_id: string; duration_ms: number }
  | { type: 'tool_call_error'; tool: string; error: string; call_id: string; duration_ms?: number }
  | { type: 'confirmation_required'; confirmation_id: string; tool: string; args: Record<string, unknown>; impact: Record<string, unknown>; call_id: string; duration_ms?: number }
  | { type: 'compacted'; call_id: string; tool: string; chars_saved: number }
  | { type: 'command_done'; command: string; ok: boolean; message: string; data?: unknown }
  | ({ type: 'research_run_started' } & ResearchRunStatus)
  | { type: 'done'; content: string; stop_reason?: string; error?: string; compacted_count?: number }
  | { type: 'error'; message: string; stop_reason?: string }
  | { type: 'save_warning'; reason: string }
  | { type: 'phase'; phase: string; round?: number; reason?: string; final_state?: unknown };

/** Every event type the backend can emit on the chat SSE stream. */
export const CHAT_EVENT_NAMES = [
  'session_created',
  'session_init',
  'user_message',
  'message_delta',
  'thinking',
  'tool_call_start',
  'tool_call_end',
  'tool_call_error',
  'confirmation_required',
  'compacted',
  'command_done',
  'research_run_started',
  'done',
  'error',
  'save_warning',
  'phase',
] as const;

export type ChatEventName = (typeof CHAT_EVENT_NAMES)[number];
