import React, { useMemo, useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, MoreVertical, Upload, Loader2 } from 'lucide-react';
import { useDocuments } from '../hooks/useDocuments';
import CorpusInsightPanel from '../components/CorpusInsightPanel';
import IngestionMonitor from '../components/IngestionMonitor';
import { formatRelativeDocTime, docUpdatedMs } from '../utils/formatDocTime';
import { formatFileSize } from '../utils/formatFileSize';
import './DocumentPage.css';

function resolveDocKey(doc) {
    return doc?.id ?? doc?.doc_id ?? doc?.name ?? '';
}

function buildCardHoverTitle(doc, t, lang) {
    const lines = [];
    const name = doc?.name || '';
    if (name) lines.push(name);
    const sum = (doc?.summary || '').trim();
    if (sum) lines.push(sum.length > 240 ? `${sum.slice(0, 240)}…` : sum);
    const sz = formatFileSize(doc?.size, t);
    if (sz) lines.push(`${t('documents_card_hover_size')} ${sz}`);
    if (doc?.uploaded_at) lines.push(`${t('documents_card_hover_disk')} ${doc.uploaded_at}`);
    const um = docUpdatedMs(doc);
    if (um != null) {
        const rel = formatRelativeDocTime(um, lang);
        if (rel) lines.push(`${t('documents_card_hover_relative')} ${rel}`);
    }
    const tags = [...new Set([...(doc.tags || []), ...(doc.keywords || [])])].filter(Boolean).slice(0, 16);
    if (tags.length) lines.push(`${t('documents_card_hover_tags')} ${tags.join(', ')}`);
    if (!sum) lines.push(t('documents_card_hover_open_for_insight'));
    return lines.join('\n');
}

