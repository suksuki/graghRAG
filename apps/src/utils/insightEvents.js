/**
 * Insight 认知摩擦埋点：sendBeacon → POST /api/log（Vite 代理到后端 /log）
 */

const SESSION_KEY = 'graphrag_insight_session';

export function getInsightSessionId() {
    try {
        let s = sessionStorage.getItem(SESSION_KEY);
        if (!s) {
            s = `s_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
            sessionStorage.setItem(SESSION_KEY, s);
        }
        return s;
    } catch {
        return `s_${Date.now()}`;
    }
}

/**
 * @param {object} partial — 需含 event；可选 ts, doc_id, insight_id, payload
 */
export function logInsightEvent(partial) {
    if (!partial || typeof partial.event !== 'string') return;
    const event = {
        ts: typeof partial.ts === 'number' ? partial.ts : Date.now(),
        session_id: getInsightSessionId(),
        doc_id: partial.doc_id ?? '',
        insight_id: partial.insight_id ?? undefined,
        event: partial.event,
        payload: partial.payload && typeof partial.payload === 'object' ? partial.payload : undefined,
    };
    const body = JSON.stringify(event);
    const url = '/api/log';
    try {
        if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
            const blob = new Blob([body], { type: 'application/json' });
            if (navigator.sendBeacon(url, blob)) return;
        }
    } catch {
        /* ignore */
    }
    fetch(url, {
        method: 'POST',
        body,
        headers: { 'Content-Type': 'application/json' },
        keepalive: true,
    }).catch(() => {});
}
