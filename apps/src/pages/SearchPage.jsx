import React, { useMemo, useEffect, useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Search, FileText, Loader2, Paperclip, X } from 'lucide-react';
import { useSearch } from '../hooks/useSearch';
import { useDocumentInsight } from '../hooks/useDocumentInsight';
import GroundedInsightPanel from '../components/GroundedInsightPanel';
import GroundedFollowUpChips from '../components/GroundedFollowUpChips';
import './SearchPage.css';

const UPLOAD_ACCEPT = '.pdf,.docx,.doc,.pptx,.xlsx,.txt,.md,.html,.jpg,.jpeg,.png,.xdmp';

async function pollIngestUntilDone(jobId) {
    const max = 90;
    for (let i = 0; i < max; i += 1) {
        const { data } = await axios.get('/api/ingest/status', { params: { job_id: jobId } });
        if (data.status === 'done') return;
        if (data.status === 'failed') {
            const err = data.error;
            const msg =
                (typeof err === 'object' && err && (err.message || err.detail)) ||
                (typeof err === 'string' ? err : null) ||
                'ingest failed';
            throw new Error(String(msg));
        }
        await new Promise((r) => setTimeout(r, 2000));
    }
    throw new Error('timeout');
}

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
    /** 有据摘要限定在单文档（file_name，与向量 metadata 一致）；来自上传，非「聊天会话」。 */
    const [insightDocId, setInsightDocId] = useState(null);
    const [uploadPhase, setUploadPhase] = useState('idle');
    const [uploadError, setUploadError] = useState(null);
    const fileInputRef = useRef(null);

    useEffect(() => {
        if (!query.trim()) {
            resetInsight();
            setSearchAnchorQuery('');
            setInsightRunQuery('');
        }
    }, [query, resetInsight]);

    const clearInsightDoc = useCallback(() => {
        setInsightDocId(null);
        setUploadError(null);
        setUploadPhase('idle');
        resetInsight();
    }, [resetInsight]);

    const onPickUpload = useCallback(() => {
        setUploadError(null);
        fileInputRef.current?.click();
    }, []);

    const onUploadFile = useCallback(
        async (e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (!file) return;
            setUploadError(null);
            setUploadPhase('uploading');
            try {
                const fd = new FormData();
                fd.append('files', file, file.name);
                const { data } = await axios.post('/api/upload', fd, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                });
                const fname =
                    typeof data.filename === 'string'
                        ? data.filename
                        : Array.isArray(data.filename)
                          ? data.filename[0]
                          : data.files?.[0];
                if (!fname) {
                    throw new Error('no filename in response');
                }
                resetInsight();
                if (data.status === 'completed') {
                    setInsightDocId(fname);
                    setUploadPhase('idle');
                    return;
                }
                const jobId = data.jobs?.[0]?.job_id;
                if (data.status === 'queued' && jobId) {
                    setUploadPhase('ingesting');
                    await pollIngestUntilDone(jobId);
                    setInsightDocId(fname);
                    setUploadPhase('idle');
                    return;
                }
                setInsightDocId(fname);
                setUploadPhase('idle');
            } catch (err) {
                const payload = err.response?.data;
                const detail = payload?.detail;
                const detailStr = Array.isArray(detail)
                    ? detail.map((d) => d?.msg || d).join('; ')
                    : detail;
                const msg =
                    payload?.message ||
                    payload?.error?.message ||
                    detailStr ||
                    err.message ||
                    'upload failed';
                setUploadError(String(msg));
                setUploadPhase('idle');
            }
        },
        [resetInsight]
    );

    const onSubmit = (e) => {
        e.preventDefault();
        const q = query.trim();
        resetInsight();
        search();
        if (q) {
            setSearchAnchorQuery(q);
            setInsightRunQuery(q);
            runInsight({ query: q, topK: 8, docId: insightDocId || undefined });
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
                <input
                    ref={fileInputRef}
                    type="file"
                    className="search-page__file-input"
                    accept={UPLOAD_ACCEPT}
                    aria-hidden
                    tabIndex={-1}
                    onChange={onUploadFile}
                />
                <button
                    type="button"
                    className="search-page__attach"
                    onClick={onPickUpload}
                    disabled={uploadPhase === 'uploading' || uploadPhase === 'ingesting'}
                    aria-label={t('search_upload_aria')}
                    title={t('search_upload_aria')}
                >
                    {uploadPhase === 'uploading' || uploadPhase === 'ingesting' ? (
                        <Loader2 className="spin" size={20} aria-hidden />
                    ) : (
                        <Paperclip size={20} aria-hidden />
                    )}
                </button>
                <div className="search-page__input-wrap">
                    <Search size={22} aria-hidden />
                    <input
                        className="search-page__input"
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder={
                            insightDocId
                                ? t('search_placeholder_scoped', { name: insightDocId })
                                : t('search_placeholder')
                        }
                        autoComplete="off"
                        aria-label={
                            insightDocId
                                ? t('search_placeholder_scoped', { name: insightDocId })
                                : t('search_placeholder')
                        }
                    />
                </div>
                <button className="search-page__submit" type="submit" disabled={loading || !query.trim()}>
                    {loading ? <Loader2 className="spin" size={20} /> : t('search_submit')}
                </button>
            </form>

            {uploadError ? (
                <div className="search-page__upload-error" role="alert">
                    {uploadError}
                </div>
            ) : null}

            {uploadPhase === 'ingesting' ? (
                <p className="search-page__scope-hint">{t('search_upload_processing')}</p>
            ) : null}

            {insightDocId && uploadPhase === 'idle' ? (
                <div className="search-page__scope-bar">
                    <span className="search-page__scope-bar-icon" aria-hidden>
                        📄
                    </span>
                    <span className="search-page__scope-bar-text">
                        {t('search_context_selected', { name: insightDocId })}
                    </span>
                    <button
                        type="button"
                        className="search-page__scope-clear"
                        onClick={clearInsightDoc}
                        aria-label={t('search_context_clear')}
                    >
                        <X size={16} aria-hidden />
                        {t('search_context_clear')}
                    </button>
                </div>
            ) : null}
            <p className="search-page__single-turn-hint">{t('search_single_turn_hint')}</p>

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
                                    runInsight({
                                        query: insightRunQuery.trim(),
                                        topK: 8,
                                        docId: insightDocId || undefined,
                                    })
                                }
                            >
                                {insightLoading ? <Loader2 className="spin" size={18} aria-hidden /> : null}
                                {t('grounded_insight_refresh')}
                            </button>
                        ) : null}
                    </div>
                    <p className="search-page__grounded-hint">
                        {insightDocId
                            ? t('grounded_insight_search_hint_scoped', { name: insightDocId })
                            : t('grounded_insight_search_hint_auto')}
                    </p>
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
                            structuredEvidence={insightData.structured_evidence || []}
                            insufficientEvidence={Boolean(insightData.insufficient_evidence)}
                            decision={insightData.decision || null}
                            apiDebug={insightData.debug || null}
                            telemetryDocId={insightDocId || '__search__'}
                            telemetryInsightId={insightRunQuery.trim() || undefined}
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
                                        runInsight({ query: picked, topK: 8, docId: insightDocId || undefined });
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
