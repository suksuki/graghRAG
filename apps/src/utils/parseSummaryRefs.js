/**
 * 将摘要文本拆成普通文本与引用标记 [n]，用于可点击、可悬停的证据高亮。
 * @param {string|null|undefined} text
 * @returns {Array<{ type: 'text', value: string } | { type: 'ref', ref: number }>}
 */
export function parseSummaryRefs(text) {
    const s = text == null ? '' : String(text);
    const re = /\[(\d+)\]/g;
    const parts = [];
    let last = 0;
    let m = re.exec(s);
    while (m !== null) {
        if (m.index > last) {
            parts.push({ type: 'text', value: s.slice(last, m.index) });
        }
        const n = parseInt(m[1], 10);
        if (!Number.isNaN(n) && n >= 1) {
            parts.push({ type: 'ref', ref: n });
        } else {
            parts.push({ type: 'text', value: m[0] });
        }
        last = re.lastIndex;
        m = re.exec(s);
    }
    if (last < s.length) {
        parts.push({ type: 'text', value: s.slice(last) });
    }
    if (parts.length === 0) {
        parts.push({ type: 'text', value: s });
    }
    return parts;
}
