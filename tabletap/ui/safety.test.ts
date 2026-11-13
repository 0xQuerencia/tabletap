import { expect, test } from "bun:test"
import {
  CONFIRM_WINDOW_MS, MAX_LIVE_MS,
  SAFE_ARM, requestArm, confirmArm, expireArm,
} from "./safety.ts"

test("starts safe on every new terminal session", () => {
  expect(SAFE_ARM).toEqual({ mode: "safe", expiresAt: 0 })
  expect(confirmArm(SAFE_ARM, 100)).toEqual(SAFE_ARM)
})

test("V requests permission but does not arm commands", () => {
  const pending = requestArm(SAFE_ARM, 100)
  expect(pending.mode).toBe("confirm")
  expect(pending.expiresAt).toBe(100 + CONFIRM_WINDOW_MS)
  expect(requestArm(pending, 200)).toEqual(SAFE_ARM)
})

test("requires a separate confirmation key within four seconds", () => {
  const pending = requestArm(SAFE_ARM, 100)
  expect(confirmArm(pending, 100 + CONFIRM_WINDOW_MS)).toEqual(SAFE_ARM)
  const armed = confirmArm(pending, 300)
  expect(armed).toEqual({ mode: "live", expiresAt: 300 + MAX_LIVE_MS })
})

test("live authorization cannot persist longer than the timeout", () => {
  const live = confirmArm(requestArm(SAFE_ARM, 100), 200)
  expect(expireArm(live, 200 + MAX_LIVE_MS - 1)).toEqual(live)
  expect(expireArm(live, 200 + MAX_LIVE_MS)).toEqual(SAFE_ARM)
  expect(requestArm(live, 300)).toEqual(SAFE_ARM)
})

test("expired confirmation is cleared, not silently accepted", () => {
  const pending = requestArm(SAFE_ARM, 1)
  expect(expireArm(pending, 1 + CONFIRM_WINDOW_MS)).toEqual(SAFE_ARM)
  expect(confirmArm(pending, 1 + CONFIRM_WINDOW_MS + 10)).toEqual(SAFE_ARM)
})
