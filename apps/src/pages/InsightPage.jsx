import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Loader2 } from 'lucide-react';
import CorpusInsightPanel from '../components/CorpusInsightPanel';
import GroundedInsightPanel from '../components/GroundedInsightPanel';
import { useDocumentInsight } from '../hooks/useDocumentInsight';
import './DocumentPage.css';
import './InsightPage.css';

/**
 * 独立「知识洞察」页：有据摘要（向量片段锚定）+ 跨文档 di_* 聚合（Corpus）。
 */
export default function InsightPage() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [groundedQuery, setGroundedQuery] = useState('');
    const {
        data: groundedData,
        loading: groundedLoading,
        error: groundedError,
        run: runGrounded,
        reset: resetGrounded,
    } = useDocumentInsight();

    return (
        <div className="document-page" style={{ maxWidth: 960 }}>
            <header className="document-page__head">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <button
                        type="button"
                        className="document-detail__back"
                        onClick={() => navigate('/documents')}
                        style={{
                            alignSelf: 'flex-start',
                            marginBottom: 0,
                            background: 'rgba(15,23,42,0.6)',
                            border: '1px solid rgba(51,65,85,0.5)',
                            borderRadius: 10,
                            padding: '8px 14px',
                            color: '#e2e8f0',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 8,
                        }}
                    >
                        <ArrowLeft size={18} aria-hidden />
                        {t('nav_document_center')}
                    </button>
                    <div>
                        <h1 className="document-page__title">{t('insight_page_title')}</h1>
                        <p className="document-page__subtitle">{t('insight_page_subtitle')}</p>
                    </div>
                </div>
            </header>

            <section className="insight-page__grounded" aria-labelledby="insight-grounded-title">
                <div className="insight-page__grounded-toolbar">
                    <h2 id="insight-grounded-title" className="insight-page__grounded-title">
                        {t('insight_page_grounded_title')}
                    </h2>
                    <button
                        type="button"
                        className="insight-page__grounded-btn"
                        disabled={groundedLoading}
                        onClick={() =>
                            runGrounded({
                                query: groundedQuery.trim() || t('insight_page_grounded_default_q'),
                                topK: 8,
                            })
                        }
                    >
                        {groundedLoading ? <Loader2 className="spin" size={18} aria-hidden /> : null}
                        {t('insight_page_grounded_btn')}
                    </button>
                </div>
                <p className="insight-page__grounded-hint">{t('insight_page_grounded_hint')}</p>
                <input
                    type="text"
                    className="insight-page__grounded-input"
                    value={groundedQuery}
                    onChange={(e) => {
                        setGroundedQuery(e.target.value);
                        if (!e.target.value.trim()) {
                            resetGrounded();
                        }
                    }}
                    placeholder={t('insight_page_grounded_placeholder')}
                    aria-label={t('insight_page_grounded_placeholder')}
                />
                {groundedError ? (
                    <div className="insight-page__grounded-error" role="alert">
                        {t('grounded_insight_error')}
                    </div>
                ) : null}
                {groundedData ? (
                    <GroundedInsightPanel
                        summary={groundedData.summary || ''}
                        supportingChunks={groundedData.supporting_chunks || []}
                        insufficientEvidence={Boolean(groundedData.insufficient_evidence)}
                        apiDebug={groundedData.debug || null}
                        onNavigateDocument={(fn, meta) =>
                            navigate(`/docs/${encodeURIComponent(fn)}`, {
                                state: {
                                    documentReturnTo: '/insight',
                                    evidenceAnchor:
                                        meta?.snippet && meta?.refIndex != null
                                            ? { refIndex: meta.refIndex, snippet: meta.snippet }
                                            : undefined,
                                },
                            })
                        }
                    />
                ) : null}
            </section>

            <p className="insight-page__corpus-bridge" role="note">
                {t('insight_page_corpus_bridge')}
            </p>
            <div className="insight-page__divider" />

            <CorpusInsightPanel variant="page" topKDocs={20} />
        </div>
    );
}
