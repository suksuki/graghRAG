import React, { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import { Loader2, Sparkles } from 'lucide-react';
import { useEntity } from '../hooks/useEntity';
import { buildEntityOverviewText } from '../utils/entityOverviewText';
import EntityHeader from './entity/EntityHeader';
import EntityOverview from './entity/EntityOverview';
import EntityDocuments from './entity/EntityDocuments';
import EntityRelations from './entity/EntityRelations';
import EntitySuggestions from './entity/EntitySuggestions';
import './DocumentDetail.css';

/**
 * 实体页：左栏身份与说明，右栏关联文档 / 产品行业 / 推荐问题。
 * 数据：GET /api/knowledge/entity/{name}；推荐问题仅在侧栏「推荐问题」进入视口时加载（IntersectionObserver + hook 内缓存）。
 */
export default function EntityPage({
    entityName,
    onBack,
    onNavigateEntity,
    onNavigateDocument,
    onSuggestedQuestion,
}) {
    const { t } = useTranslation();
    const location = useLocation();
    const navigate = useNavigate();
    const suggestionsSectionRef = useRef(null);
    const returnTo = typeof location.state?.entityReturnTo === 'string' ? location.state.entityReturnTo : null;

    const handleBack = () => {
        if (returnTo && returnTo.startsWith('/')) {
            navigate(returnTo);
            return;
        }
        onBack?.();
    };
    const {
        profile,
        suggestions,
        suggestionsLoading,
        triggerSuggestions,
        loading,
        error,
    } = useEntity(entityName);

    if (!entityName) {
        return null;
    }

    const displayName = profile?.entity || entityName;
    const overviewText = profile != null ? buildEntityOverviewText(profile, t) : '';
    const isWeak = Boolean(profile?.weak_profile);

    // 仅当用户看到推荐区域时再请求（单一触发源，避免与定时器竞态）
    useEffect(() => {
        if (!entityName || !profile || isWeak) return;
        const el = suggestionsSectionRef.current;
        if (!el) return;
        const obs = new IntersectionObserver(
            (entries) => {
                const entry = entries[0];
                if (!entry?.isIntersecting) return;
                triggerSuggestions();
                obs.unobserve(entry.target);
            },
            { root: null, rootMargin: '0px', threshold: 0.05 }
        );
        obs.observe(el);
        return () => obs.disconnect();
    }, [entityName, profile, isWeak, triggerSuggestions]);

    return (
        <div className="document-detail entity-page">
            <div className="document-detail__main">
                {returnTo === '/insight' && (
                    <div className="entity-page__context-banner" role="navigation">
                        <Sparkles size={16} style={{ flexShrink: 0, color: '#a78bfa' }} aria-hidden />
                        <span className="entity-page__context-banner__text">{t('entity_from_insight')}</span>
                        <button
                            type="button"
                            className="entity-page__context-banner__btn"
                            onClick={() => navigate('/insight')}
                        >
                            {t('entity_back_to_insight')}
                        </button>
                    </div>
                )}
                <EntityHeader displayName={displayName} onBack={handleBack} weakProfile={isWeak} />

                {loading && !profile && (
                    <div className="document-detail__loading">
                        <Loader2 className="spin" size={22} />
                        {t('loading')}
                    </div>
                )}

                {error && !profile && (
                    <div className="document-detail__error" role="alert">
                        {t('entity_load_error')}
                    </div>
                )}

                {profile && <EntityOverview overviewText={overviewText} />}
            </div>

            <aside className="document-detail__side">
                {profile && (
                    <>
                        <EntityDocuments documents={profile.documents} onNavigateDocument={onNavigateDocument} />
                        <EntityRelations
                            products={profile.products}
                            domains={profile.domains}
                            onNavigateEntity={onNavigateEntity}
                        />
                        {!isWeak && (
                            <EntitySuggestions
                                ref={suggestionsSectionRef}
                                suggestions={suggestions}
                                suggestionsLoading={suggestionsLoading}
                                onSuggestedQuestion={onSuggestedQuestion}
                            />
                        )}
                    </>
                )}
            </aside>
        </div>
    );
}
