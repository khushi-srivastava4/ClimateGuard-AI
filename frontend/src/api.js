const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
const DEFAULT_TIMEOUT_MS = 12000;

export async function apiRequest(path, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...fetchOptions } = options;
  const controller = new AbortController();
  const forwardAbort = () => controller.abort(signal.reason);
  if (signal?.aborted) {
    controller.abort(signal.reason);
  } else {
    signal?.addEventListener('abort', forwardAbort, { once: true });
  }
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  let response;
  let handledResponseError = false;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        ...(fetchOptions.body ? { 'Content-Type': 'application/json' } : {}),
        ...fetchOptions.headers,
      },
    });
    if (response.status === 204) return null;

    let data;
    try {
      const body = await response.text();
      data = body ? JSON.parse(body) : null;
    } catch {
      handledResponseError = true;
      throw new Error(`The backend returned an invalid response (HTTP ${response.status}).`);
    }

    if (!response.ok) {
      handledResponseError = true;
      const detail = typeof data?.detail === 'string'
        ? data.detail
        : Array.isArray(data?.detail)
          ? data.detail
            .map((issue) => {
              if (typeof issue === 'string') return issue;
              if (!issue || typeof issue !== 'object') return '';
              const location = Array.isArray(issue.loc) ? `${issue.loc.join('.')}: ` : '';
              return `${location}${issue.msg || ''}`;
            })
            .filter(Boolean)
            .join('; ')
          : null;
      throw new Error(detail || `The request failed (HTTP ${response.status}).`);
    }
    return data;
  } catch (requestError) {
    if (signal?.aborted) throw requestError;
    if (controller.signal.aborted) {
      const timeoutError = new Error(`The request timed out after ${timeoutMs / 1000} seconds.`);
      timeoutError.name = 'TimeoutError';
      throw timeoutError;
    }
    if (handledResponseError) throw requestError;
    if (response) {
      throw new Error(`The backend response could not be read (HTTP ${response.status}).`);
    }
    throw new Error(
      `Could not reach ${API_BASE_URL}. Check the backend URL, CORS configuration, and network connection.`,
    );
  } finally {
    window.clearTimeout(timeoutId);
    signal?.removeEventListener('abort', forwardAbort);
  }
}
