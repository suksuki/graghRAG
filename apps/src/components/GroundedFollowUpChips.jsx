import React, { useMemo, useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Compass } from 'lucide-react';
import './GroundedFollowUpChips.css';

const DOC_PRESET_IDS = [1, 2, 3, 4, 5, 6];
const SEARCH_PRESET_IDS = [1, 2, 3, 4, 5];

/**
 * 摘要下方的「继续探索」快捷问句：点击即用完整 query 回调（不调新接口，由父组件 runInsight）。
 *
 * @param {'document' | 'search'} props.mode
 * @param {string} [props.searchQuery] — mode=search 时用于 i18n 插值 {{q}}
 * @param {boolean} [props.disabled]
 * @param {(fullQuery: string) => void} props.onPick
 */
export default function GroundedFollowUpChips({ mode, searchQuery = '', disabled = false, onPick }) {
    const { t } = useTranslation();
    const chipClickRef = useRef(false);
    /** 本次 Insight 是否由胶囊触发；刷新/首轮加载时清掉，避免误高亮与误提示 */
    const [pendingChip, setPendingChip] = useState(null);

    useEffect(() => {
        if (disabled) {
            if (!chipClickRef.current) setPendingChip(null);
        } else {
            setPendingChip(null);
        }
        chipClickRef.current = false;
    }, [disabled]);

    const ids = useMemo(() => (mode === 'search' ? SEARCH_PRESET_IDS : DOC_PRESET_IDS), [mode]);
    const headingKey =
        mode === 'search' ? 'grounded_search_follow_heading' : 'grounded_doc_follow_heading';
    const regionKey =
        mode === 'search' ? 'grounded_search_follow_region_aria' : 'grounded_doc_follow_region_aria';

    const resolveQuery = (id) => {
        const key = `${mode === 'search' ? 'grounded_search_preset' : 'grounded_doc_preset'}_${id}_query`;
        if (mode === 'search') {
            const q = (searchQuery || '').trim() || t('grounded_search_preset_fallback_q');
            return t(key, { q });
        }
        return t(key);
    };

    const chipKey = (id) => `${mode}-${id}`;

    return (
        <div
            className="grounded-follow"
            role="region"
            aria-label={t(regionKey)}
            aria-busy={disabled && pendingChip ? 'true' : undefined}
        >
            <div className="grounded-follow__head">
                <Compass size={14} aria-hidden />
                {t(headingKey)}
            </div>
            <div className="grounded-follow__chips">
                {ids.map((id) => {
                    const labelKey = `${mode === 'search' ? 'grounded_search_preset' : 'grounded_doc_preset'}_${id}_label`;
                    const fullQ = resolveQuery(id).trim();
                    if (!fullQ) return null;
                    const ck = chipKey(id);
                    const isPending = Boolean(disabled && pendingChip && pendingChip.key === ck);
                    return (
                        <button
                            key={ck}
                            type="button"
                            className={`grounded-follow__btn${isPending ? ' grounded-follow__btn--pending' : ''}`}
                            disabled={disabled}
                            title={fullQ}
                            aria-pressed={isPending}
                            onClick={() => {
                                chipClickRef.current = true;
                                setPendingChip({ key: ck, label: t(labelKey) });
                                onPick(fullQ);
                            }}
                        >
                            {t(labelKey)}
                        </button>
                    );
                })}
            </div>
            {disabled && pendingChip ? (
                <p className="grounded-follow__status" role="status" aria-live="polite">
                    {t('grounded_follow_analyzing', { label: pendingChip.label })}
                </p>
            ) : null}
        </div>
    );
}
