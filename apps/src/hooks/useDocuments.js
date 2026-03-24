import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

/**
 * GET /api/docs → { documents: [{ id, name, summary, entities, tags }, ...] }
 */
export function useDocuments() {
    const { i18n } = useTranslation();
    const [documents, setDocuments] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const refetch = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get('/api/docs', {
                headers: { 'x-lang': i18n.language || 'zh' },
            });
            setDocuments(Array.isArray(res.data?.documents) ? res.data.documents : []);
        } catch (e) {
            setError(e);
            setDocuments([]);
        } finally {
            setLoading(false);
        }
    }, [i18n.language]);

    useEffect(() => {
        refetch();
    }, [refetch]);

    useEffect(() => {
        const onHubRefetch = () => refetch();
        window.addEventListener('graphrag_refetch_docs', onHubRefetch);
        return () => window.removeEventListener('graphrag_refetch_docs', onHubRefetch);
    }, [refetch]);

    return { documents, loading, error, refetch };
}
