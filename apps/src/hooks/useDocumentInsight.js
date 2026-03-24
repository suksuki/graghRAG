import { useState, useCallback } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

/**
 * POST /api/v1/insights/document — 片段锚定的有据摘要（含 ref_index / [n]）。
 */
export function useDocumentInsight() {
    const { i18n } = useTranslation();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const reset = useCallback(() => {
        setData(null);
        setError(null);
    }, []);

    const run = useCallback(
        async ({ query, docId, topK = 8, includeGraphRelations = true }) => {
            const q = String(query || '').trim();
            if (!q) return;
            setLoading(true);
            setError(null);
            try {
                const body = {
                    query: q,
                    top_k: topK,
                    include_graph_relations: includeGraphRelations,
                };
                if (docId) {
                    body.doc_id = docId;
                }
                const res = await axios.post('/api/v1/insights/document', body, {
                    headers: {
                        'Content-Type': 'application/json',
                        'x-lang': i18n.language || 'zh',
                    },
                });
                setData(res.data);
            } catch (e) {
                setError(e);
                setData(null);
            } finally {
                setLoading(false);
            }
        },
        [i18n.language]
    );

    return { data, loading, error, run, reset };
}