export default function DocumentPage({
    selectedDocId = null,
    onSelectDoc,
    onDeleteDocument,
    upload = null,
}) {
    const { t, i18n } = useTranslation();
    const { documents, loading, error, refetch } = useDocuments();
    const [filter, setFilter] = useState('');
    const [sort, setSort] = useState('default');
    const [openMenuKey, setOpenMenuKey] = useState(null);
    const cardShellRefs = useRef(new Map());

    useEffect(() => {
        if (openMenuKey == null) return undefined;
        const onDocClick = (e) => {
            if (e.target.closest('.document-page__card-toolbar')) return;
            setOpenMenuKey(null);
        };
        document.addEventListener('click', onDocClick);
        return () => document.removeEventListener('click', onDocClick);
    }, [openMenuKey]);

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

    useEffect(() => {
        if (!selectedDocId || loading) return undefined;
        const id = requestAnimationFrame(() => {
            const el = cardShellRefs.current.get(selectedDocId);
            el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        });
        return () => cancelAnimationFrame(id);
    }, [selectedDocId, loading, filtered.length]);

    const handleSelect = (key) => {
        if (!key || typeof onSelectDoc !== 'function') return;
        onSelectDoc(key);
    };

    return (
        <div className="document-page">
            <header className="document-page__head">
                <div className="document-page__head-intro">
                    <h1 className="document-page__title">{t('documents_kb_title')}</h1>
                    <p className="document-page__subtitle">{t('documents_kb_subtitle')}</p>
                </div>
                <div className="document-page__toolbar document-page__toolbar--action-bar">
                    <div className="document-page__toolbar-filters">
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
                    {upload && typeof upload.onFileChange === 'function' ? (
                        <label className="document-page__upload-primary">
                            {upload.isUploading ? (
                                <>
                                    <Loader2 className="spin" size={18} aria-hidden />
                                    <span>{upload.uploadProgress ?? 0}%</span>
                                </>
                            ) : (
                                <>
                                    <Upload size={18} aria-hidden />
                                    <span>{t('upload')}</span>
                                </>
                            )}
                            <input
                                type="file"
                                multiple
                                hidden
                                disabled={upload.isUploading}
                                onChange={(e) => {
                                    upload.onFileChange(e);
                                    e.target.value = '';
                                }}
                            />
                        </label>
                    ) : null}
                </div>
            </header>

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
                        const updatedMs = docUpdatedMs(doc);
                        const relTime = updatedMs != null ? formatRelativeDocTime(updatedMs, i18n.language) : '';
                        const hasSnippet = Boolean((doc.summary || '').trim());
                        return (
                            <div
                                key={key}
                                className="document-page__card-shell"
                                ref={(el) => {
                                    if (el) cardShellRefs.current.set(key, el);
                                    else cardShellRefs.current.delete(key);
                                }}
                            >
                                {typeof onDeleteDocument === 'function' && (
                                    <div className="document-page__card-toolbar">
                                        <button
                                            type="button"
                                            className="document-page__card-more"
                                            aria-label={t('documents_card_menu_aria')}
                                            aria-expanded={openMenuKey === key}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setOpenMenuKey((k) => (k === key ? null : key));
                                            }}
                                        >
                                            <MoreVertical size={16} aria-hidden />
                                        </button>
                                        {openMenuKey === key && (
                                            <div className="document-page__card-dropdown" role="menu">
                                                <button
                                                    type="button"
                                                    role="menuitem"
                                                    className="document-page__card-dropdown-item document-page__card-dropdown-item--danger"
                                                    onClick={() => {
                                                        setOpenMenuKey(null);
                                                        onDeleteDocument(doc);
                                                    }}
                                                >
                                                    {t('documents_card_delete')}
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                )}
                                <button
                                    type="button"
                                    className={`document-page__card document-page__card--dense ${selectedDocId === key ? 'document-page__card--active' : ''}`}
                                    onClick={() => handleSelect(key)}
                                    title={buildCardHoverTitle(doc, t, i18n.language)}
                                >
                                    <div className="document-page__card-head-row">
                                        <FileText className="document-page__card-icon" size={17} aria-hidden />
                                        <span className="document-page__card-title-text" title={doc.name}>
                                            {doc.name}
                                        </span>
                                    </div>
                                    <div className="document-page__card-meta">
                                        <span
                                            className={`document-page__card-dot document-page__card-dot--${hasSnippet ? 'ok' : 'muted'}`}
                                            title={
                                                hasSnippet
                                                    ? t('documents_card_status_indexed')
                                                    : t('documents_card_hover_open_for_insight')
                                            }
                                            aria-hidden
                                        />
                                        <span className="document-page__card-meta-text">
                                            {hasSnippet ? t('documents_card_status_indexed') : t('documents_card_status_basic')}
                                        </span>
                                        {relTime ? (
                                            <>
                                                <span className="document-page__card-meta-sep" aria-hidden>
                                                    ·
                                                </span>
                                                <time className="document-page__card-meta-time" dateTime={doc.uploaded_at || undefined}>
                                                    {relTime}
                                                </time>
                                            </>
                                        ) : null}
                                        {doc.doc_type ? (
                                            <>
                                                <span className="document-page__card-meta-sep" aria-hidden>
                                                    ·
                                                </span>
                                                <span className="document-page__card-type-inline">
                                                    {t(`doc_type_${doc.doc_type}`, { defaultValue: doc.doc_type })}
                                                </span>
                                            </>
                                        ) : null}
                                    </div>
                                </button>
                            </div>
                        );
                    })}
                </div>
            )}

            <details className="document-page__fold-system">
                <summary className="document-page__fold-system-summary">{t('document_page_fold_system_summary')}</summary>
                <div className="document-page__fold-system-body">
                    <IngestionMonitor />
                </div>
            </details>

            <details className="document-page__fold-corpus">
                <summary className="document-page__fold-corpus-summary">{t('document_page_fold_corpus_summary')}</summary>
                <div className="document-page__fold-corpus-body">
                    <CorpusInsightPanel variant="embedded" topKDocs={20} />
                </div>
            </details>
        </div>
    );
}
