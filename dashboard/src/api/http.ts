// Shared fetch wrapper for the OTS API.
//
// OTS uses Flask-Security session auth: the login response carries a CSRF
// token that must be echoed in the X-XSRF-TOKEN header on any mutating
// request; the session itself lives in a cookie.

let csrfToken: string | null = null

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

export class HttpError extends Error {
  constructor(public status: number, statusText: string) {
    super(`${status} ${statusText}`)
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }
  const method = (init?.method ?? 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD' && csrfToken) {
    headers['X-XSRF-TOKEN'] = csrfToken
  }
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers,
  })
  if (!res.ok) throw new HttpError(res.status, res.statusText)
  return res.json() as Promise<T>
}
