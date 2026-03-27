import React, { useMemo, useState } from 'react';

export default function DocScopePicker({ docs = [], onSelect }) {
    const [open, setOpen] = useState(false);
    const safeDocs = useMemo(() => (Array.isArray(docs) ? docs : []), [docs]);

    return (
        <div style={{ position: 'relative' }}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-label="选择文档范围"
                title="选择文档范围"
                style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    border: '1px solid rgba(148,163,184,0.45)',
                    background: 'transparent',
                    color: 'inherit',
                    cursor: 'pointer',
                }}
            >
                📎
            </button>
            {open ? (
                <div
                    style={{
                        position: 'absolute',
                        bottom: 40,
                        left: 0,
                        background: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: 8,
                        padding: 8,
                        width: 240,
                        maxHeight: 260,
                        overflowY: 'auto',
                        zIndex: 12,
                    }}
                >
                    {safeDocs.length === 0 ? (
                        <div style={{ opacity: 0.7, fontSize: 12, padding: 6 }}>暂无可选文档</div>
                    ) : (
                        safeDocs.map((doc) => {
                            const name = doc?.name || doc?.file_name || doc?.doc_id || '';
                            if (!name) return null;
                            return (
                                <div
                                    key={name}
                                    style={{ padding: '6px 8px', cursor: 'pointer', borderRadius: 6 }}
                                    onClick={() => {
                                        onSelect?.(doc);
                                        setOpen(false);
                                    }}
                                >
                                    📄 {name}
                                </div>
                            );
                        })
                    )}
                </div>
            ) : null}
        </div>
    );
}

