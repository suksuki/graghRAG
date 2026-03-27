import React, { useEffect } from 'react';
import { logInsightEvent } from '../utils/insightEvents';

const MAX_RELATIONS = 3;

function pairLine(a, b, text, onRefClick) {
    return (
        <li key={`${a}-${b}-${text}`} className="relation-block__item">
            <button type="button" className="grounded-insight__ref" onClick={() => onRefClick?.(a)}>
                [{a}]
            </button>{' '}
            与{' '}
            <button type="button" className="grounded-insight__ref" onClick={() => onRefClick?.(b)}>
                [{b}]
            </button>{' '}
            {text}
        </li>
    );
}

/**
 * 关系解释模块（非推理）：仅展示 conflict + co-citation。
 */
export default function InsightRelationBlock({
    conflicts = [],
    coCitationPairs = [],
    onRefClick,
    telemetryDocId = '',
    telemetryInsightId,
}) {
    const raw = [];
    if (Array.isArray(conflicts)) {
        conflicts.forEach((p) => {
            const a = Number(p?.[0]);
            const b = Number(p?.[1]);
            if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) return;
            raw.push({ type: 'conflict', a, b, text: '存在冲突表述' });
        });
    }
    if (Array.isArray(coCitationPairs)) {
        coCitationPairs.forEach((p) => {
            const a = Number(p?.[0]);
            const b = Number(p?.[1]);
            if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) return;
            raw.push({ type: 'co_citation', a, b, text: '共同支持该结论' });
        });
    }

    if (!raw.length) return null;

    // 信息裁剪（非智能优化）：去重 + conflict 优先 + 限制条数
    raw.sort((x, y) => {
        if (x.type === 'conflict' && y.type !== 'conflict') return -1;
        if (x.type !== 'conflict' && y.type === 'conflict') return 1;
        return 0;
    });
    const seen = new Set();
    const deduped = [];
    raw.forEach((r) => {
        const key = [r.a, r.b].sort((m, n) => m - n).join('-');
        if (seen.has(key)) return;
        seen.add(key);
        deduped.push(r);
    });
    const finalRelations = deduped.slice(0, MAX_RELATIONS);
    if (!finalRelations.length) return null;

    // L1 埋点：关系块被渲染（首版以 mount 为 impression）
    useEffect(() => {
        logInsightEvent({
            event: 'relation_block_impression',
            doc_id: telemetryDocId,
            insight_id: telemetryInsightId,
            payload: { relation_count: finalRelations.length },
        });
    }, [finalRelations.length, telemetryDocId, telemetryInsightId]);

    return (
        <div className="relation-block" role="note" aria-label="证据关系">
            <div className="relation-block__title">证据关系</div>
            <ul className="relation-block__list">
                {finalRelations.map((r) => pairLine(r.a, r.b, r.text, onRefClick))}
            </ul>
        </div>
    );
}

