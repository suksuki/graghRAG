import { useState, useEffect } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

/**
 * GET /api/knowledge/docs/{doc_id} + GET /api/graph/suggestions?doc_id=
 * 仅使用 API 既有字段，不注入 mock。
 */
export function useDocumentDetail(docId) {
    const { i18n } = useTranslation();
    const [detail, setDetail] = useState(null);
    const [suggestions, setSuggestions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!docId) {
            setDetail(null);
            setSuggestions([]);
            setError(null);
            setLoading(false);
            return;
        }

        let cancelled = false;
        setDetail(null);
        setLoading(true);
        setError(null);

        (async () => {
            try {
                const r = await axios.get(`/api/knowledge/docs/${encodeURIComponent(docId)}`, {
                    headers: { 'x-lang': i18n.language || 'zh' },
                });
                if (!cancelled) setDetail(r.data);
            } catch (e) {
                if (!cancelled) {
                    setDetail(null);
                    setError(e);
                }
            }

            try {
                const sres = await fetch(
                    `/api/graph/suggestions?doc_id=${encodeURIComponent(docId)}`,
                    { headers: { 'x-lang': i18n.language || 'zh' } }
                );
                if (sres.ok) {
                    const sj = await sres.json();
                    if (!cancelled) {
                        setSuggestions(Array.isArray(sj?.questions) ? sj.questions : []);
                    }
                } else if (!cancelled) {
                    setSuggestions([]);
                }
            } catch {
                if (!cancelled) setSuggestions([]);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [docId, i18n.language]);

    useEffect(() => {
        if (!docId) return;

        const headers = { 'x-lang': i18n.language || 'zh' };

        const softRefetch = async () => {
            try {
                const r = await axios.get(`/api/knowledge/docs/${encodeURIComponent(docId)}`, { headers });
                setDetail((prev) => r.data ?? prev);
            } catch {
                /* 保留当前 detail，避免摄取中短暂 404 清空界面 */
            }

            try {
                const sres = await fetch(
                    `/api/graph/suggestions?doc_id=${encodeURIComponent(docId)}`,
                    { headers }
                );
                if (sres.ok) {
                    const sj = await sres.json();
                    setSuggestions(Array.isArray(sj?.questions) ? sj.questions : []);
                }
            } catch {
                /* 保留原 recommendations */
            }
        };

        window.addEventListener('graphrag_refetch_docs', softRefetch);
        return () => window.removeEventListener('graphrag_refetch_docs', softRefetch);
    }, [docId, i18n.language]);

    return { detail, suggestions, loading, error };
}
