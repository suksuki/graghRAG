import React, { useMemo, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Search, FileText, Loader2 } from 'lucide-react';
import { useSearch } from '../hooks/useSearch';
import { useDocumentInsight } from '../hooks/useDocumentInsight';
import GroundedInsightPanel from '../components/GroundedInsightPanel';
import GroundedFollowUpChips from '../components/GroundedFollowUpChips';
import './SearchPage.css';

/**
 * 将 query 拆成词条，在 text 中高亮（不修改 API 字段，仅展示层）。
 */
function highlightTerms(text, rawQuery) {
    const q = (rawQuery || '').trim();
    if (!q || !text) return text;
    const terms = [...new Set(q.split(/\s+/).filter((w) => w.length >= 1))];
    if (!terms.length) return text;

    const escaped = terms
        .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
        .filter(Boolean);
    if (!escaped.length) return text;

    try {
        const re = new RegExp(`(${escaped.join('|')})`, 'gi');
        const parts = String(text).split(re);
        return parts.map((part, i) => {
            if (terms.some((t) => part.toLowerCase() === t.toLowerCase())) {
                return (
                    <mark key={i} className="search-page__highlight">
                        {part}
                    </mark>
                );
            }
            return <React.Fragment key={i}>{part}</React.Fragment>;
        });
    } catch {
        return text;
    }
}

