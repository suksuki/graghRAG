/**
 * @param {number | null | undefined} bytes
 * @param {(key: string, opts?: object) => string} t i18n t()
 */
export function formatFileSize(bytes, t) {
    if (bytes == null || typeof bytes !== 'number' || bytes < 0 || !Number.isFinite(bytes)) {
        return '';
    }
    if (bytes < 1024) return `${bytes} ${t('unit_bytes')}`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} ${t('unit_kb')}`;
    return `${(bytes / 1048576).toFixed(1)} ${t('unit_mb')}`;
}
