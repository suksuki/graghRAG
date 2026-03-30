import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

function isStructuredEvidencePreviewEnabled() {
    if (import.meta.env.DEV) return true;
    try {
        return window.localStorage.getItem('graphrag_debug_structured_evidence') === '1';
    } catch (_) {
        return false;
    }
}

export default function StructuredEvidenceBlock({
    structuredEvidence,
    chunkByRef,
    activeRef,
    onRefClick,
    onNavigateDocument,
    currentDocId,
}) {
    const { t, i18n } = useTranslation();
    const isPreviewEnabled = useMemo(() => isStructuredEvidencePreviewEnabled(), []);
    const locale = String(i18n.language || 'zh').toLowerCase();
    const valueSeparator = locale.startsWith('en') ? ': ' : '：';
    const personJoiner = locale.startsWith('en') ? ', ' : '、';
    const rows = Array.isArray(structuredEvidence) ? structuredEvidence : [];

    if (!isPreviewEnabled || !rows.length) return null;

    return (
        <section className="structured-evidence" aria-label={t('structured_evidence_title')}>
            <div className="structured-evidence__title">{t('structured_evidence_title')}</div>
            <p className="structured-evidence__hint">{t('structured_evidence_hint')}</p>
            <ul className="structured-evidence__list">
                {rows.map((row, idx) => {
                    const refs = Array.isArray(row?.ref_indices)
                        ? row.ref_indices.filter((ref) => Number.isInteger(ref) && ref > 0)
                        : [];
                    const fileNames = Array.isArray(row?.file_names)
                        ? row.file_names.map((name) => String(name || '').trim()).filter(Boolean)
                        : [];
                    const primaryFile = fileNames[0] || '';
                    const primaryChunk = refs.length ? chunkByRef?.get?.(refs[0]) : null;
                    const canOpenDocument =
                        typeof onNavigateDocument === 'function' &&
                        primaryFile &&
                        primaryFile !== String(currentDocId || '');
                    return (
                        <li key={`${row?.role || 'role'}-${idx}`} className="structured-evidence__item">
                            <div className="structured-evidence__line">
                                <span className="structured-evidence__role">{row?.role || t('v3_source_unknown')}</span>
                                <span className="structured-evidence__sep">{valueSeparator}</span>
                                <span className="structured-evidence__persons">
                                    {Array.isArray(row?.persons) ? row.persons.join(personJoiner) : ''}
                                </span>
                            </div>
                            <div className="structured-evidence__meta">
                                {refs.length ? (
                                    <div className="structured-evidence__meta-group structured-evidence__meta-group--refs">
                                        <span className="structured-evidence__meta-label">
                                            {t('structured_evidence_refs_label')}
                                        </span>
                                        <div className="structured-evidence__refs">
                                        {refs.map((ref) => (
                                            <button
                                                key={ref}
                                                type="button"
                                                className={[
                                                    'grounded-insight__ref',
                                                    'grounded-insight__ref--inline-group',
                                                    activeRef === ref ? 'grounded-insight__ref--active' : '',
                                                ]
                                                    .filter(Boolean)
                                                    .join(' ')}
                                                onClick={() => onRefClick?.(ref)}
                                            >
                                                [{ref}]
                                            </button>
                                        ))}
                                        </div>
                                    </div>
                                ) : null}
                                {fileNames.length ? (
                                    <div className="structured-evidence__meta-group structured-evidence__meta-group--files">
                                        <span className="structured-evidence__meta-label">
                                            {t('structured_evidence_source_label')}
                                        </span>
                                        <span className="structured-evidence__files">{fileNames.join(personJoiner)}</span>
                                    </div>
                                ) : null}
                                {canOpenDocument ? (
                                    <button
                                        type="button"
                                        className="structured-evidence__open"
                                        onClick={() =>
                                            onNavigateDocument(primaryFile, {
                                                refIndex: refs[0],
                                                snippet: primaryChunk?.snippet,
                                            })
                                        }
                                    >
                                        {t('grounded_insight_open_at_evidence')}
                                    </button>
                                ) : null}
                            </div>
                        </li>
                    );
                })}
            </ul>
        </section>
    );
}
