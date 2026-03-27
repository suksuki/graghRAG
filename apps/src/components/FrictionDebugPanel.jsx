import React from 'react';
import './FrictionDebugPanel.css';

const LABELS = {
    friction: {
        T1: '冲突来回（T1）',
        T2: '只 hover（T2）',
        T3: '冲突区停滞（T3）',
        T4: '显式提问（T4）',
        TB: '有证据仍切换（TB）',
        TQ: '数量/分组信号（TQ）',
    },
    suggested: {
        A: 'Type A · 数量/结构',
        B: 'Type B · 来源类型',
        C: 'Type C · 时间维度',
        D: 'Type D · 语义 framing',
    },
};

/**
 * 内部调试：展示摩擦类型与 v3 形态建议（不面向最终用户）。
 * 数据由父组件 `useFrictionEval` 注入，避免与 v3 面板重复轮询。
 */
export default function FrictionDebugPanel({ evalResult }) {
    const data = evalResult?.data;
    const err = evalResult?.err;
    const loading = evalResult?.loading;
    const refresh = evalResult?.refresh;

    const ft = data?.friction_type;
    const sv = data?.suggested_v3;

    return (
        <aside className="friction-debug" aria-label="Friction debug">
            <div className="friction-debug__title">认知摩擦 · v3 候选（内部）</div>
            {loading && !data ? <div className="friction-debug__muted">加载中…</div> : null}
            {err ? <div className="friction-debug__err">{err}</div> : null}
            {data ? (
                <>
                    <div className="friction-debug__row">
                        <span className="friction-debug__k">Friction</span>
                        <span className="friction-debug__v">
                            {ft ? LABELS.friction[ft] || ft : '—'}
                        </span>
                    </div>
                    <div className="friction-debug__row">
                        <span className="friction-debug__k">Suggested</span>
                        <span className="friction-debug__v">
                            {sv ? LABELS.suggested[sv] || sv : '—'}
                        </span>
                    </div>
                    <div className="friction-debug__row friction-debug__row--small">
                        <span className="friction-debug__k">events</span>
                        <span>{data.event_count ?? 0}</span>
                    </div>
                    <pre className="friction-debug__pre">{JSON.stringify(data.counts || {}, null, 0)}</pre>
                    <button type="button" className="friction-debug__btn" onClick={() => refresh?.()}>
                        刷新
                    </button>
                </>
            ) : null}
        </aside>
    );
}

export function isFrictionDebugEnabled() {
    try {
        if (import.meta.env?.DEV) return true;
        return typeof localStorage !== 'undefined' && localStorage.getItem('graphrag_debug_friction') === '1';
    } catch {
        return false;
    }
}
