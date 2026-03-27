import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import GroundedInlineRefButton from './GroundedInlineRefButton';
import './V3ExplanationPanel.css';

/**
 * 从 ref_index 列表与 chunk 映射提取轻量「来源」展示（不做 NLP、不裁决）。
 */
function extractSourceSummary(refNums, chunkByRef) {
    const files = new Set();
    refNums.forEach((r) => {
        const ch = chunkByRef.get(r);
        const fn = ch?.file_name || ch?.metadata?.file_name || ch?.source;
        if (fn) {
            const base = String(fn).replace(/\\/g, '/').split('/').pop();
            if (base) files.add(base);
        }
    });
    return [...files].sort();
}

function GroupHeader({ refCount, label, t }) {
    return <div className="v3-explanation__group-header">{t('v3_group_header', { label, count: refCount })}</div>;
}

function RefList({ refs, refsProps }) {
    const {
        chunkByRef,
        rankByRef,
        activeRef,
        conflictPartnersByRef,
        telemetryDocId,
        telemetryInsightId,
        setTooltip,
        onRefClick,
        cancelTooltipDismiss,
        scheduleTooltipDismissFromRef,
        t,
    } = refsProps;
    return (
        <div className="v3-explanation__ref-list" role="group">
            {refs.map((r) => (
                <GroundedInlineRefButton
                    key={`v3-sg-${r}`}
                    refNum={r}
                    chunkByRef={chunkByRef}
                    rankByRef={rankByRef}
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
        </div>
    );
}

function SourceSummary({ refs, chunkByRef, t }) {
    const labels = useMemo(() => extractSourceSummary(refs, chunkByRef), [refs, chunkByRef]);
    if (!labels.length) {
        return <div className="v3-explanation__source-summary">{t('v3_source_unknown')}</div>;
    }
    return (
        <div className="v3-explanation__source-summary">
            {t('v3_source_summary_label')}: {labels.join(' / ')}
        </div>
    );
}

function GroupColumn({ refs, label, refsProps, chunkByRef, t }) {
    return (
        <div className="v3-explanation__group-col">
            <GroupHeader refCount={refs.length} label={label} t={t} />
            <RefList refs={refs} refsProps={refsProps} />
            <SourceSummary refs={refs} chunkByRef={chunkByRef} t={t} />
        </div>
    );
}

function GroupComparison({ groupRows, refsProps, chunkByRef, t }) {
    return (
        <div className="v3-explanation__comparison">
            {groupRows.map(([groupKey, refs]) => (
                <GroupColumn
                    key={groupKey}
                    refs={refs}
                    label={t(`decision_group_${groupKey}`, { defaultValue: groupKey })}
                    refsProps={refsProps}
                    chunkByRef={chunkByRef}
                    t={t}
                />
            ))}
        </div>
    );
}

function Header() {
    const { t } = useTranslation();
    return <div className="v3-explanation__header">{t('v3_panel_header_a')}</div>;
}

function MetaHint() {
    const { t } = useTranslation();
    return <div className="v3-explanation__meta-hint">{t('v3_panel_meta_hint')}</div>;
}

/**
 * v3 结构化解释（仅 Type A：数量/分组；不生成结论、不裁判）。
 * @param {Array<[string, number[]]>} props.groupRows — 与 GroundedInsightPanel.supportGroupRows 一致
 */
export default function V3ExplanationPanel({
    type = 'A',
    groupRows = [],
    signals: _signals,
    refsProps,
    chunkByRef,
}) {
    const { t } = useTranslation();
    if (type !== 'A' || !groupRows?.length) return null;

    return (
        <section className="v3-explanation v3-explanation--type-a" aria-labelledby="v3-explanation-heading">
            <div id="v3-explanation-heading" className="v3-explanation__title">
                {t('v3_panel_title')}
            </div>
            <div className="v3-panel">
                <Header />
                <GroupComparison groupRows={groupRows} refsProps={refsProps} chunkByRef={chunkByRef} t={t} />
                <MetaHint />
            </div>
        </section>
    );
}
