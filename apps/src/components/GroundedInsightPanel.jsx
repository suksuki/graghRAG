import React, { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Quote } from 'lucide-react';
import { parseSummaryRefs } from '../utils/parseSummaryRefs';
import { parseStructuredGroundedSummary } from '../utils/parseStructuredGroundedSummary';
import './GroundedInsightPanel.css';

/** 单段文本内 [n] 引用按钮（复用于整段摘要与结构化列表项） */
function GroundedRefParts({ parts, keyPrefix, chunkByRef, activeRef, t, setTooltip, onRefClick }) {
    return parts.map((p, i) => {
        if (p.type === 'text') {
            return <span key={`${keyPrefix}-t-${i}`}>{p.value}</span>;
        }
        const ch = chunkByRef.get(p.ref);
        const missing = !ch;
        return (
            <button
                key={`${keyPrefix}-r-${i}-${p.ref}`}
                type="button"
                className={[
                    'grounded-insight__ref',
                    activeRef === p.ref ? 'grounded-insight__ref--active' : '',
                    missing ? 'grounded-insight__ref--missing' : '',
                ]
                    .filter(Boolean)
                    .join(' ')}
                aria-label={t('grounded_insight_ref_aria', { n: p.ref })}
                aria-expanded={activeRef === p.ref}
                onClick={() => onRefClick(p.ref)}
                onMouseEnter={(e) => {
                    if (!ch) return;
                    setTooltip({
                        ref: p.ref,
                        x: e.clientX + 12,
                        y: e.clientY + 16,
                        chunk: ch,
                    });
                }}
                onMouseMove={(e) => {
                    setTooltip((prev) =>
                        prev && prev.ref === p.ref ? { ...prev, x: e.clientX + 12, y: e.clientY + 16 } : prev
                    );
                }}
                onMouseLeave={() => setTooltip((prev) => (prev?.ref === p.ref ? null : prev))}
            >
                [{p.ref}]
            </button>
        );
    });
}

/**
 * 渲染有据摘要：summary 中 [n] 可 hover（tooltip）、click（高亮来源 + 右侧预览）、来源行可点击跳转文档。
 *
 * @param {object} props
 * @param {string} props.summary
 * @param {Array<object>} props.supportingChunks — API supporting_chunks（含 ref_index）
 * @param {boolean} [props.insufficientEvidence]
 * @param {(fileName: string, meta?: { refIndex: number, snippet?: string }) => void} [props.onNavigateDocument] — 打开文档；meta 用于原文侧滚动对齐片段
 * @param {string} [props.currentDocId] — 当前正在查看的文件名；与其相同时隐藏「打开文档」（已在原文页）
 * @param {import('react').ReactNode} [props.belowSummary] — 插在摘要与来源双栏之间（如「继续探索」快捷问句）
 * @param {Record<string, unknown>|null} [props.apiDebug] — 开发环境展示 POST /insights/document 的 debug（生产勿传）
 */