export default function SearchPage() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { query, setQuery, results, loading, error, search } = useSearch();
    const {
        data: insightData,
        loading: insightLoading,
        error: insightError,
        run: runInsight,
        reset: resetInsight,
    } = useDocumentInsight();

    /** 最近一次「搜索提交」的检索词：用于胶囊模板 {{q}}，避免点击胶囊后把整段预设写进输入框导致嵌套。 */
    const [searchAnchorQuery, setSearchAnchorQuery] = useState('');
    /** 最近一次发给 Insight API 的 query：刷新摘要时与当前摘要一致。 */
    const [insightRunQuery, setInsightRunQuery] = useState('');

    useEffect(() => {
        if (!query.trim()) {
            resetInsight();
            setSearchAnchorQuery('');
            setInsightRunQuery('');
        }
    }, [query, resetInsight]);

    const onSubmit = (e) => {
        e.preventDefault();
        const q = query.trim();
        resetInsight();
        search();
        if (q) {
            setSearchAnchorQuery(q);
            setInsightRunQuery(q);
            runInsight({ query: q, topK: 8 });
        }
    };

    const openDocument = (docId) => {
        if (!docId) return;
        navigate(`/docs/${encodeURIComponent(docId)}`, {
            state: { documentReturnTo: '/search' },
        });
    };

    const formatCardMeta = (row) => {
        const kwMax = 14;
        const truncKw = (s) => {
            const str = String(s);
            if (str.length <= kwMax) return str;
            return `${str.slice(0, kwMax - 1)}…`;
        };
        const parts = [];
        if (row.doc_type) {
            parts.push(t(`doc_type_${row.doc_type}`, { defaultValue: row.doc_type }));
        }
        const kws = Array.isArray(row.keywords) ? row.keywords.filter(Boolean) : [];
        if (kws.length) {
            parts.push(kws.map(truncKw).join(' · '));
        }
        return parts.join(' · ');
    };

    const showEmpty = useMemo(
        () => !loading && query.trim() && results.length === 0 && !error,
        [loading, query, results.length, error]
    );

    return (
        <div className="search-page">
            <p className="search-page__kicker">{t('search_page_kicker')}</p>

            <form className="search-page__form" onSubmit={onSubmit}>
                <div className="search-page__input-wrap">
                    <Search size={22} aria-hidden />
                    <input
                        className="search-page__input"
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder={t('search_placeholder')}
                        autoComplete="off"
                        aria-label={t('search_placeholder')}
                    />
                </div>
                <button className="search-page__submit" type="submit" disabled={loading || !query.trim()}>
                    {loading ? <Loader2 className="spin" size={20} /> : t('search_submit')}
                </button>
            </form>

            {query.trim() && (loading || insightLoading || insightData || insightError) ? (
                <section className="search-page__grounded-section" aria-labelledby="search-grounded-heading">
                    <div className="search-page__grounded-toolbar">
                        <h2 id="search-grounded-heading" className="search-page__grounded-title">
                            {t('grounded_insight_section_title')}
                        </h2>
                        {insightData || insightError ? (
                            <button
                                type="button"
                                className="search-page__grounded-btn search-page__grounded-btn--ghost"
                                disabled={insightLoading}
                                onClick={() =>
                                    insightRunQuery.trim() &&
                                    runInsight({ query: insightRunQuery.trim(), topK: 8 })
                                }
                            >
                                {insightLoading ? <Loader2 className="spin" size={18} aria-hidden /> : null}
                                {t('grounded_insight_refresh')}
                            </button>
                        ) : null}
                    </div>
                    <p className="search-page__grounded-hint">{t('grounded_insight_search_hint_auto')}</p>
                    {insightError ? (
                        <div className="search-page__error search-page__grounded-error" role="alert">
                            {t('grounded_insight_error')}
                        </div>
                    ) : null}
                    {insightLoading && !insightData ? (
                        <div className="search-page__grounded-loading" aria-busy="true" aria-label={t('grounded_insight_loading')}>
                            <Loader2 className="spin" size={22} aria-hidden />
                            <span>{t('grounded_insight_loading')}</span>
                        </div>
                    ) : null}
                    {insightData ? (
                        <GroundedInsightPanel
                            summary={insightData.summary || ''}
                            supportingChunks={insightData.supporting_chunks || []}
                            insufficientEvidence={Boolean(insightData.insufficient_evidence)}
                            apiDebug={insightData.debug || null}
                            onNavigateDocument={(fn, meta) =>
                                navigate(`/docs/${encodeURIComponent(fn)}`, {
                                    state: {
                                        documentReturnTo: '/search',
                                        evidenceAnchor:
                                            meta?.snippet && meta?.refIndex != null
                                                ? { refIndex: meta.refIndex, snippet: meta.snippet }
                                                : undefined,
                                    },
                                })
                            }
                            belowSummary={
                                <GroundedFollowUpChips
                                    mode="search"
                                    searchQuery={searchAnchorQuery}
                                    disabled={insightLoading}
                                    onPick={(picked) => {
                                        setInsightRunQuery(picked);
                                        runInsight({ query: picked, topK: 8 });
                                    }}
                                />
                            }
                        />
                    ) : null}
                </section>
            ) : null}

            {(query.trim() && (results.length > 0 || loading || error || showEmpty)) && (
                <>
                    <div className="search-page__results-head">
                        <span className="search-page__results-title">{t('search_results_heading')}</span>
                        <span className="search-page__sort">{t('search_sort_relevance')}</span>
                    </div>

                    {error && (
                        <div className="search-page__error" role="alert">
                            {t('search_error_generic')}
                        </div>
                    )}

                    {loading && (
                        <div className="search-page__skeleton-list" aria-busy="true" aria-label={t('searching')}>
                            {[0, 1, 2].map((i) => (
                                <div key={i} className="search-page__skeleton-card">
                                    <div className="search-page__skeleton-line search-page__skeleton-line--title" />
                                    <div className="search-page__skeleton-line search-page__skeleton-line--meta" />
                                    <div className="search-page__skeleton-line" />
                                    <div className="search-page__skeleton-line" />
                                    <div className="search-page__skeleton-line search-page__skeleton-line--short" />
                                </div>
                            ))}
                        </div>
                    )}

                    {!loading && !error && (
                        <div className="search-page__list">
                            {results.map((row, idx) => {
                                const metaLine = formatCardMeta(row);
                                return (
                                    <button
                                        key={`${row.doc}-${idx}`}
                                        type="button"
                                        className="search-page__card"
                                        onClick={() => openDocument(row.doc)}
                                    >
                                        <div className="search-page__card-title" style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                                            <FileText size={22} style={{ flexShrink: 0, marginTop: 2, color: '#818cf8' }} aria-hidden />
                                            <span>{highlightTerms(row.doc, query)}</span>
                                        </div>
                                        {metaLine ? <div className="search-page__card-meta">{metaLine}</div> : null}
                                        <div className="search-page__card-snippet">{highlightTerms(row.snippet || '', query)}</div>
                                    </button>
                                );
                            })}
                        </div>
                    )}

                    {showEmpty && (
                        <div className="search-page__empty search-page__empty--rich" role="status">
                            <p className="search-page__empty-title">{t('search_empty_title')}</p>
                            <p className="search-page__empty-lead">{t('search_empty_try_label')}</p>
                            <ul className="search-page__empty-tips">
                                <li>{t('search_empty_tip_1')}</li>
                                <li>{t('search_empty_tip_2')}</li>
                                <li>{t('search_empty_tip_3')}</li>
                            </ul>
                            <button
                                type="button"
                                className="search-page__empty-cta"
                                onClick={() => navigate('/documents')}
                            >
                                {t('search_go_document_center')}
                            </button>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
