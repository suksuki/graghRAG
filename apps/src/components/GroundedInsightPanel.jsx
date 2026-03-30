import React, { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Quote, X } from 'lucide-react';
import { parseSummaryRefs } from '../utils/parseSummaryRefs';
import { parseStructuredGroundedSummary } from '../utils/parseStructuredGroundedSummary';
import { getInsightSessionId, logInsightEvent } from '../utils/insightEvents';
import { useFrictionEval } from '../hooks/useFrictionEval';
import FrictionDebugPanel, { isFrictionDebugEnabled } from './FrictionDebugPanel';
import GroundedInlineRefButton from './GroundedInlineRefButton';
import InsightRelationBlock from './InsightRelationBlock';
import V3ExplanationPanel from './V3ExplanationPanel';
import StructuredEvidenceBlock from './StructuredEvidenceBlock';
import './GroundedInsightPanel.css';

/** support_groups 内 ref 所属分组 key（用于埋点） */
function refToGroupKey(ref, decision) {
    const sg = decision?.support_groups;
    if (!sg || typeof sg !== 'object') return null;
    const r = Number(ref);
    if (!Number.isFinite(r)) return null;
    for (const [k, refs] of Object.entries(sg)) {
        if (Array.isArray(refs) && refs.includes(r)) return k;
    }
    return null;
}

/** 同一句/同一条 bullet 内与其他引用共现：ref → 其余 ref_index 升序列表（长度≥2 才有条目） */
function coCitationOthersByRef(parts) {
    const unique = [
        ...new Set(parts.filter((p) => p.type === 'ref').map((p) => p.ref)),
    ].sort((a, b) => a - b);
    if (unique.length < 2) return new Map();
    const m = new Map();
    unique.forEach((r) => m.set(r, unique.filter((x) => x !== r)));
    return m;
}

function pairCombosFromParts(parts) {
    const refs = [...new Set(parts.filter((p) => p.type === 'ref').map((p) => Number(p.ref)).filter(Number.isFinite))].sort(
        (a, b) => a - b
    );
    const out = [];
    if (refs.length < 2) return out;
    for (let i = 0; i < refs.length; i += 1) {
        for (let j = i + 1; j < refs.length; j += 1) {
            out.push([refs[i], refs[j]]);
        }
    }
    return out;
}

/** 单段文本内 [n] 引用按钮（复用于整段摘要与结构化列表项） */
function GroundedRefParts({
    parts,
    keyPrefix,
    partKeyPrefix,
    chunkByRef,
    rankByRef,
    topStarSlotByKey,
    activeRef,
    conflictPartnersByRef,
    telemetryDocId = '',
    telemetryInsightId,
    refClickPosition = 'summary',
    t,
    setTooltip,
    onRefClick,
    cancelTooltipDismiss,
    scheduleTooltipDismissFromRef,
}) {
    const pk = partKeyPrefix ?? keyPrefix;
    const coOthers = coCitationOthersByRef(parts);
    return parts.map((p, i) => {
        if (p.type === 'text') {
            return <span key={`${keyPrefix}-t-${i}`}>{p.value}</span>;
        }
        const ch = chunkByRef.get(p.ref);
        const missing = !ch;
        const rank = rankByRef?.get?.(p.ref);
        const slotKey = `${pk}-${i}`;
        const showTopMark = rank === 1 && topStarSlotByKey?.get(slotKey) === true;
        const topScoreStr =
            showTopMark && typeof ch?.score === 'number' && !Number.isNaN(ch.score) ? ch.score.toFixed(3) : null;
        return (
            <button
                key={`${keyPrefix}-r-${i}-${p.ref}`}
                type="button"
                className={[
                    'grounded-insight__ref',
                    activeRef === p.ref ? 'grounded-insight__ref--active' : '',
                    missing ? 'grounded-insight__ref--missing' : '',
                    showTopMark ? 'grounded-insight__ref--top' : '',
                ]
                    .filter(Boolean)
                    .join(' ')}
                aria-label={
                    showTopMark
                        ? t('grounded_insight_ref_aria_top_evidence', { n: p.ref })
                        : t('grounded_insight_ref_aria', { n: p.ref })
                }
                title={
                    showTopMark
                        ? topScoreStr != null
                            ? t('grounded_insight_ref_top_hover_title_scored', { score: topScoreStr })
                            : t('grounded_insight_ref_top_hover_title')
                        : undefined
                }
                aria-expanded={activeRef === p.ref}
                onClick={() => {
                    logInsightEvent({
                        event: 'click_reference',
                        doc_id: telemetryDocId,
                        insight_id: telemetryInsightId,
                        payload: { ref_id: String(p.ref), position: refClickPosition },
                    });
                    onRefClick(p.ref);
                }}
                onMouseEnter={(e) => {
                    if (!ch) return;
                    cancelTooltipDismiss?.();
                    const siblings = coOthers.get(p.ref) || [];
                    const conflictPartners = conflictPartnersByRef?.get?.(p.ref);
                    const features = [];
                    if (rank) features.push('rank');
                    if (showTopMark) features.push('star');
                    if (siblings.length) features.push('co_citation');
                    if (Array.isArray(conflictPartners) && conflictPartners.length) features.push('conflict');
                    logInsightEvent({
                        event: 'hover_tooltip',
                        doc_id: telemetryDocId,
                        insight_id: telemetryInsightId,
                        payload: { ref_id: String(p.ref), features },
                    });
                    setTooltip({
                        ref: p.ref,
                        x: e.clientX + 12,
                        y: e.clientY + 16,
                        chunk: ch,
                        coCitationRefs: siblings.length > 0 ? siblings : undefined,
                        conflictPartners:
                            Array.isArray(conflictPartners) && conflictPartners.length > 0
                                ? conflictPartners
                                : undefined,
                    });
                }}
                onMouseMove={(e) => {
                    setTooltip((prev) =>
                        prev && prev.ref === p.ref ? { ...prev, x: e.clientX + 12, y: e.clientY + 16 } : prev
                    );
                }}
                onMouseLeave={() => scheduleTooltipDismissFromRef?.(p.ref)}
            >
                [{p.ref}
                {showTopMark ? (
                    <span className="grounded-insight__ref-top-mark" aria-hidden>
                        {t('grounded_insight_ref_top_mark')}
                    </span>
                ) : null}
                ]
            </button>
        );
    });
}

