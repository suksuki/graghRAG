import React from 'react';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';

export default function EntityOverview({ overviewText }) {
    const { t } = useTranslation();

    return (
        <section className="document-detail__panel">
            <div className="document-detail__panel-title">
                <FileText size={16} aria-hidden />
                {t('entity_overview_title')}
            </div>
            <div style={{ fontSize: '14px', lineHeight: 1.6, color: '#cbd5e1' }}>{overviewText}</div>
        </section>
    );
}
