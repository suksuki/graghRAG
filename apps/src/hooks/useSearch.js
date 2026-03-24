import { useState, useCallback } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

/**
 * 调用 GET /api/search?q=（仅使用 API 返回的 query + results，不注入 mock）。
 */
export function useSearch() {
    const { i18n } = useTranslation();
    const [query, setQuery] = useState('');
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const search = useCallback(
        async (overrideQuery) => {
            const q = String(overrideQuery ?? query).trim();
            if (!q) {
                setResults([]);
                setError(null);
                return;
            }
            setLoading(true);
            setError(null);
            try {
                const res = await axios.get('/api/search', {
                    params: { q },
                    headers: { 'x-lang': i18n.language || 'zh' },
                });
                setResults(Array.isArray(res.data?.results) ? res.data.results : []);
            } catch (e) {
                setError(e);
                setResults([]);
            } finally {
                setLoading(false);
            }
        },
        [query, i18n.language]
    );

    const clearResults = useCallback(() => {
        setResults([]);
        setError(null);
    }, []);

    return {
        query,
        setQuery,
        results,
        loading,
        error,
        search,
        clearResults,
    };
}
