import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * 轮询 POST /api/telemetry/friction-eval，供 FrictionDebugPanel 与 v3 条件渲染共用（单次订阅）。
 */
export function useFrictionEval({ enabled, sessionId, docId = '', pollMs = 5000, logCandidate = false }) {
    const [data, setData] = useState(null);
    const [err, setErr] = useState(null);
    const [loading, setLoading] = useState(false);
    const abortRef = useRef(null);

    const refresh = useCallback(async () => {
        if (!enabled || !sessionId) return;
        abortRef.current?.abort();
        const ac = new AbortController();
        abortRef.current = ac;
        setLoading(true);
        setErr(null);
        try {
            const r = await fetch('/api/telemetry/friction-eval', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    doc_id: docId || undefined,
                    log_candidate: logCandidate,
                }),
                signal: ac.signal,
            });
            if (!r.ok) {
                setErr(`HTTP ${r.status}`);
                setData(null);
                return;
            }
            const j = await r.json();
            setData(j);
        } catch (e) {
            if (e.name === 'AbortError') return;
            setErr(String(e.message || e));
            setData(null);
        } finally {
            setLoading(false);
        }
    }, [enabled, sessionId, docId, logCandidate]);

    useEffect(() => {
        if (!enabled || !sessionId) {
            setData(null);
            setErr(null);
            return undefined;
        }
        refresh();
        const id = window.setInterval(refresh, pollMs);
        return () => {
            window.clearInterval(id);
            abortRef.current?.abort();
        };
    }, [enabled, sessionId, docId, pollMs, refresh]);

    return { data, err, loading, refresh };
}
