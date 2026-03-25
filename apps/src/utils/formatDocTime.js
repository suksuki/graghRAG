/**
 * @param {number | string | null | undefined} mtime Unix seconds or ms, or date string
 * @param {string} lang i18n language code (zh / en / ko)
 * @returns {string}
 */
export function formatRelativeDocTime(mtime, lang) {
    const ms = toEpochMs(mtime);
    if (ms == null) return '';

    const locale =
        lang === 'zh' || String(lang || '').startsWith('zh')
            ? 'zh-CN'
            : lang === 'ko' || String(lang || '').startsWith('ko')
              ? 'ko'
              : 'en';

    const diffSec = (ms - Date.now()) / 1000;
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    const a = Math.abs(diffSec);

    if (a < 45) return rtf.format(Math.round(diffSec), 'second');
    if (a < 2700) return rtf.format(Math.round(diffSec / 60), 'minute');
    if (a < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour');
    if (a < 604800) return rtf.format(Math.round(diffSec / 86400), 'day');
    if (a < 2629800) return rtf.format(Math.round(diffSec / 604800), 'week');
    if (a < 31557600) return rtf.format(Math.round(diffSec / 2629800), 'month');
    return rtf.format(Math.round(diffSec / 31557600), 'year');
}

export function toEpochMs(mtime) {
    if (mtime == null) return null;
    if (typeof mtime === 'number' && Number.isFinite(mtime)) {
        return mtime < 1e12 ? Math.round(mtime * 1000) : Math.round(mtime);
    }
    if (typeof mtime === 'string') {
        const p = Date.parse(mtime.includes('T') ? mtime : mtime.replace(/-/g, '/'));
        return Number.isFinite(p) ? p : null;
    }
    return null;
}

export function docUpdatedMs(doc) {
    if (!doc) return null;
    const m = doc.mtime;
    if (m != null && Number(m) > 0) {
        const n = Number(m);
        return n < 1e12 ? Math.round(n * 1000) : Math.round(n);
    }
    return toEpochMs(doc.uploaded_at);
}