const DECISION_GROUP_ORDER = [
    'increase',
    'decrease',
    'rise',
    'fall',
    'support',
    'oppose',
    'allow',
    'forbid',
    'other',
];

/**
 * 渲染有据摘要：summary 中 [n] 可 hover（tooltip）、click（高亮来源 + 右侧预览）、来源行可点击跳转文档。
 *
 * @param {object} props
 * @param {string} props.summary
 * @param {Array<object>} props.supportingChunks — API supporting_chunks（含 ref_index）
 * @param {Array<object>} [props.structuredEvidence] — API structured_evidence（带 ref/file provenance）
 * @param {boolean} [props.insufficientEvidence]
 * @param {(fileName: string, meta?: { refIndex: number, snippet?: string }) => void} [props.onNavigateDocument] — 打开文档；meta 用于原文侧滚动对齐片段
 * @param {string} [props.currentDocId] — 当前正在查看的文件名；与其相同时隐藏「打开文档」（已在原文页）
 * @param {import('react').ReactNode} [props.belowSummary] — 插在摘要与来源双栏之间（如「继续探索」快捷问句）
 * @param {{ conflicts?: Array<{ refs: number[], type?: string }>, support_groups?: Record<string, number[]>|null }|null} [props.decision] — Decision：冲突 + 可选 support_groups
 * @param {Record<string, unknown>|null} [props.apiDebug] — 开发环境展示 POST /insights/document 的 debug（生产勿传）
 * @param {string} [props.telemetryDocId] — 埋点 doc 上下文（文档页为 `docId`；无文档场景可用 `__insight__` / `__search__`）
 * @param {string} [props.telemetryInsightId] — 可选：本次问题/检索词（与 doc_id 组合区分会话）
 */
