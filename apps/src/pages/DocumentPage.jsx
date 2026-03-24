import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { FileText } from 'lucide-react';
import { useDocuments } from '../hooks/useDocuments';
import CorpusInsightPanel from '../components/CorpusInsightPanel';
import IngestionMonitor from '../components/IngestionMonitor';
import './DocumentPage.css';

function resolveDocKey(doc) {
    return doc?.id ?? doc?.doc_id ?? doc?.name ?? '';
}

export default function DocumentPage() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { documents, loading, error, refetch } = useDocuments();
    const [filter, setFilter] = useState('');
    const [sort, setSort] = useState('default');

    const filtered = useMemo(() => {
        let list = documents || [];
        const q = filter.trim().toLowerCase();
        if (q) {
            list = list.filter((d) => {
                const name = (d.name || '').toLowerCase();
                const sum = (d.summary || '').toLowerCase();
                const tags = (d.tags || []).join(' ').toLowerCase();
                const ents = (d.entities || []).join(' ').toLowerCase();
                const kws = (d.keywords || []).join(' ').toLowerCase();
                const tps = (d.topics || []).join(' ').toLowerCase();
                return (
                    name.includes(q) ||
                    sum.includes(q) ||
                    tags.includes(q) ||
                    ents.includes(q) ||
                    kws.includes(q) ||
                    tps.includes(q)
                );
            });
        }
        const copy = [...list];
        if (sort === 'name') {
            copy.sort((a, b) => (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' }));
        } else if (sort === 'recent') {
            copy.sort((a, b) => (Number(b.mtime) || 0) - (Number(a.mtime) || 0));
        }
        return copy;
    }, [documents, filter, sort]);

    const openDoc = (id) => {
        if (!id) return;
        navigate(`/docs/${encodeURIComponent(id)}`);
    };

    return (
        <div className="document-page">
            <header className="document-page__head">
                <div>
                    <h1 className="document-page__title">{t('documents_kb_title')}</h1>
                    <p className="document-page__subtitle">{t('documents_kb_subtitle')}</p>
                </div>
                <div className="document-page__toolbar">
                    <input
                        type="search"
                        className="document-page__filter"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        placeholder={t('documents_filter_placeholder')}
                        aria-label={t('documents_filter_placeholder')}
                    />
                    <select
                        className="document-page__sort"
                        value={sort}
                        onChange={(e) => setSort(e.target.value)}
                        aria-label={t('documents_sort_label')}
                    >
                        <option value="default">{t('documents_sort_default')}</option>
                        <option value="recent">{t('documents_sort_recent')}</option>
                        <option value="name">{t('documents_sort_name')}</option>
                    </select>
                </div>
            </header>

            <IngestionMonitor />

            <CorpusInsightPanel variant="embedded" topKDocs={20} />

            {error && (
                <div className="document-page__error" role="alert">
                    {t('documents_list_error')}
                    <button
                        type="button"
                        onClick={() => refetch()}
                        style={{ marginLeft: 12, textDecoration: 'underline', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}
                    >
                        {t('retry')}
                    </button>
                </div>
            )}

            {loading && (
                <div className="document-page__grid" aria-busy="true">
                    {[1, 2, 3, 4, 5].map((k) => (
                        <div key={k} className="document-page__skeleton" />
                    ))}
                </div>
            )}

            {!loading && !error && filtered.length === 0 && (
                <div className="document-page__empty">{t('document_center_empty')}</div>
            )}

            {!loading && filtered.length > 0 && (
                <div className="document-page__grid">
                    {filtered.map((doc) => {
                        const key = resolveDocKey(doc);
                        return (
                            <button
                                key={key}
                                type="button"
                                className="document-page__card"
                                onClick={() => openDoc(key)}
                            >
                                <div className="document-page__card-head">
                                    <div className="document-page__card-title">
                                        <FileText size={22} style={{ flexShrink: 0, marginTop: 2, color: '#818cf8' }} aria-hidden />
                                        <span className="document-page__card-title-text">{doc.name}</span>
                                        {doc.doc_type ? (
                                            <span className="document-page__doc-type-badge" title={t('doc_type_label')}>
                                                {t(`doc_type_${doc.doc_type}`, { defaultValue: doc.doc_type })}
                                            </span>
                                        ) : null}
                                    </div>
                                    {doc.uploaded_at ? (
                                        <time
                                            className="document-page__card-date"
                                            dateTime={doc.uploaded_at}
                                            title={t('documents_card_updated_tooltip')}
                                        >
                                            {doc.uploaded_at}
                                        </time>
                                    ) : null}
                                </div>
                                <div className="document-page__card-summary">{doc.summary || t('doc_summary_empty')}</div>
                                {(doc.keywords || []).length > 0 && (
                                    <div className="document-page__card-keywords" aria-label={t('doc_keywords_label')}>
                                        {(doc.keywords || []).slice(0, 8).map((kw, ki) => (
                                            <span key={`kw-${ki}`} className="document-page__keyword">
                                                {kw}
                                            </span>
                                        ))}
                                    </div>
                                )}
                                <div className="document-page__card-tags">
                                    {(doc.tags || []).slice(0, 8).map((tag, ti) => (
                                        <span key={ti} className="document-page__tag">
                                            {tag}
                                        </span>
                                    ))}
                                </div>
                                <span className="document-page__card-hint">{t('documents_card_open_hint')}</span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
