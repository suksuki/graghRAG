import React, { forwardRef } from 'react';
import { useTranslation } from 'react-i18next';
import { MapPin, Loader2 } from 'lucide-react';

const EntitySuggestions = forwardRef(function EntitySuggestions(
    { suggestions, suggestionsLoading, onSuggestedQuestion },
    ref
) {
    const { t } = useTranslation();
    const list = suggestions || [];
    const showEmpty = !suggestionsLoading && list.length === 0;

    return (
        <section ref={ref} className="document-detail__panel">
            <div className="document-detail__panel-title">
                <MapPin size={16} aria-hidden />
                {t('suggested_questions_title')}
            </div>
            {suggestionsLoading && list.length === 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#94a3b8', fontSize: 13 }}>
                    <Loader2 className="spin" size={18} />
                    {t('suggestions_loading')}
                </div>
            )}
            {list.slice(0, 8).map((q, qi) => (
                <button
                    key={qi}
                    type="button"
                    className="document-detail__suggest-btn"
                    onClick={() => onSuggestedQuestion?.(q)}
                >
                    {q}
                </button>
            ))}
            {showEmpty && (
                <span style={{ fontSize: '13px', opacity: 0.75 }}>{t('no_suggested_questions')}</span>
            )}
        </section>
    );
});

export default EntitySuggestions;
