import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import {
    ArrowLeft,
    X,
    FileText,
    Search,
    AlignLeft,
    Network,
    Quote,
    MapPin,
    Loader2,
    ListOrdered,
    Layers,
    Tag,
} from 'lucide-react';
import { useDocumentDetail } from '../hooks/useDocumentDetail';
import { useDocumentInsight } from '../hooks/useDocumentInsight';
import GroundedInsightPanel from '../components/GroundedInsightPanel';
import GroundedFollowUpChips from '../components/GroundedFollowUpChips';
import './DocumentDetail.css';

export default function DocumentDetail({
    docId,
    onBack,
    onEntityNavigate,
    onSuggestedQuestion,
}) {
    const { t } = useTranslation();
    const location = useLocation();
    const navigate = useNavigate();
    const returnTo = typeof location.state?.documentReturnTo === 'string' ? location.state.documentReturnTo : null;
    const evidenceSnippetFromNav = location.state?.evidenceAnchor?.snippet;
    const [evidenceFlashIdx, setEvidenceFlashIdx] = useState(null);
    const evidenceHandledKeyRef = useRef(null);
    const { detail, suggestions, loading, error } = useDocumentDetail(docId);
    const {
        data: groundedData,
        loading: groundedLoading,
        error: groundedError,
        run: runGroundedInsight,
        reset: resetGroundedInsight,
    } = useDocumentInsight();
    const [groundedQuery, setGroundedQuery] = useState('');
    const [entitiesExpanded, setEntitiesExpanded] = useState(false);
    const entityPreview = 8;
    const autoInsightDocRef = useRef(null);

    useEffect(() => {
        setEntitiesExpanded(false);
    }, [docId]);

    useEffect(() => {
        evidenceHandledKeyRef.current = null;
        setEvidenceFlashIdx(null);
    }, [docId]);

    useEffect(() => {
        autoInsightDocRef.current = null;
        resetGroundedInsight();
        setGroundedQuery('');
    }, [docId, resetGroundedInsight]);

    useEffect(() => {
        if (!detail || !evidenceSnippetFromNav) return;
        const key = `${docId}|${String(evidenceSnippetFromNav).slice(0, 64)}`;
        if (evidenceHandledKeyRef.current === key) return;
        evidenceHandledKeyRef.current = key;

        const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
        const needle = norm(evidenceSnippetFromNav);
        const head = needle.slice(0, Math.min(72, needle.length));
        const snippets = detail.related_snippets || [];
        let idx = -1;
        if (head.length >= 8) {
            snippets.forEach((s, i) => {
                const h = norm(s);
                if (!h) return;
                if (h.includes(head) || head.includes(h.slice(0, Math.min(48, h.length)))) {
                    idx = i;
                }
            });
        }

        setEvidenceFlashIdx(idx >= 0 ? idx : null);
        requestAnimationFrame(() => {
            if (idx >= 0) {
                document.getElementById(`document-evidence-snippet-${idx}`)?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center',
                });
            } else {
                document.getElementById('document-detail-related-knowledge')?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start',
                });
            }
        });

        const clearFlash = window.setTimeout(() => setEvidenceFlashIdx(null), 5200);

        const nextState = { ...(location.state || {}) };
        delete nextState.evidenceAnchor;
        navigate(
            { pathname: location.pathname, search: location.search, hash: location.hash || '' },
            { replace: true, state: Object.keys(nextState).length ? nextState : undefined }
        );

        return () => clearTimeout(clearFlash);
    }, [detail, docId, evidenceSnippetFromNav, navigate, location.hash, location.pathname, location.search]);

    useEffect(() => {
        if (!detail || !docId || loading) return;
        if (autoInsightDocRef.current === docId) return;
        autoInsightDocRef.current = docId;
        runGroundedInsight({
            query: t('grounded_insight_doc_default_query'),
            docId,
            topK: 8,
        });
    }, [detail, docId, loading, t, runGroundedInsight]);

    const openDocument = useCallback(
        (fn, meta) => {
            if (!fn || fn === docId) return;
            navigate(`/docs/${encodeURIComponent(fn)}`, {
                state: {
                    documentReturnTo: returnTo || undefined,
                    evidenceAnchor:
                        meta?.snippet && meta?.refIndex != null
                            ? { refIndex: meta.refIndex, snippet: meta.snippet }
                            : undefined,
                },
            });
        },
        [docId, navigate, returnTo]
    );

    const handleGroundedGenerate = () => {
        const q = groundedQuery.trim() || t('grounded_insight_doc_default_query');
        runGroundedInsight({ query: q, docId, topK: 8 });
    };

    const handleBack = () => {
        if (returnTo && returnTo.startsWith('/')) {
            navigate(returnTo);
            return;
        }
        onBack?.();
    };

    if (!docId) {
        return null;
    }

    return (
        <div className="document-detail">
            <div className="document-detail__main">
                {returnTo === '/search' && (
                    <div className="entity-page__context-banner" role="navigation">
                        <Search size={16} style={{ flexShrink: 0, color: '#a78bfa' }} aria-hidden />
                        <span className="entity-page__context-banner__text">{t('document_from_search')}</span>
                        <button type="button" className="entity-page__context-banner__btn" onClick={() => navigate('/search')}>
                            {t('document_back_to_search')}
                        </button>
                    </div>
                )}
                <div className="document-detail__topbar">
                    <button type="button" className="document-detail__back" onClick={handleBack}>
                        <ArrowLeft size={18} aria-hidden />
                        {t('back_to_list')}
                    </button>
                    <button type="button" className="document-detail__close" onClick={handleBack} aria-label={t('close')}>
                        ×
                    </button>
                </div>

                {loading && !detail && (
                    <div className="document-detail__loading">
                        <Loader2 className="spin" size={22} />
                        {t('loading')}
                    </div>
                )}

                {error && !detail && (
                    <div className="document-detail__error" role="alert">
                        {t('document_detail_load_error')}
                    </div>
                )}

                {detail && (
                    <>
                        <h1 className="document-detail__title">
                            <FileText size={28} style={{ flexShrink: 0, marginTop: 2, color: '#818cf8' }} aria-hidden />
                            <span style={{ flex: 1, minWidth: 0 }}>{detail.name || docId}</span>
                            {detail.doc_type ? (
                                <span className="document-detail__doc-type-badge" title={t('doc_type_label')}>
                                    {t(`doc_type_${detail.doc_type}`, { defaultValue: detail.doc_type })}
                                </span>
                            ) : null}
                        </h1>

                        <section className="document-detail__panel document-detail__panel--grounded-insight document-detail__panel--grounded-first">
                            <div className="document-detail__panel-title">
                                <Quote size={16} aria-hidden />
                                {t('grounded_insight_doc_section_title')}
                            </div>
                            <p className="document-detail__grounded-lead">{t('grounded_insight_doc_section_lead_auto')}</p>
                            {groundedLoading && !groundedData ? (
                                <div className="document-detail__grounded-loading" aria-busy="true" aria-label={t('grounded_insight_loading')}>
                                    <Loader2 className="spin" size={22} aria-hidden />
                                    <span>{t('grounded_insight_loading')}</span>
                                </div>
                            ) : null}
                            <textarea
                                className="document-detail__grounded-input"
                                rows={2}
                                value={groundedQuery}
                                onChange={(e) => setGroundedQuery(e.target.value)}
                                placeholder={t('grounded_insight_doc_query_placeholder')}
                                aria-label={t('grounded_insight_doc_query_placeholder')}
                            />
                            <button
                                type="button"
                                className="document-detail__grounded-submit"
                                disabled={groundedLoading}
                                onClick={handleGroundedGenerate}
                            >
                                {groundedLoading ? <Loader2 className="spin" size={18} aria-hidden /> : null}
                                {t('grounded_insight_regenerate')}
                            </button>
                            {groundedError ? (
                                <div className="document-detail__error document-detail__grounded-error" role="alert">
                                    {t('grounded_insight_error')}
                                </div>
                            ) : null}
                            {groundedData ? (
                                <div className="document-detail__grounded-panel-wrap">
                                    <GroundedInsightPanel
                                        summary={groundedData.summary || ''}
                                        supportingChunks={groundedData.supporting_chunks || []}
                                        insufficientEvidence={Boolean(groundedData.insufficient_evidence)}
                                        apiDebug={groundedData.debug || null}
                                        onNavigateDocument={openDocument}
                                        currentDocId={docId}
                                        belowSummary={
                                            <GroundedFollowUpChips
                                                mode="document"
                                                disabled={groundedLoading}
                                                onPick={(q) => {
                                                    setGroundedQuery(q);
                                                    runGroundedInsight({ query: q, docId, topK: 8 });
                                                }}
                                            />
                                        }
                                    />
                                </div>
                            ) : null}
                        </section>

                        {(detail.insight || '').trim() ? (
                            <section className="document-detail__panel document-detail__panel--insight">
                                <div className="document-detail__panel-title document-detail__panel-title--accent">
                                    {t('knowledge_key_insight_title')}
                                </div>
                                <div style={{ fontSize: '14px', lineHeight: 1.55, color: '#e2e8f0' }}>{detail.insight}</div>
                            </section>
                        ) : null}

                        {Array.isArray(detail.key_points) && detail.key_points.length > 0 && (
                            <section className="document-detail__panel document-detail__panel--di-primary">
                                <div className="document-detail__panel-title">
                                    <ListOrdered size={16} aria-hidden />
                                    {t('doc_key_points_title')}
                                </div>
                                <ul className="document-detail__key-points">
                                    {detail.key_points.map((kp, i) => (
                                        <li key={i}>{kp}</li>
                                    ))}
                                </ul>
                            </section>
                        )}

                        <section className="document-detail__panel document-detail__panel--doc-summary">
                            <div className="document-detail__panel-title">
                                <AlignLeft size={16} aria-hidden />
                                {t('doc_summary_title')}
                            </div>
                            <div style={{ fontSize: '14px', lineHeight: 1.6, color: '#cbd5e1' }}>
                                {detail.summary || t('doc_summary_empty')}
                            </div>
                        </section>

                        {Array.isArray(detail.topics) && detail.topics.length > 0 && (
                            <section className="document-detail__panel document-detail__panel--di-secondary">
                                <div className="document-detail__panel-title">
                                    <Layers size={16} aria-hidden />
                                    {t('doc_topics_title')}
                                </div>
                                <div className="document-detail__topic-chips">
                                    {detail.topics.map((tp, i) => (
                                        <span key={i} className="document-detail__topic-chip">
                                            {tp}
                                        </span>
                                    ))}
                                </div>
                            </section>
                        )}

                        {(detail.keywords || []).length > 0 && (
                            <section className="document-detail__panel document-detail__panel--di-secondary">
                                <div className="document-detail__panel-title">
                                    <Tag size={16} aria-hidden />
                                    {t('doc_keywords_title')}
                                </div>
                                <div className="document-detail__topic-chips">
                                    {(detail.keywords || []).map((kw, i) => (
                                        <span key={i} className="document-detail__keyword-chip">
                                            {kw}
                                        </span>
                                    ))}
                                </div>
                            </section>
                        )}

                        {Array.isArray(detail.related_snippets) && detail.related_snippets.length > 0 && (
                            <section className="document-detail__panel" id="document-detail-related-knowledge">
                                <div className="document-detail__panel-title">
                                    <Quote size={16} aria-hidden />
                                    {t('related_knowledge_title')}
                                </div>
                                {detail.related_snippets.map((s, i) => (
                                    <div
                                        key={i}
                                        id={`document-evidence-snippet-${i}`}
                                        className={[
                                            'document-detail__excerpt',
                                            evidenceFlashIdx === i ? 'document-detail__excerpt--evidence-focus' : '',
                                        ]
                                            .filter(Boolean)
                                            .join(' ')}
                                    >
                                        {s}
                                    </div>
                                ))}
                            </section>
                        )}
                    </>
                )}
            </div>

            <aside className="document-detail__side">
                {detail && (
                    <>
                        <section className="document-detail__panel">
                            <div className="document-detail__panel-title">
                                <Network size={16} aria-hidden />
                                {t('entities_title')}
                            </div>
                            <div>
                                {(() => {
                                    const ents = detail.entities || [];
                                    const hidden = Math.max(0, ents.length - entityPreview);
                                    const shown = entitiesExpanded ? ents : ents.slice(0, entityPreview);
                                    return (
                                        <>
                                            {shown.map((en, i) => (
                                                <button
                                                    key={`${en}-${i}`}
                                                    type="button"
                                                    className="document-detail__entity-pill"
                                                    title={t('entity_pill_navigate_hint')}
                                                    onClick={() => onEntityNavigate?.(en)}
                                                >
                                                    {en}
                                                </button>
                                            ))}
                                            {hidden > 0 && !entitiesExpanded ? (
                                                <button
                                                    type="button"
                                                    className="document-detail__entity-more"
                                                    onClick={() => setEntitiesExpanded(true)}
                                                >
                                                    {t('entity_show_more', { count: hidden })}
                                                </button>
                                            ) : null}
                                            {ents.length === 0 ? (
                                                <span style={{ fontSize: '13px', opacity: 0.75 }}>{t('entities_empty')}</span>
                                            ) : null}
                                        </>
                                    );
                                })()}
                            </div>
                        </section>

                        {Array.isArray(detail.relations) && detail.relations.length > 0 && (
                            <section className="document-detail__panel">
                                <div className="document-detail__panel-title">
                                    <Network size={16} aria-hidden />
                                    {t('relations_title')}
                                </div>
                                {detail.relations.slice(0, 32).map((rel, i) => (
                                    <div key={i} className="document-detail__rel-row">
                                        <button
                                            type="button"
                                            className="document-detail__rel-link"
                                            onClick={() => onEntityNavigate?.(rel.source)}
                                        >
                                            {rel.source}
                                        </button>
                                        <span style={{ opacity: 0.65 }}>{rel.relation}</span>
                                        <button
                                            type="button"
                                            className="document-detail__rel-link"
                                            onClick={() => onEntityNavigate?.(rel.target)}
                                        >
                                            {rel.target}
                                        </button>
                                    </div>
                                ))}
                            </section>
                        )}

                        {suggestions.length > 0 && (
                            <section className="document-detail__panel">
                                <div className="document-detail__panel-title">
                                    <MapPin size={16} aria-hidden />
                                    {t('document_discovery_questions')}
                                </div>
                                {suggestions.slice(0, 8).map((q, qi) => (
                                    <button
                                        key={qi}
                                        type="button"
                                        className="document-detail__suggest-btn"
                                        onClick={() => onSuggestedQuestion?.(q)}
                                    >
                                        {q}
                                    </button>
                                ))}
                            </section>
                        )}
                    </>
                )}
            </aside>
        </div>
    );
}
