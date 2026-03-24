import React from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import CorpusInsightPanel from '../components/CorpusInsightPanel';
import './DocumentPage.css';

/**
 * 独立「知识洞察」页：完整展示 Corpus Insight。
 */
export default function InsightPage() {
    const { t } = useTranslation();
    const navigate = useNavigate();

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
            <CorpusInsightPanel variant="page" topKDocs={20} />
        </div>
    );
}
