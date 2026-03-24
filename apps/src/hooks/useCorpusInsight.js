import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

/**
 * POST /api/insights/corpus — 跨文档知识库洞察（聚合 di_*）。
 */
export function useCorpusInsight(topKDocs = 20) {
    const { i18n } = useTranslation();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchInsight = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.post(
                '/api/insights/corpus',
                { top_k_docs: topKDocs },
                { headers: { 'x-lang': i18n.language || 'zh' } }
            );
            setData(res.data);
        } catch (e) {
            setError(e);
            setData(null);
        } finally {
            setLoading(false);
        }
    }, [topKDocs, i18n.language]);

    useEffect(() => {
        fetchInsight();
    }, [fetchInsight]);

    useEffect(() => {
        const onRefetch = () => fetchInsight();
        window.addEventListener('graphrag_refetch_docs', onRefetch);
        return () => window.removeEventListener('graphrag_refetch_docs', onRefetch);
    }, [fetchInsight]);

    return { data, loading, error, refetch: fetchInsight };
}
