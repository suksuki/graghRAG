/**
 * 实体概览文案：优先 API insight，否则用「关联 N 个文档 + 前两个文件名主题词」模板（不直接拼长文件名列表）。
 */

export function fileStemTopic(filename) {
    const base = String(filename).split(/[/\\]/).pop() || '';
    const stem = base.replace(/\.[^.]+$/, '');
    const cleaned = stem.replace(/[_\-]+/g, ' ').trim();
    return (cleaned || base).slice(0, 36);
}

/**
 * @param {object|null} profile - GET /api/entity 响应
 * @param {function} t - i18n t
 */
export function buildEntityOverviewText(profile, t) {
    if (profile?.weak_profile) {
        const docs = profile?.documents || [];
        if (docs.length === 0) return t('entity_weak_no_vector_hits');
        return t('entity_weak_overview', {
            name: profile?.entity || '',
            count: docs.length,
        });
    }

    const insight = (profile?.insight || '').trim();
    if (insight) return insight;

    const docs = profile?.documents || [];
    if (docs.length === 0) return t('entity_no_docs_hint');

    const t1 = fileStemTopic(docs[0]);
    if (docs.length === 1) return t('entity_desc_one_topic', { topic: t1 });

    const t2 = fileStemTopic(docs[1]);
    return t('entity_desc_multi_topics', { count: docs.length, t1, t2 });
}
