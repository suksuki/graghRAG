import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Search, FileText, Loader2 } from 'lucide-react';
import { useSearch } from '../hooks/useSearch';
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

    const onSubmit = (e) => {
        e.preventDefault();
        search();
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
