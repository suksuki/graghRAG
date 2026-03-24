import React from 'react';
import { useTranslation } from 'react-i18next';
import { Package, Building2 } from 'lucide-react';

/**
 * 图谱侧「产品 / 行业」关系展示（非 Cypher 三元组，沿用 API 字段）。
 */
export default function EntityRelations({ products, domains, onNavigateEntity }) {
    const { t } = useTranslation();
    const plist = products || [];
    const dlist = domains || [];

    return (
        <>
            <section className="document-detail__panel">
                <div className="document-detail__panel-title">
                    <Package size={16} aria-hidden />
                    {t('products_title')}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {plist.map((p, pi) => (
                        <button
                            key={pi}
                            type="button"
                            className="document-detail__entity-pill"
                            onClick={() => onNavigateEntity?.(p)}
                        >
                            {p}
                        </button>
                    ))}
                    {plist.length === 0 && <span style={{ fontSize: '13px', opacity: 0.75 }}>—</span>}
                </div>
            </section>

            <section className="document-detail__panel">
                <div className="document-detail__panel-title">
                    <Building2 size={16} aria-hidden />
                    {t('industries_title')}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {dlist.map((d, di) => (
                        <button
                            key={di}
                            type="button"
                            className="document-detail__entity-pill"
                            style={{
                                background: 'rgba(16,185,129,0.14)',
                                borderColor: 'rgba(16,185,129,0.28)',
                            }}
                            onClick={() => onNavigateEntity?.(d)}
                        >
                            {d}
                        </button>
                    ))}
                    {dlist.length === 0 && <span style={{ fontSize: '13px', opacity: 0.75 }}>—</span>}
                </div>
            </section>
        </>
    );
}