export default function GroundedInsightPanel({
    summary,
    supportingChunks,
    insufficientEvidence = false,
    onNavigateDocument,
    currentDocId,
    belowSummary = null,
    apiDebug = null,
}) {
    const { t } = useTranslation();
    const baseIdRef = useRef(`g-${Math.random().toString(36).slice(2, 11)}`);
    const baseId = baseIdRef.current;
    const [activeRef, setActiveRef] = useState(null);
    const [tooltip, setTooltip] = useState(null);
    const [summaryAnimClass, setSummaryAnimClass] = useState('');
    const prevSummaryRef = useRef(null);
    const [pulseRefIndex, setPulseRefIndex] = useState(null);
    const previewColRef = useRef(null);
    const sourcesColRef = useRef(null);

    const chunkByRef = useMemo(() => {
        const m = new Map();
        (supportingChunks || []).forEach((ch) => {
            const r = ch?.ref_index;
            if (typeof r === 'number' && r >= 1) {
                m.set(r, ch);
            }
        });
        return m;
    }, [supportingChunks]);

    const sortedSources = useMemo(() => {
        const list = [...(supportingChunks || [])];
        list.sort((a, b) => (a.ref_index || 0) - (b.ref_index || 0));
        return list;
    }, [supportingChunks]);

    /** dev 调试区：把 debug 对象翻成可读要点（与 JSON 块配合） */
    const devDebugHumanLines = useMemo(() => {
        if (!apiDebug || typeof apiDebug !== 'object') return [];
        const pre = apiDebug.vector_hits_pre_doc_filter;
        const post = apiDebug.vector_hits_post_doc_filter;
        const chunkN = apiDebug.chunk_count;
        const docF = apiDebug.doc_filter;
        const mkey = apiDebug.doc_match_key;
        const lines = [];
        if (typeof pre === 'number') {
            lines.push(t('grounded_insight_debug_line_pre', { pre }));
        }
        if (typeof post === 'number') {
            lines.push(t('grounded_insight_debug_line_post', { post }));
        }
        if (typeof chunkN === 'number') {
            lines.push(t('grounded_insight_debug_line_chunks', { n: chunkN }));
        }
        if (docF) {
            lines.push(
                t('grounded_insight_debug_line_doc_filter', {
                    doc: String(docF),
                    key: mkey != null && mkey !== '' ? String(mkey) : '—',
                })
            );
        }
        if (typeof pre === 'number' && pre === 0) {
            lines.push(t('grounded_insight_debug_hint_no_vector'));
        } else if (typeof pre === 'number' && typeof post === 'number' && pre > 0 && post === 0) {
            lines.push(
                docF ? t('grounded_insight_debug_hint_filter_mismatch') : t('grounded_insight_debug_hint_post_zero_plain')
            );
        } else if (typeof post === 'number' && post > 0) {
            lines.push(t('grounded_insight_debug_hint_ok'));
        }
        return lines;
    }, [apiDebug, t]);

    const parsedSummary = useMemo(() => parseStructuredGroundedSummary(summary), [summary]);

    const flatParts = useMemo(
        () => parseSummaryRefs(parsedSummary.mode === 'plain' ? parsedSummary.body : ''),
        [parsedSummary]
    );

    useEffect(() => {
        const prev = prevSummaryRef.current;
        prevSummaryRef.current = summary;
        if (prev !== null && prev !== summary) {
            setSummaryAnimClass('grounded-insight__summary-wrap--enter');
            const id = window.setTimeout(() => setSummaryAnimClass(''), 240);
            return () => clearTimeout(id);
        }
        return undefined;
    }, [summary]);

    useEffect(() => {
        if (pulseRefIndex == null) return undefined;
        const id = window.setTimeout(() => setPulseRefIndex(null), 900);
        return () => clearTimeout(id);
    }, [pulseRefIndex]);

    const scrollToSource = useCallback((ref) => {
        const el = document.getElementById(`grounded-source-${baseId}-${ref}`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        sourcesColRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, [baseId]);

    const onRefClick = useCallback(
        (ref) => {
            setActiveRef(ref);
            setPulseRefIndex(ref);
            requestAnimationFrame(() => {
                scrollToSource(ref);
                previewColRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            });
        },
        [scrollToSource]
    );

    const refPartProps = useMemo(
        () => ({
            chunkByRef,
            activeRef,
            t,
            setTooltip,
            onRefClick,
        }),
        [chunkByRef, activeRef, t, onRefClick]
    );

    const activeChunk = activeRef != null ? chunkByRef.get(activeRef) : null;

    const canJumpTo = (fileName) => {
        if (!onNavigateDocument || !fileName) return false;
        if (currentDocId != null && String(fileName) === String(currentDocId)) return false;
        return true;
    };

    const jumpWithEvidence = (fileName, chunk) => {
        if (!onNavigateDocument || !fileName) return;
        const refIndex = chunk?.ref_index;
        const snippet = chunk?.snippet;
        if (typeof refIndex === 'number' && snippet) {
            onNavigateDocument(String(fileName), { refIndex, snippet });
        } else {
            onNavigateDocument(String(fileName));
        }
    };

    return (
        <div className="grounded-insight">
            {insufficientEvidence ? (
                <div className="grounded-insight__badge grounded-insight__badge--warn" role="status">
                    {t('grounded_insight_evidence_limited')}
                </div>
            ) : (
                <div className="grounded-insight__badge">
                    <Quote size={14} aria-hidden />
                    {t('grounded_insight_evidence_backed')}
                </div>
            )}

            <div
                className={`grounded-insight__summary-wrap${summaryAnimClass ? ` ${summaryAnimClass}` : ''}`}
                aria-label={t('grounded_insight_summary_label')}
            >
                {parsedSummary.mode === 'structured' ? (
                    <div className="grounded-insight__structured">
                        {parsedSummary.sections.map((sec, si) => (
                            <section key={`sec-${si}-${sec.title}`} className="grounded-insight__section">
                                <h4 className="grounded-insight__section-title">{sec.title}</h4>
                                {sec.bullets.length ? (
                                    <ul className="grounded-insight__bullet-list">
                                        {sec.bullets.map((bullet, bi) => (
                                            <li key={`${si}-${bi}`} className="grounded-insight__bullet">
                                                <GroundedRefParts
                                                    parts={parseSummaryRefs(bullet)}
                                                    keyPrefix={`s${si}-b${bi}`}
                                                    {...refPartProps}
                                                />
                                            </li>
                                        ))}
                                    </ul>
                                ) : null}
                            </section>
                        ))}
                    </div>
                ) : (
                    <div className="grounded-insight__summary grounded-insight__summary--plain">
                        <GroundedRefParts parts={flatParts} keyPrefix="p" {...refPartProps} />
                    </div>
                )}
            </div>

            {belowSummary ? <div className="grounded-insight__below-summary">{belowSummary}</div> : null}

            {sortedSources.length > 0 && (
                <>
                    <div className="grounded-insight__grid-head">
                        <span>{t('grounded_insight_sources_heading')}</span>
                        <span>{t('grounded_insight_preview_heading')}</span>
                    </div>
                    <div className="grounded-insight__grid">
                        <div ref={sourcesColRef} className="grounded-insight__sources" role="list">
                            {sortedSources.map((ch) => {
                                const r = ch.ref_index;
                                const fn = ch.file_name || t('grounded_insight_unknown_doc');
                                const isActive = activeRef === r;
                                const isPulse = pulseRefIndex === r;
                                return (
                                    <div
                                        key={`src-${r}-${fn}`}
                                        id={`grounded-source-${baseId}-${r}`}
                                        className={[
                                            'grounded-insight__source',
                                            isActive ? 'grounded-insight__source--active' : '',
                                            isPulse ? 'grounded-insight__source--pulse' : '',
                                        ]
                                            .filter(Boolean)
                                            .join(' ')}
                                        role="listitem"
                                    >
                                        <button
                                            type="button"
                                            className="grounded-insight__source-main"
                                            onClick={() => setActiveRef(r)}
                                        >
                                            <div className="grounded-insight__source-label">
                                                [{r}] {fn}
                                            </div>
                                            <div className="grounded-insight__source-snippet">{ch.snippet || ''}</div>
                                            {typeof ch.score === 'number' ? (
                                                <div className="grounded-insight__source-score" aria-label={t('grounded_insight_score', { score: ch.score.toFixed(3) })}>
                                                    {t('grounded_insight_score_short', { score: ch.score.toFixed(3) })}
                                                </div>
                                            ) : null}
                                        </button>
                                        {canJumpTo(ch.file_name) ? (
                                            <button
                                                type="button"
                                                className="grounded-insight__source-jump"
                                                onClick={() => jumpWithEvidence(String(ch.file_name), ch)}
                                            >
                                                {t('grounded_insight_open_document')}
                                            </button>
                                        ) : null}
                                    </div>
                                );
                            })}
                        </div>
                        <div
                            ref={previewColRef}
                            className={[
                                'grounded-insight__preview',
                                pulseRefIndex != null && activeRef === pulseRefIndex
                                    ? 'grounded-insight__preview--pulse'
                                    : '',
                            ]
                                .filter(Boolean)
                                .join(' ')}
                        >
                            {activeChunk ? (
                                <>
                                    <div className="grounded-insight__preview-title">
                                        [{activeChunk.ref_index}] {activeChunk.file_name || ''}
                                    </div>
                                    {typeof activeChunk.score === 'number' ? (
                                        <div className="grounded-insight__preview-score">
                                            {t('grounded_insight_score_short', { score: activeChunk.score.toFixed(3) })}
                                        </div>
                                    ) : null}
                                    <div
                                        className={[
                                            'grounded-insight__preview-body',
                                            pulseRefIndex === activeChunk.ref_index
                                                ? 'grounded-insight__preview-body--pulse'
                                                : '',
                                        ]
                                            .filter(Boolean)
                                            .join(' ')}
                                    >
                                        {activeChunk.snippet || ''}
                                    </div>
                                    {canJumpTo(activeChunk.file_name) ? (
                                        <button
                                            type="button"
                                            className="grounded-insight__preview-jump"
                                            onClick={() => jumpWithEvidence(String(activeChunk.file_name), activeChunk)}
                                        >
                                            {t('grounded_insight_open_at_evidence')}
                                        </button>
                                    ) : null}
                                </>
                            ) : (
                                <p className="grounded-insight__preview-placeholder">
                                    {t('grounded_insight_preview_hint')}
                                </p>
                            )}
                        </div>
                    </div>
                </>
            )}

            {tooltip?.chunk ? (
                <div
                    className="grounded-insight__tooltip"
                    role="tooltip"
                    style={{
                        left: Math.min(tooltip.x, typeof window !== 'undefined' ? window.innerWidth - 380 : 0),
                        top: tooltip.y,
                    }}
                >
                    <div className="grounded-insight__tooltip-file">{tooltip.chunk.file_name || ''}</div>
                    {typeof tooltip.chunk.score === 'number' ? (
                        <div className="grounded-insight__tooltip-score">
                            {t('grounded_insight_score_short', { score: tooltip.chunk.score.toFixed(3) })}
                        </div>
                    ) : null}
                    <div className="grounded-insight__tooltip-snippet">{tooltip.chunk.snippet || ''}</div>
                </div>
            ) : null}

            {import.meta.env.DEV && apiDebug && typeof apiDebug === 'object' && Object.keys(apiDebug).length > 0 ? (
                <details className="grounded-insight__dev-debug">
                    <summary className="grounded-insight__dev-debug-summary">{t('grounded_insight_dev_debug_summary')}</summary>
                    {devDebugHumanLines.length > 0 ? (
                        <div className="grounded-insight__dev-debug-human">
                            <div className="grounded-insight__dev-debug-human-title">{t('grounded_insight_dev_debug_human_title')}</div>
                            <ul className="grounded-insight__dev-debug-human-list">
                                {devDebugHumanLines.map((line, i) => (
                                    <li key={i}>{line}</li>
                                ))}
                            </ul>
                        </div>
                    ) : null}
                    <pre className="grounded-insight__dev-debug-pre">{JSON.stringify(apiDebug, null, 2)}</pre>
                </details>
            ) : null}
        </div>
    );
}
