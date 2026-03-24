import React from 'react';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';

export default function EntityDocuments({ documents, onNavigateDocument }) {
    const { t } = useTranslation();
    const list = documents || [];

    return (
        <section className="document-detail__panel">
            <div className="document-detail__panel-title">
                <FileText size={16} aria-hidden />
                {t('related_documents_title')}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {list.map((fn, fi) => (
                    <button
                        key={fi}
                        type="button"
                        className="document-detail__rel-link"
                        style={{ textAlign: 'left', textDecoration: 'underline', width: '100%' }}
                        onClick={() => onNavigateDocument?.(fn)}
                    >
                        {fn}
                    </button>
                ))}
                {list.length === 0 && <span style={{ fontSize: '13px', opacity: 0.75 }}>—</span>}
            </div>
        </section>
    );
}
