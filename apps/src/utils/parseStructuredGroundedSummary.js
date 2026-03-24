/**
 * 解析 LLM 按 prompt 输出的 #### 标题 + "- " 列表结构；无法识别时回退为整段 plain。
 * 与 core/document_insight_service._STRUCTURE_SECTION_TITLES 约定一致。
 */

/** 兼容 #### 标题 / ####标题（与 prompt 推荐「四井号 + 空格」略有偏差时仍能解析） */
const HEADING_RE = /^####\s*(.+)$/;

/**
 * @param {string|null|undefined} text
 * @returns {{ mode: 'plain', body: string } | { mode: 'structured', sections: Array<{ title: string, bullets: string[] }> }}
 */
export function parseStructuredGroundedSummary(text) {
    const raw = text == null ? '' : String(text).trim();
    if (!raw) {
        return { mode: 'plain', body: '' };
    }

    const lines = raw.split('\n');
    const sections = [];
    let i = 0;

    while (i < lines.length) {
        const trimmed = lines[i].trim();
        const hm = trimmed.match(HEADING_RE);
        if (!hm) {
            i += 1;
            continue;
        }
        const title = (hm[1] || '').trim();
        i += 1;
        const bullets = [];
        while (i < lines.length) {
            const t = lines[i].trim();
            if (HEADING_RE.test(t)) {
                break;
            }
            if (t.startsWith('- ') || t.startsWith('• ') || t.startsWith('* ')) {
                bullets.push(t.replace(/^[-•*]\s+/, '').trim());
            }
            i += 1;
        }
        if (title) {
            sections.push({ title, bullets });
        }
    }

    if (sections.length >= 2) {
        return { mode: 'structured', sections };
    }

    return { mode: 'plain', body: raw };
}
