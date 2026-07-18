import assert from 'node:assert/strict'
import test from 'node:test'
import { editionLimitMessage, editionState } from '../renderer/src/edition.mjs'

test('missing edition is safely presented as Beta', () => {
  assert.deepEqual(editionState({}), {
    edition: 'starter', label: 'Beta', exportAllowed: false, sessionLimitSeconds: 60,
  })
})

test('Beta cannot be unlocked by export_allowed alone', () => {
  assert.equal(editionState({ edition: 'starter', export_allowed: true }).exportAllowed, false)
})

test('Full has export and no time limit', () => {
  assert.deepEqual(editionState({ edition: 'full', export_allowed: true }), {
    edition: 'full', label: 'Full', exportAllowed: true, sessionLimitSeconds: null,
  })
})

test('limit event has a clear German fallback', () => {
  assert.match(editionLimitMessage({ limit_seconds: 60 }), /Beta-Limit.*60 Sekunden/)
  assert.doesNotMatch(editionLimitMessage({ message: 'Starter-Limit erreicht', limit_seconds: 60 }), /Starter/)
})
