// Shared fetch wrapper for the OTS API.
//
// OTS uses Flask-Security session auth: the login response carries a CSRF
// token that must be echoed in the X-XSRF-TOKEN header on any mutating
// request; the session itself lives in a cookie.

let csrfToken: string | null = null

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

/** Flask-Security also mirrors the CSRF token into the XSRF-TOKEN cookie —
 * the survivor across page reloads (module state is lost). */
function currentCsrfToken(): string | null {
  const cookie = document.cookie
    .split('; ')
    .find((c) => c.startsWith('XSRF-TOKEN='))
  return cookie ? decodeURIComponent(cookie.slice('XSRF-TOKEN='.length)) : csrfToken
}

export class HttpError extends Error {
  constructor(public status: number, statusText: string) {
    super(`${status} ${statusText}`)
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    // FormData bodies set their own multipart boundary — don't override it
    ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(init?.headers as Record<string, string> | undefined),
  }
  const method = (init?.method ?? 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') {
    const token = currentCsrfToken()
    if (token) headers['X-XSRF-TOKEN'] = token
  }
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers,
  })
  if (!res.ok) throw new HttpError(res.status, res.statusText)
  return res.json() as Promise<T>
}
