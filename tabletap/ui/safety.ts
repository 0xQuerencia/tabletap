/** Explicit, expiring action authorization for the interactive TableTap TUI.
 *
 * Request with V, confirm with Y. V again cancels a pending request and
 * disarms a live session. A different key prevents key-repeat from arming.
 * This state is intentionally not persisted across application restarts.
 */
export const CONFIRM_WINDOW_MS = 4_000
export const MAX_LIVE_MS = 10 * 60_000

export type ArmState = {
  mode: "safe" | "confirm" | "live"
  expiresAt: number
}

export const SAFE_ARM: ArmState = { mode: "safe", expiresAt: 0 }

export function requestArm(current: ArmState, now: number): ArmState {
  if (current.mode !== "safe") return SAFE_ARM
  return { mode: "confirm", expiresAt: now + CONFIRM_WINDOW_MS }
}

export function confirmArm(current: ArmState, now: number): ArmState {
  if (current.mode !== "confirm" || now >= current.expiresAt) return SAFE_ARM
  return { mode: "live", expiresAt: now + MAX_LIVE_MS }
}

export function expireArm(current: ArmState, now: number): ArmState {
  return current.mode !== "safe" && now >= current.expiresAt ? SAFE_ARM : current
}
