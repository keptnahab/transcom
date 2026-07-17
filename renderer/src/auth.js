const API_BASE = window.electronAPI?.getWebApiBase?.()
  || (location.port === '5747' ? '' : location.origin)

const TOKEN_KEY = 'transcom_auth_token'
const USER_KEY = 'transcom_auth_user'

export class AuthHttpError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'AuthHttpError'
    this.status = status
  }
}

export function isAuthFailure(err) {
  return err?.status === 401 || err?.status === 403
}

export function token() {
  return localStorage.getItem(TOKEN_KEY)
}

export function currentUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export async function login(email, password) {
  const res = await fetch(`${API_BASE}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error((await safeJson(res)).error || 'Login failed')
  const data = await res.json()
  if (data.token) localStorage.setItem(TOKEN_KEY, data.token)
  localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  return data.user
}

export async function me() {
  const res = await authFetch('/api/me')
  const data = await safeJson(res)
  if (!res.ok) throw new AuthHttpError(data.error || 'Unauthorized', res.status)
  if (data.token) localStorage.setItem(TOKEN_KEY, data.token)
  localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  return data.user
}

export async function listUsers() {
  const res = await authFetch('/api/users')
  const data = await safeJson(res)
  if (!res.ok) throw new AuthHttpError(data.error || 'Could not load users', res.status)
  return data.users || []
}

export async function createUser(email, isAdmin = false) {
  const res = await authFetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, is_admin: isAdmin }),
  })
  const data = await safeJson(res)
  if (!res.ok) throw new AuthHttpError(data.error || 'Could not create user', res.status)
  return data
}

export async function setUserPassword(email, password = '') {
  const res = await authFetch(`/api/users/${encodeURIComponent(email)}/password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  const data = await safeJson(res)
  if (!res.ok) throw new AuthHttpError(data.error || 'Could not update password', res.status)
  return data
}

export async function deleteUser(email) {
  const res = await authFetch(`/api/users/${encodeURIComponent(email)}`, { method: 'DELETE' })
  const data = await safeJson(res)
  if (!res.ok) throw new AuthHttpError(data.error || 'Could not delete user', res.status)
}

async function authFetch(path, options = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token() || ''}`,
    },
  })
}

async function safeJson(res) {
  try {
    return await res.json()
  } catch {
    return {}
  }
}
