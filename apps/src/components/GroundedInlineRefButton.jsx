import React from 'react';
import { logInsightEvent } from '../utils/insightEvents';

/**
 * Decision v2：分组行内的 [n]，与摘要引用共用交互（无句内共引）。
 */
export default function GroundedInlineRefButton({
    refNum,
    chunkByRef,
    rankByRef,
    activeRef,
    conflictPartnersByRef,
    telemetryDocId = '',
    telemetryInsightId,
    setTooltip,
    onRefClick,
    cancelTooltipDismiss,
    scheduleTooltipDismissFromRef,
    t,
}) {
    const ch = chunkByRef.get(refNum);
    const missing = !ch;
    const rank = rankByRef?.get?.(refNum);
    const showTopMark = rank === 1;
    const topScoreStr =
        showTopMark && typeof ch?.score === 'number' && !Number.isNaN(ch.score) ? ch.score.toFixed(3) : null;
    const conflictPartners = conflictPartnersByRef?.get?.(refNum);
    return (
        <button
            type="button"
            className={[
                'grounded-insight__ref',
                'grounded-insight__ref--inline-group',
                activeRef === refNum ? 'grounded-insight__ref--active' : '',
                missing ? 'grounded-insight__ref--missing' : '',
                showTopMark ? 'grounded-insight__ref--top' : '',
            ]
                .filter(Boolean)
                .join(' ')}
            aria-label={
                showTopMark
                    ? t('grounded_insight_ref_aria_top_evidence', { n: refNum })
                    : t('grounded_insight_ref_aria', { n: refNum })
            }
            title={
                showTopMark
                    ? topScoreStr != null
                        ? t('grounded_insight_ref_top_hover_title_scored', { score: topScoreStr })
                        : t('grounded_insight_ref_top_hover_title')
                    : undefined
            }
            onClick={() => {
                logInsightEvent({
                    event: 'click_reference',
                    doc_id: telemetryDocId,
                    insight_id: telemetryInsightId,
                    payload: { ref_id: String(refNum), position: 'group' },
                });
                onRefClick(refNum);
            }}
            onMouseEnter={(e) => {
                if (!ch) return;
                cancelTooltipDismiss?.();
                const features = [];
                if (rank) features.push('rank');
                if (showTopMark) features.push('star');
                if (Array.isArray(conflictPartners) && conflictPartners.length) features.push('conflict');
                logInsightEvent({
                    event: 'hover_tooltip',
                    doc_id: telemetryDocId,
                    insight_id: telemetryInsightId,
                    payload: { ref_id: String(refNum), features },
                });
                setTooltip({
                    ref: refNum,
                    x: e.clientX + 12,
                    y: e.clientY + 16,
                    chunk: ch,
                    coCitationRefs: undefined,
                    conflictPartners:
                        Array.isArray(conflictPartners) && conflictPartners.length > 0
                            ? conflictPartners
                            : undefined,
                });
            }}
            onMouseMove={(e) => {
                setTooltip((prev) =>
                    prev && prev.ref === refNum ? { ...prev, x: e.clientX + 12, y: e.clientY + 16 } : prev
                );
            }}
            onMouseLeave={() => scheduleTooltipDismissFromRef?.(refNum)}
        >
            [{refNum}
            {showTopMark ? (
                <span className="grounded-insight__ref-top-mark" aria-hidden>
                    {t('grounded_insight_ref_top_mark')}
                </span>
            ) : null}
            ]
        </button>
    );
}
