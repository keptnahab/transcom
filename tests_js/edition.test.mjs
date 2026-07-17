import assert from 'node:assert/strict'
import test from 'node:test'
import { editionLimitMessage, editionState } from '../renderer/src/edition.mjs'

test('missing edition is safely Starter', () => {
  assert.deepEqual(editionState({}), {
    edition: 'starter', label: 'Starter', exportAllowed: false, sessionLimitSeconds: 60,
  })
})

test('Starter cannot be unlocked by export_allowed alone', () => {
  assert.equal(editionState({ edition: 'starter', export_allowed: true }).exportAllowed, false)
})

test('Full has export and no time limit', () => {
  assert.deepEqual(editionState({ edition: 'full', export_allowed: true }), {
    edition: 'full', label: 'Full', exportAllowed: true, sessionLimitSeconds: null,
  })
})

test('limit event has a clear German fallback', () => {
  assert.match(editionLimitMessage({ limit_seconds: 60 }), /60 Sekunden/)
})
