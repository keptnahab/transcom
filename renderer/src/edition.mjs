export function editionState(status = {}) {
  const edition = status?.edition === 'full' ? 'full' : 'starter'
  return {
    edition,
    label: edition === 'full' ? 'Full' : 'Starter',
    exportAllowed: edition === 'full' && status?.export_allowed !== false,
    sessionLimitSeconds: edition === 'full' ? null : Number(status?.session_limit_seconds || 60),
  }
}

export function editionLimitMessage(payload = {}) {
  const limit = Number(payload?.limit_seconds || 60)
  return payload?.message || `Starter-Limit erreicht: Die Transkription wurde nach ${limit} Sekunden beendet.`
}
