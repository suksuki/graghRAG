import React from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Sparkles, RefreshCw, Loader2, BarChart3, Building2, Hash, Lightbulb } from 'lucide-react';
import { useCorpusInsight } from '../hooks/useCorpusInsight';
import './CorpusInsightPanel.css';

/**
 * @param {'embedded' | 'page'} variant — embedded：文档中心顶部；page：独立 Insight 页
 */
export default function CorpusInsightPanel({ variant = 'embedded', topKDocs = 20 }) {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { data, loading, error, refetch } = useCorpusInsight(topKDocs);

    const openEntity = (name) => {
        const n = (name || '').trim();
        if (!n) return;
        navigate(`/entity/${encodeURIComponent(n)}`, { state: { entityReturnTo: '/insight' } });
    };

    const isEmbedded = variant === 'embedded';
    const n = data?.docs_analyzed ?? 0;
    const hasInsights = Array.isArray(data?.key_insights) && data.key_insights.length > 0;

    return (
        <section
            className={`insight-panel ${isEmbedded ? 'insight-panel--embedded' : 'insight-panel--page'}`}
            aria-labelledby="corpus-insight-heading"
        >
            <div className={`insight-panel__head ${isEmbedded ? '' : 'insight-panel__head--page'}`}>
                {isEmbedded ? (
                    <div>
                        <div className="insight-panel__title-row">
                            <Sparkles size={22} style={{ color: '#a78bfa', flexShrink: 0 }} aria-hidden />
                            <h2 id="corpus-insight-heading" className="insight-panel__title">
                                {t('insight_panel_title')}
                            </h2>
                        </div>
                        <p className="insight-panel__subtitle">{t('insight_panel_subtitle')}</p>
                    </div>
                ) : (
                    <span id="corpus-insight-heading" className="insight-panel__sr-only">
                        {t('insight_panel_title')}
                    </span>
                )}
                <div className="insight-panel__actions">
                    <button
                        type="button"
                        className="insight-panel__refresh"
                        onClick={() => refetch()}
                        disabled={loading}
                    >
                        {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                        {t('insight_refresh')}
                    </button>
                    {isEmbedded && (
                        <Link to="/insight" className="insight-panel__link">
                            {t('insight_open_full')} →
                        </Link>
                    )}
                </div>
            </div>

            {loading && !data && (
                <div className="insight-panel__skeleton" aria-busy="true" aria-label={t('insight_loading')}>
                    <div className="insight-panel__skeleton-line insight-panel__skeleton-line--lg" />
                    <div className="insight-panel__skeleton-line" />
                    <div className="insight-panel__skeleton-line insight-panel__skeleton-line--short" />
                    <div className="insight-panel__skeleton-grid">
                        <div className="insight-panel__skeleton-card" />
                        <div className="insight-panel__skeleton-card" />
                        <div className="insight-panel__skeleton-card" />
                    </div>
                    <div className="insight-panel__skeleton-insights">
                        <div className="insight-panel__skeleton-line insight-panel__skeleton-line--sm" />
                        <div className="insight-panel__skeleton-line" />
                        <div className="insight-panel__skeleton-line" />
                    </div>
                </div>
            )}

            {error && !data && (
                <div className="insight-panel__error" role="alert">
                    {t('insight_error')}
                    <button
                        type="button"
                        className="insight-panel__refresh"
                        style={{ marginLeft: 8 }}
                        onClick={() => refetch()}
                    >
                        {t('retry')}
                    </button>
                </div>
            )}

            {data && (
                <>
                    <p
                        className={`insight-panel__trust ${n === 0 ? 'insight-panel__trust--muted' : ''}`}
                        role="status"
                    >
                        {n > 0
                            ? t('insight_based_on_docs', { count: n })
                            : t('insight_trust_zero')}
                    </p>

                    {(data.summary || '').trim() && (
                        <div className="insight-panel__summary-wrap">
                            <div className="insight-panel__summary-kicker">{t('insight_summary_kicker')}</div>
                            <div className="insight-panel__summary">{data.summary}</div>
                        </div>
                    )}

                    {((data.top_topics || []).length > 0 ||
                        (data.top_entities || []).length > 0 ||
                        (data.top_keywords || []).length > 0) && (
                        <div className="insight-panel__scan-grid" role="region" aria-label={t('insight_scan_region_label')}>
                            {(data.top_topics || []).length > 0 && (
                                <div className="insight-panel__scan-card">
                                    <h3 className="insight-panel__scan-card-title">
                                        <BarChart3 size={14} aria-hidden />
                                        {t('insight_top_topics')}
                                    </h3>
                                    <div className="insight-panel__chips">
                                        {data.top_topics.map((x, i) => (
                                            <span key={i} className="insight-panel__chip">
                                                {x}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {(data.top_entities || []).length > 0 && (
                                <div className="insight-panel__scan-card">
                                    <h3 className="insight-panel__scan-card-title">
                                        <Building2 size={14} aria-hidden />
                                        {t('insight_top_entities')}
                                    </h3>
                                    <div className="insight-panel__chips">
                                        {data.top_entities.map((x, i) => (
                                            <button
                                                key={i}
                                                type="button"
                                                className="insight-panel__chip insight-panel__chip--entity insight-panel__chip--clickable"
                                                onClick={() => openEntity(x)}
                                                title={`${x} — ${t('entity_pill_navigate_hint')}`}
                                            >
                                                {x}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {(data.top_keywords || []).length > 0 && (
                                <div className="insight-panel__scan-card">
                                    <h3 className="insight-panel__scan-card-title">
                                        <Hash size={14} aria-hidden />
                                        {t('insight_top_keywords')}
                                    </h3>
                                    <div className="insight-panel__chips">
                                        {data.top_keywords.map((x, i) => (
                                            <span key={i} className="insight-panel__chip insight-panel__chip--keyword">
                                                {x}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {hasInsights && (
                        <div className="insight-panel__section insight-panel__section--insights">
                            <h3 className="insight-panel__section-title insight-panel__section-title--insights">
                                <Lightbulb size={14} aria-hidden />
                                {t('insight_key_insights')}
                            </h3>
                            <p className="insight-panel__insights-intro">{t('insight_key_insights_intro')}</p>
                            <ol className="insight-panel__insights insight-panel__insights--numbered">
                                {data.key_insights.map((line, i) => (
                                    <li key={i}>{line}</li>
                                ))}
                            </ol>
                            {(data.closing_takeaway || '').trim() ? (
                                <div className="insight-panel__takeaway">
                                    <span className="insight-panel__takeaway-kicker">{t('insight_takeaway_kicker')}</span>
                                    <p className="insight-panel__takeaway-text">{data.closing_takeaway.trim()}</p>
                                </div>
                            ) : null}
                        </div>
                    )}
                </>
            )}
        </section>
    );
}