export default function GroundedInsightPanel({
    summary,
    supportingChunks,
    structuredEvidence = [],
    insufficientEvidence = false,
    onNavigateDocument,
    currentDocId,
    belowSummary = null,
    decision = null,
    telemetryDocId = '',
    telemetryInsightId,
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
    /** rank #1 引用点击时用更强 pulse + 略长动画 */
    const [pulseIsTopEvidence, setPulseIsTopEvidence] = useState(false);
    const previewColRef = useRef(null);
    const sourcesColRef = useRef(null);
    const tooltipLeaveTimerRef = useRef(null);
    const summaryDwellRef = useRef(null);
    const conflictDwellRef = useRef(null);
    const groupsDwellRef = useRef(null);
    const prevGroupForActiveRef = useRef(null);
    const viewedGroupKeysRef = useRef(new Set());

    const frictionDebugOn = isFrictionDebugEnabled();
    const [sessionIdForFriction] = useState(() => getInsightSessionId());
    const frictionEval = useFrictionEval({
        enabled: frictionDebugOn,
        sessionId: sessionIdForFriction,
        docId: telemetryDocId || '',
    });

    const cancelTooltipDismiss = useCallback(() => {
        if (tooltipLeaveTimerRef.current != null) {
            window.clearTimeout(tooltipLeaveTimerRef.current);
            tooltipLeaveTimerRef.current = null;
        }
    }, []);

    const scheduleTooltipDismissFromRef = useCallback(
        (refNum) => {
            cancelTooltipDismiss();
            tooltipLeaveTimerRef.current = window.setTimeout(() => {
                tooltipLeaveTimerRef.current = null;
                setTooltip((prev) => (prev?.ref === refNum ? null : prev));
            }, 320);
        },
        [cancelTooltipDismiss]
    );

    useEffect(
        () => () => {
            if (tooltipLeaveTimerRef.current != null) {
                window.clearTimeout(tooltipLeaveTimerRef.current);
            }
        },
        []
    );

    useEffect(() => {
        if (!tooltip?.chunk) return undefined;
        const onKey = (e) => {
            if (e.key === 'Escape') {
                cancelTooltipDismiss();
                setTooltip(null);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [tooltip?.chunk, cancelTooltipDismiss]);

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

    /** ref_index → 与其启发式冲突的其它 ref（升序，用于 tooltip） */
    const conflictPartnersByRef = useMemo(() => {
        const m = new Map();
        const raw = decision?.conflicts;
        if (!Array.isArray(raw)) return m;
        raw.forEach((c) => {
            const refs = c?.refs;
            if (!Array.isArray(refs) || refs.length !== 2) return;
            const a = Number(refs[0]);
            const b = Number(refs[1]);
            if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) return;
            if (!m.has(a)) m.set(a, []);
            if (!m.has(b)) m.set(b, []);
            m.get(a).push(b);
            m.get(b).push(a);
        });
        m.forEach((arr, k) => {
            m.set(k, [...new Set(arr)].sort((x, y) => x - y));
        });
        return m;
    }, [decision]);

    const hasConflictEvidence = (decision?.conflicts?.length ?? 0) > 0;

    const supportGroupRows = useMemo(() => {
        const sg = decision?.support_groups;
        if (!sg || typeof sg !== 'object') return [];
        const rows = [];
        DECISION_GROUP_ORDER.forEach((k) => {
            const refs = sg[k];
            if (Array.isArray(refs) && refs.length > 0) {
                rows.push([k, [...refs].sort((a, b) => a - b)]);
            }
        });
        Object.keys(sg).forEach((k) => {
            if (DECISION_GROUP_ORDER.includes(k)) return;
            const refs = sg[k];
            if (Array.isArray(refs) && refs.length > 0) {
                rows.push([k, [...refs].sort((a, b) => a - b)]);
            }
        });
        // 若至少有一组含 2+ 条 ref，则隐藏「单 ref」组，减轻噪音；若全部为单 ref（典型 1 vs 1），仍全部展示
        const hasMultiRefGroup = rows.some(([, refs]) => refs.length >= 2);
        if (hasMultiRefGroup) {
            return rows.filter(([, refs]) => refs.length >= 2);
        }
        return rows;
    }, [decision]);

    const hasSupportStructure = supportGroupRows.length > 0;

    const showV3A =
        frictionDebugOn &&
        frictionEval.data?.suggested_v3 === 'A' &&
        supportGroupRows.length > 0;

    useEffect(() => {
        viewedGroupKeysRef.current = new Set();
        prevGroupForActiveRef.current = null;
    }, [summary]);

    useEffect(() => {
        if (activeRef == null) {
            prevGroupForActiveRef.current = null;
            return;
        }
        const g = refToGroupKey(activeRef, decision);
        const prev = prevGroupForActiveRef.current;
        if (prev != null && g != null && prev !== g) {
            logInsightEvent({
                event: 'switch_conflict_group',
                doc_id: telemetryDocId,
                insight_id: telemetryInsightId,
                payload: { from_group: prev, to_group: g },
            });
        }
        prevGroupForActiveRef.current = g;
    }, [activeRef, decision, telemetryDocId, telemetryInsightId]);

    useEffect(() => {
        supportGroupRows.forEach(([k, refs]) => {
            if (viewedGroupKeysRef.current.has(k)) return;
            viewedGroupKeysRef.current.add(k);
            logInsightEvent({
                event: 'view_support_group',
                doc_id: telemetryDocId,
                insight_id: telemetryInsightId,
                payload: { group_id: k, ref_count: refs.length },
            });
        });
    }, [supportGroupRows, telemetryDocId, telemetryInsightId]);

    useEffect(() => {
        const nodes = [
            [summaryDwellRef.current, 'summary'],
            [hasConflictEvidence ? conflictDwellRef.current : null, 'conflict'],
            [hasSupportStructure ? groupsDwellRef.current : null, 'group'],
        ].filter(([el]) => el);
        if (!nodes.length) return undefined;
        const starts = new Map();
        const obs = new IntersectionObserver(
            (entries) => {
                entries.forEach((en) => {
                    const section = en.target.dataset.dwellSection;
                    if (!section) return;
                    if (en.isIntersecting) {
                        starts.set(section, Date.now());
                    } else {
                        const t0 = starts.get(section);
                        if (t0) {
                            const duration_ms = Date.now() - t0;
                            if (duration_ms >= 800) {
                                logInsightEvent({
                                    event: 'dwell_time',
                                    doc_id: telemetryDocId,
                                    insight_id: telemetryInsightId,
                                    payload: { section, duration_ms },
                                });
                            }
                            starts.delete(section);
                        }
                    }
                });
            },
            { threshold: 0.12, rootMargin: '0px' }
        );
        nodes.forEach(([el, section]) => {
            el.dataset.dwellSection = section;
            obs.observe(el);
        });
        return () => obs.disconnect();
    }, [hasConflictEvidence, hasSupportStructure, summary, telemetryDocId, telemetryInsightId]);

    /** 本批片段内按 score 排序的位次 + 归一化权重（用于视觉强弱，不改变 [n] 与摘要顺序） */
    const retrievalRanking = useMemo(() => {
        const list = sortedSources;
        const total = list.length;
        const numeric = list.map((c) => c.score).filter((s) => typeof s === 'number' && !Number.isNaN(s));
        let minV = 0;
        let maxV = 1;
        if (numeric.length) {
            minV = Math.min(...numeric);
            maxV = Math.max(...numeric);
        }
        const order = [...list].sort((a, b) => {
            const as = typeof a.score === 'number' && !Number.isNaN(a.score) ? a.score : -Infinity;
            const bs = typeof b.score === 'number' && !Number.isNaN(b.score) ? b.score : -Infinity;
            if (bs !== as) return bs - as;
            return (a.ref_index || 0) - (b.ref_index || 0);
        });
        const rankByRef = new Map();
        order.forEach((ch, i) => rankByRef.set(ch.ref_index, i + 1));
        const weightByRef = new Map();
        list.forEach((ch) => {
            const ri = ch.ref_index;
            if (typeof ch.score !== 'number' || Number.isNaN(ch.score)) {
                weightByRef.set(ri, 0.68);
                return;
            }
            const w = maxV > minV ? (ch.score - minV) / (maxV - minV) : 1;
            weightByRef.set(ri, Math.max(0, Math.min(1, w)));
        });
        return { rankByRef, weightByRef, total };
    }, [sortedSources]);

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

    /** 摘要阅读顺序内：每个 ref_index 仅在首次出现且 rank===1 时显示 ★，降低重复噪音 */
    const topStarSlotByKey = useMemo(() => {
        const rankByRef = retrievalRanking.rankByRef;
        const m = new Map();
        const seenTopRef = new Set();

        const walkParts = (parts, prefix) => {
            parts.forEach((p, i) => {
                if (p.type !== 'ref') return;
                const key = `${prefix}-${i}`;
                const r = p.ref;
                if (rankByRef.get(r) === 1 && !seenTopRef.has(r)) {
                    m.set(key, true);
                    seenTopRef.add(r);
                } else {
                    m.set(key, false);
                }
            });
        };

        if (parsedSummary.mode === 'structured') {
            parsedSummary.sections.forEach((sec, si) => {
                sec.bullets.forEach((bullet, bi) => {
                    walkParts(parseSummaryRefs(bullet), `s${si}-b${bi}`);
                });
            });
        } else {
            walkParts(parseSummaryRefs(parsedSummary.body), 'p');
        }
        return m;
    }, [parsedSummary, retrievalRanking.rankByRef]);

    /** 结构化列表项：含「摘要中首次出现的 top 引用 ★」时做句级弱强调 */
    const bulletFirstTopKeys = useMemo(() => {
        const keys = new Set();
        if (parsedSummary.mode !== 'structured') return keys;
        const rankByRef = retrievalRanking.rankByRef;
        parsedSummary.sections.forEach((sec, si) => {
            sec.bullets.forEach((bullet, bi) => {
                const parts = parseSummaryRefs(bullet);
                const hit = parts.some(
                    (p, i) =>
                        p.type === 'ref' &&
                        rankByRef.get(p.ref) === 1 &&
                        topStarSlotByKey.get(`s${si}-b${bi}-${i}`) === true
                );
                if (hit) keys.add(`s${si}-b${bi}`);
            });
        });
        return keys;
    }, [parsedSummary, retrievalRanking.rankByRef, topStarSlotByKey]);

    const flatParts = useMemo(
        () => parseSummaryRefs(parsedSummary.mode === 'plain' ? parsedSummary.body : ''),
        [parsedSummary]
    );

    const relationConflictPairs = useMemo(() => {
        const raw = decision?.conflicts;
        if (!Array.isArray(raw)) return [];
        const seen = new Set();
        const out = [];
        raw.forEach((c) => {
            const refs = Array.isArray(c?.refs) ? c.refs : [];
            for (let i = 0; i < refs.length; i += 1) {
                for (let j = i + 1; j < refs.length; j += 1) {
                    const a = Number(refs[i]);
                    const b = Number(refs[j]);
                    if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) continue;
                    const x = Math.min(a, b);
                    const y = Math.max(a, b);
                    const k = `${x}-${y}`;
                    if (seen.has(k)) continue;
                    seen.add(k);
                    out.push([x, y]);
                }
            }
        });
        return out;
    }, [decision]);

    const relationCoCitationPairs = useMemo(() => {
        const seen = new Set();
        const out = [];
        const pushPairs = (pairs) => {
            pairs.forEach(([a, b]) => {
                const k = `${a}-${b}`;
                if (seen.has(k)) return;
                seen.add(k);
                out.push([a, b]);
            });
        };
        if (parsedSummary.mode === 'structured') {
            parsedSummary.sections.forEach((sec) => {
                sec.bullets.forEach((bullet) => {
                    pushPairs(pairCombosFromParts(parseSummaryRefs(bullet)));
                });
            });
        } else {
            pushPairs(pairCombosFromParts(flatParts));
        }
        const conflictKeys = new Set(relationConflictPairs.map(([a, b]) => `${a}-${b}`));
        return out.filter(([a, b]) => !conflictKeys.has(`${a}-${b}`));
    }, [parsedSummary, flatParts, relationConflictPairs]);

    /** 纯文本摘要：若存在首次 top ★，整块左侧弱强调（无语义列表时） */
    const plainHasFirstTopAnchor = useMemo(() => {
        if (parsedSummary.mode !== 'plain') return false;
        const rankByRef = retrievalRanking.rankByRef;
        return flatParts.some(
            (p, i) =>
                p.type === 'ref' &&
                rankByRef.get(p.ref) === 1 &&
                topStarSlotByKey.get(`p-${i}`) === true
        );
    }, [parsedSummary.mode, flatParts, retrievalRanking.rankByRef, topStarSlotByKey]);

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
        const ms = pulseIsTopEvidence ? 1200 : 900;
        const id = window.setTimeout(() => {
            setPulseRefIndex(null);
            setPulseIsTopEvidence(false);
        }, ms);
        return () => clearTimeout(id);
    }, [pulseRefIndex, pulseIsTopEvidence]);

    const scrollToSource = useCallback((ref) => {
        const el = document.getElementById(`grounded-source-${baseId}-${ref}`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        sourcesColRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        requestAnimationFrame(() => {
            const btn = el?.querySelector?.('.grounded-insight__source-main');
            if (btn && typeof btn.focus === 'function') {
                btn.focus({ preventScroll: true });
            }
        });
    }, [baseId]);

    const onRefClick = useCallback(
        (ref) => {
            setActiveRef(ref);
            setPulseRefIndex(ref);
            setPulseIsTopEvidence(retrievalRanking.rankByRef.get(ref) === 1);
            requestAnimationFrame(() => {
                scrollToSource(ref);
                previewColRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            });
        },
        [scrollToSource, retrievalRanking.rankByRef]
    );

    const refPartProps = useMemo(
        () => ({
            chunkByRef,
            rankByRef: retrievalRanking.rankByRef,
            topStarSlotByKey,
            activeRef,
            conflictPartnersByRef,
            telemetryDocId,
            telemetryInsightId,
            refClickPosition: 'summary',
            t,
            setTooltip,
            onRefClick,
            cancelTooltipDismiss,
            scheduleTooltipDismissFromRef,
        }),
        [
            chunkByRef,
            retrievalRanking.rankByRef,
            topStarSlotByKey,
            activeRef,
            conflictPartnersByRef,
            telemetryDocId,
            telemetryInsightId,
            t,
            onRefClick,
            cancelTooltipDismiss,
            scheduleTooltipDismissFromRef,
        ]
    );

    const v3RefsProps = useMemo(
        () => ({
            chunkByRef,
            rankByRef: retrievalRanking.rankByRef,
            activeRef,
            conflictPartnersByRef,
            telemetryDocId,
            telemetryInsightId,
            setTooltip,
            onRefClick,
            cancelTooltipDismiss,
            scheduleTooltipDismissFromRef,
            t,
        }),
        [
            chunkByRef,
            retrievalRanking.rankByRef,
            activeRef,
            conflictPartnersByRef,
            telemetryDocId,
            telemetryInsightId,
            setTooltip,
            onRefClick,
            cancelTooltipDismiss,
            scheduleTooltipDismissFromRef,
            t,
        ]
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

            {sortedSources.length > 0 ? (
                <p className="grounded-insight__star-legend" role="note">
                    <span className="grounded-insight__star-legend-mark" aria-hidden>
                        {t('grounded_insight_ref_top_mark')}
                    </span>{' '}
                    {t('grounded_insight_star_legend')}
                </p>
            ) : null}

            <div
                ref={summaryDwellRef}
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
                                            <li
                                                key={`${si}-${bi}`}
                                                className={[
                                                    'grounded-insight__bullet',
                                                    bulletFirstTopKeys.has(`s${si}-b${bi}`)
                                                        ? 'grounded-insight__bullet--top-evidence-line'
                                                        : '',
                                                ]
                                                    .filter(Boolean)
                                                    .join(' ')}
                                            >
                                                <GroundedRefParts
                                                    parts={parseSummaryRefs(bullet)}
                                                    keyPrefix={`s${si}-b${bi}`}
                                                    partKeyPrefix={`s${si}-b${bi}`}
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
                    <div
                        className={[
                            'grounded-insight__summary',
                            'grounded-insight__summary--plain',
                            plainHasFirstTopAnchor ? 'grounded-insight__summary--top-evidence-anchor' : '',
                        ]
                            .filter(Boolean)
                            .join(' ')}
                    >
                        <GroundedRefParts parts={flatParts} keyPrefix="p" partKeyPrefix="p" {...refPartProps} />
                    </div>
                )}
            </div>

            <StructuredEvidenceBlock
                structuredEvidence={structuredEvidence}
                chunkByRef={chunkByRef}
                activeRef={activeRef}
                onRefClick={onRefClick}
                onNavigateDocument={onNavigateDocument}
                currentDocId={currentDocId}
            />

            <InsightRelationBlock
                conflicts={relationConflictPairs}
                coCitationPairs={relationCoCitationPairs}
                onRefClick={onRefClick}
                telemetryDocId={telemetryDocId}
                telemetryInsightId={telemetryInsightId}
            />

            {hasConflictEvidence ? (
                <div ref={conflictDwellRef} className="grounded-insight__decision-warning" role="status">
                    {t('grounded_insight_conflict_warning')}
                </div>
            ) : null}

            {hasSupportStructure ? (
                <div
                    ref={groupsDwellRef}
                    className="grounded-insight__decision-groups"
                    role="region"
                    aria-label={t('grounded_insight_decision_groups_aria')}
                >
                    {supportGroupRows.map(([groupKey, refs]) => (
                        <div key={groupKey} className="grounded-insight__decision-groups__row">
                            <span className="grounded-insight__decision-groups__label">
                                {t(`decision_group_${groupKey}`, { defaultValue: groupKey })}
                            </span>
                            <span className="grounded-insight__decision-groups__refs">
                                {refs.map((r) => (
                                    <GroundedInlineRefButton
                                        key={`sg-${groupKey}-${r}`}
                                        refNum={r}
                                        chunkByRef={chunkByRef}
                                        rankByRef={retrievalRanking.rankByRef}
                                        activeRef={activeRef}
                                        conflictPartnersByRef={conflictPartnersByRef}
                                        telemetryDocId={telemetryDocId}
                                        telemetryInsightId={telemetryInsightId}
                                        setTooltip={setTooltip}
                                        onRefClick={onRefClick}
                                        cancelTooltipDismiss={cancelTooltipDismiss}
                                        scheduleTooltipDismissFromRef={scheduleTooltipDismissFromRef}
                                        t={t}
                                    />
                                ))}
                            </span>
                        </div>
                    ))}
                </div>
            ) : null}

            {belowSummary ? <div className="grounded-insight__below-summary">{belowSummary}</div> : null}

            {showV3A ? (
                <V3ExplanationPanel
                    type="A"
                    groupRows={supportGroupRows}
                    signals={frictionEval.data?.signals}
                    refsProps={v3RefsProps}
                    chunkByRef={chunkByRef}
                />
            ) : null}

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
                                const pulseStrong = isPulse && pulseIsTopEvidence;
                                const rank = retrievalRanking.rankByRef.get(r) ?? 0;
                                const w = retrievalRanking.weightByRef.get(r) ?? 0.72;
                                return (
                                    <div
                                        key={`src-${r}-${fn}`}
                                        id={`grounded-source-${baseId}-${r}`}
                                        className={[
                                            'grounded-insight__source',
                                            isActive ? 'grounded-insight__source--active' : '',
                                            pulseStrong
                                                ? 'grounded-insight__source--pulse-top'
                                                : isPulse
                                                  ? 'grounded-insight__source--pulse'
                                                  : '',
                                        ]
                                            .filter(Boolean)
                                            .join(' ')}
                                        style={isActive ? undefined : { '--grounded-score-w': String(w) }}
                                        role="listitem"
                                    >
                                        <button
                                            type="button"
                                            className="grounded-insight__source-main"
                                            onClick={() => setActiveRef(r)}
                                        >
                                            <div className="grounded-insight__source-label-row">
                                                {rank > 0 ? (
                                                    <span
                                                        className="grounded-insight__source-rank"
                                                        title={t('grounded_insight_source_rank_title', {
                                                            rank,
                                                            total: retrievalRanking.total,
                                                        })}
                                                    >
                                                        #{rank}
                                                    </span>
                                                ) : null}
                                                <div className="grounded-insight__source-label">
                                                    [{r}] {fn}
                                                </div>
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
                                pulseRefIndex != null &&
                                activeRef === pulseRefIndex &&
                                pulseIsTopEvidence
                                    ? 'grounded-insight__preview--pulse-top'
                                    : pulseRefIndex != null && activeRef === pulseRefIndex
                                      ? 'grounded-insight__preview--pulse'
                                      : '',
                            ]
                                .filter(Boolean)
                                .join(' ')}
                        >
                            {activeChunk ? (
                                <>
                                    <div className="grounded-insight__preview-title-row">
                                        {retrievalRanking.rankByRef.get(activeChunk.ref_index) ? (
                                            <span
                                                className="grounded-insight__preview-rank"
                                                title={t('grounded_insight_source_rank_title', {
                                                    rank: retrievalRanking.rankByRef.get(activeChunk.ref_index),
                                                    total: retrievalRanking.total,
                                                })}
                                            >
                                                #{retrievalRanking.rankByRef.get(activeChunk.ref_index)}
                                            </span>
                                        ) : null}
                                        <div className="grounded-insight__preview-title">
                                            [{activeChunk.ref_index}] {activeChunk.file_name || ''}
                                        </div>
                                    </div>
                                    {typeof activeChunk.score === 'number' ? (
                                        <div className="grounded-insight__preview-score">
                                            {t('grounded_insight_score_short', { score: activeChunk.score.toFixed(3) })}
                                        </div>
                                    ) : null}
                                    <div
                                        className={[
                                            'grounded-insight__preview-body',
                                            pulseRefIndex === activeChunk.ref_index && pulseIsTopEvidence
                                                ? 'grounded-insight__preview-body--pulse-top'
                                                : pulseRefIndex === activeChunk.ref_index
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
                    onMouseEnter={cancelTooltipDismiss}
                    onMouseLeave={() => {
                        cancelTooltipDismiss();
                        setTooltip(null);
                    }}
                >
                    <button
                        type="button"
                        className="grounded-insight__tooltip-dismiss"
                        aria-label={t('grounded_insight_tooltip_close')}
                        onClick={(e) => {
                            e.stopPropagation();
                            cancelTooltipDismiss();
                            setTooltip(null);
                        }}
                    >
                        <X size={14} strokeWidth={2} aria-hidden />
                    </button>
                    {(() => {
                        const tipRank = retrievalRanking.rankByRef.get(tooltip.chunk.ref_index);
                        const tipIsTopBatch = tipRank === 1;
                        const tipScored = typeof tooltip.chunk.score === 'number';
                        return (
                            <>
                                <div className="grounded-insight__tooltip-head">
                                    {tipRank ? (
                                        <span
                                            className="grounded-insight__tooltip-rank"
                                            title={t('grounded_insight_source_rank_title', {
                                                rank: tipRank,
                                                total: retrievalRanking.total,
                                            })}
                                        >
                                            #{tipRank}
                                        </span>
                                    ) : null}
                                    <div className="grounded-insight__tooltip-file">{tooltip.chunk.file_name || ''}</div>
                                </div>
                                {tipIsTopBatch ? (
                                    <p className="grounded-insight__tooltip-top-evidence">
                                        {tipScored
                                            ? t('grounded_insight_tooltip_top_evidence_scored', {
                                                  score: tooltip.chunk.score.toFixed(3),
                                              })
                                            : t('grounded_insight_tooltip_top_evidence_plain')}
                                    </p>
                                ) : null}
                                {tipScored && !tipIsTopBatch ? (
                                    <div className="grounded-insight__tooltip-score">
                                        {t('grounded_insight_score_short', { score: tooltip.chunk.score.toFixed(3) })}
                                    </div>
                                ) : null}
                                {Array.isArray(tooltip.conflictPartners) && tooltip.conflictPartners.length > 0 ? (
                                    <p className="grounded-insight__tooltip-conflict" role="note">
                                        {t('grounded_insight_conflict_tooltip', {
                                            refs: tooltip.conflictPartners.map((r) => `[${r}]`).join(', '),
                                        })}
                                    </p>
                                ) : null}
                                {Array.isArray(tooltip.coCitationRefs) && tooltip.coCitationRefs.length > 0 ? (
                                    <>
                                        <p className="grounded-insight__tooltip-co-citation" role="note">
                                            <span className="grounded-insight__tooltip-co-citation-label">
                                                {t('grounded_insight_tooltip_also_supported_before')}
                                            </span>
                                            {tooltip.coCitationRefs.map((r, idx) => {
                                                const coRank = retrievalRanking.rankByRef.get(r) ?? 0;
                                                return (
                                                    <span key={`co-${r}`} className="grounded-insight__tooltip-co-citation-item">
                                                        {idx > 0 ? (
                                                            <span className="grounded-insight__tooltip-co-citation-sep" aria-hidden>
                                                                {', '}
                                                            </span>
                                                        ) : null}
                                                        <button
                                                            type="button"
                                                            className="grounded-insight__tooltip-co-citation-ref"
                                                            aria-label={
                                                                coRank > 0
                                                                    ? t('grounded_insight_tooltip_co_ref_aria', {
                                                                          n: r,
                                                                          rank: coRank,
                                                                          total: retrievalRanking.total,
                                                                      })
                                                                    : t('grounded_insight_ref_aria', { n: r })
                                                            }
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                cancelTooltipDismiss();
                                                                setTooltip(null);
                                                                onRefClick(r);
                                                            }}
                                                        >
                                                            [{r}]
                                                        </button>
                                                        {coRank > 0 ? (
                                                            <span
                                                                className="grounded-insight__tooltip-co-citation-rank"
                                                                title={t('grounded_insight_source_rank_title', {
                                                                    rank: coRank,
                                                                    total: retrievalRanking.total,
                                                                })}
                                                                aria-hidden
                                                            >
                                                                #{coRank}
                                                            </span>
                                                        ) : null}
                                                    </span>
                                                );
                                            })}
                                            {t('grounded_insight_tooltip_also_supported_after') ? (
                                                <span className="grounded-insight__tooltip-co-citation-after">
                                                    {t('grounded_insight_tooltip_also_supported_after')}
                                                </span>
                                            ) : null}
                                        </p>
                                        <p className="grounded-insight__tooltip-reasoning-hint" role="note">
                                            {tooltip.coCitationRefs.length >= 2
                                                ? t('grounded_insight_tooltip_multi_aligned_sources')
                                                : t('grounded_insight_tooltip_reasoning_joint_hint')}
                                        </p>
                                    </>
                                ) : null}
                            </>
                        );
                    })()}
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

            {frictionDebugOn ? <FrictionDebugPanel evalResult={frictionEval} /> : null}
        </div>
    );
}
