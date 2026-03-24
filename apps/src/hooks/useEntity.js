import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

/** 跨路由内存缓存：同一实体 + 语言不重复打 suggestions API（进程内有效）。 */
const suggestionsCache = new Map();

function suggestionsCacheKey(entityName, lang) {
    return `${String(entityName)}\0${lang || 'zh'}`;
}

/**
 * GET /api/entity/{name} — 首屏加载。
 * GET /api/graph/suggestions?entity= — 仅通过 triggerSuggestions() 按需加载；命中缓存则同步回填、无请求。
 */
export function useEntity(entityName) {
    const { i18n } = useTranslation();
    const [profile, setProfile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const [suggestions, setSuggestions] = useState([]);
    const [suggestionsLoading, setSuggestionsLoading] = useState(false);
    const suggestionsFetchedRef = useRef(false);
    /** 实体/语言切换时递增，丢弃过期的 suggestions 请求回写（避免闪 loading / 串数据） */
    const suggestionsRequestGenRef = useRef(0);

    useEffect(() => {
        if (!entityName) {
            setProfile(null);
            setSuggestions([]);
            setError(null);
            setLoading(false);
            setSuggestionsLoading(false);
            suggestionsFetchedRef.current = false;
            return;
        }

        suggestionsRequestGenRef.current += 1;
        suggestionsFetchedRef.current = false;
        setSuggestions([]);
        setSuggestionsLoading(false);
        let cancelled = false;
        setLoading(true);
        setError(null);

        (async () => {
            try {
                const r = await axios.get(`/api/entity/${encodeURIComponent(entityName)}`, {
                    headers: { 'x-lang': i18n.language || 'zh' },
                });
                if (!cancelled) setProfile(r.data);
            } catch (e) {
                if (!cancelled) {
                    setProfile(null);
                    setError(e);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [entityName, i18n.language]);

    const triggerSuggestions = useCallback(async () => {
        if (!entityName || suggestionsFetchedRef.current) return;

        const lang = i18n.language || 'zh';
        const ckey = suggestionsCacheKey(entityName, lang);
        if (suggestionsCache.has(ckey)) {
            suggestionsFetchedRef.current = true;
            setSuggestionsLoading(false);
            setSuggestions(suggestionsCache.get(ckey));
            return;
        }

        const gen = suggestionsRequestGenRef.current;
        suggestionsFetchedRef.current = true;
        setSuggestionsLoading(true);
        try {
            const sres = await fetch(
                `/api/graph/suggestions?entity=${encodeURIComponent(entityName)}`,
                { headers: { 'x-lang': lang } }
            );
            if (gen !== suggestionsRequestGenRef.current) return;

            if (sres.ok) {
                const sj = await sres.json();
                const questions = Array.isArray(sj?.questions) ? sj.questions : [];
                suggestionsCache.set(ckey, questions);
                setSuggestions(questions);
            } else {
                suggestionsFetchedRef.current = false;
                setSuggestions([]);
            }
        } catch {
            if (gen !== suggestionsRequestGenRef.current) return;
            suggestionsFetchedRef.current = false;
            setSuggestions([]);
        } finally {
            if (gen === suggestionsRequestGenRef.current) {
                setSuggestionsLoading(false);
            }
        }
    }, [entityName, i18n.language]);

    return {
        profile,
        loading,
        error,
        suggestions,
        suggestionsLoading,
        triggerSuggestions,
    };
}
