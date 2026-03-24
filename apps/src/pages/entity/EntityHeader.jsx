import React from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Network } from 'lucide-react';

export default function EntityHeader({ displayName, onBack, weakProfile = false }) {
    const { t } = useTranslation();

    return (
        <>
            <div className="document-detail__topbar">
                <button type="button" className="document-detail__back" onClick={onBack}>
                    <ArrowLeft size={18} aria-hidden />
                    {t('entity_back_documents')}
                </button>
                <button type="button" className="document-detail__close" onClick={onBack} aria-label={t('close')}>
                    ×
                </button>
            </div>
            <h1 className="document-detail__title">
                <Network size={28} style={{ flexShrink: 0, marginTop: 2, color: '#818cf8' }} aria-hidden />
                {displayName}
            </h1>
            <div style={{ marginBottom: 16 }}>
                <span
                    style={{
                        display: 'inline-block',
                        fontSize: '11px',
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        padding: '4px 10px',
                        borderRadius: 8,
                        background: 'rgba(99,102,241,0.18)',
                        border: '1px solid rgba(129,140,248,0.35)',
                        color: '#c4b5fd',
                    }}
                >
                    {weakProfile ? t('entity_type_badge_weak') : t('entity_type_badge')}
                </span>
            </div>
        </>
    );
}
