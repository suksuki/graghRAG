import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import axios from 'axios';
import { Activity, RefreshCw, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import './IngestionMonitor.css';

const LAST_UPLOAD_KEY = 'graphrag_last_upload';

/**
 * 文档中心内嵌：轮询 GET /ingestion/status，解释「上传 ≠ 加工完成」+ 健康度一句话。
 */
export default function IngestionMonitor() {
    const { t, i18n } = useTranslation();
    const [st, setSt] = useState({});
    const [loading, setLoading] = useState(true);
    const [lastUpload, setLastUpload] = useState(null);

    const readLastUpload = useCallback(() => {
        try {
            const raw = localStorage.getItem(LAST_UPLOAD_KEY);
            setLastUpload(raw ? JSON.parse(raw) : null);
        } catch {
            setLastUpload(null);
        }
    }, []);

    const load = useCallback(async () => {
        try {
            const r = await axios.get('/api/ingestion/status');
            setSt(r.data || {});
        } catch {
            setSt({ status: 'unknown', health: 'failed' });
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        readLastUpload();
        load();
        const id = setInterval(load, 4000);
        const onUploadEvt = () => readLastUpload();
        window.addEventListener('graphrag_last_upload_changed', onUploadEvt);
        return () => {
            clearInterval(id);
            window.removeEventListener('graphrag_last_upload_changed', onUploadEvt);
        };
    }, [load, readLastUpload]);

    const onRefresh = () => {
        setLoading(true);
        load();
        readLastUpload();
        try {
            window.dispatchEvent(new Event('graphrag_refetch_docs'));
        } catch (_) {
            /* ignore */
        }
    };

    const rawStatus = st.status || 'idle';
    const health = st.health || 'ok';
    const isProcessing = rawStatus === 'processing';
    const isFailed = rawStatus === 'failed';
    const graphPct =
        st.graph_total > 0 ? Math.round(((st.graph_done || 0) * 100) / st.graph_total) : 0;

    const lastUploadText = useMemo(() => {
        if (!lastUpload?.at) return null;
        let time = '';
        try {
            time = new Date(lastUpload.at).toLocaleString(i18n.language || 'zh', {
                dateStyle: 'short',
                timeStyle: 'short',
            });
        } catch {
            time = String(lastUpload.at);
        }
        const modeKey =
            lastUpload.ingestion_mode === 'inline'
                ? 'ingestion_last_upload_mode_inline'
                : lastUpload.ingestion_mode === 'celery'
                  ? 'ingestion_last_upload_mode_celery'
                  : 'ingestion_last_upload_mode_unknown';
        const files = Array.isArray(lastUpload.files) ? lastUpload.files.filter(Boolean) : [];
        const fileStr = files.length ? files.slice(0, 4).join(', ') + (files.length > 4 ? '…' : '') : '—';
        const stu = lastUpload.status;
        const mode = t(modeKey);
        if (stu === 'completed') {
            return t('ingestion_last_upload_done', { time, mode, files: fileStr });
        }
        if (stu === 'queued') {
            return t('ingestion_last_upload_queued', { time, mode, files: fileStr });
        }
        if (stu === 'failed') {
            return t('ingestion_last_upload_failed', { time, mode, files: fileStr });
        }
        return t('ingestion_last_upload_unknown', { time, mode, files: fileStr });
    }, [lastUpload, t, i18n.language]);

    const healthIcon =
        health === 'ok' ? (
            <CheckCircle2 size={20} aria-hidden />
        ) : health === 'stalled' || health === 'failed' ? (
            <AlertCircle size={20} aria-hidden />
        ) : (
            <Loader2 className="spin" size={20} aria-hidden />
        );

    return (
        <section className="ingestion-monitor" aria-label={t('ingestion_monitor_title')}>
            <div className={`ingestion-monitor__health ingestion-monitor__health--${health}`}>
                {healthIcon}
                <p className="ingestion-monitor__health-text">{t(`ingestion_health_summary_${health}`)}</p>
            </div>

            {(health === 'stalled' || health === 'failed') && (
                <div className={`ingestion-monitor__health-guide ingestion-monitor__health-guide--${health}`}>
                    <p className="ingestion-monitor__health-guide-title">{t('ingestion_health_guide_title')}</p>
                    <ul className="ingestion-monitor__health-guide-list">
                        {health === 'stalled' ? (
                            <>
                                <li>{t('ingestion_health_guide_stalled_1')}</li>
                                <li>{t('ingestion_health_guide_stalled_2')}</li>
                            </>
                        ) : (
                            <>
                                <li>{t('ingestion_health_guide_failed_1')}</li>
                                <li>{t('ingestion_health_guide_failed_2')}</li>
                            </>
                        )}
                    </ul>
                </div>
            )}

            {lastUploadText ? (
                <div className="ingestion-monitor__last-upload">
                    <span className="ingestion-monitor__last-upload-label">{t('ingestion_last_upload_title')}</span>
                    <span className="ingestion-monitor__last-upload-body">{lastUploadText}</span>
                </div>
            ) : null}

            <div className="ingestion-monitor__head">
                <div className="ingestion-monitor__title-row">
                    <Activity size={18} className={isProcessing ? 'ingestion-monitor__icon--pulse' : ''} aria-hidden />
                    <h2 className="ingestion-monitor__title">{t('ingestion_monitor_title')}</h2>
                </div>
                <button type="button" className="ingestion-monitor__refresh" onClick={onRefresh} disabled={loading}>
                    {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                    {t('ingestion_monitor_refresh')}
                </button>
            </div>
            <p className="ingestion-monitor__subtitle">{t('ingestion_monitor_subtitle')}</p>

            <ol className="ingestion-monitor__pipeline">
                <li>{t('ingestion_monitor_step_1')}</li>
                <li>{t('ingestion_monitor_step_2')}</li>
                <li>{t('ingestion_monitor_step_3')}</li>
                <li>{t('ingestion_monitor_step_4')}</li>
            </ol>

            <div
                className={`ingestion-monitor__badge ingestion-monitor__badge--${isFailed ? 'failed' : isProcessing ? 'processing' : 'idle'}`}
                role="status"
            >
                {isFailed ? <AlertCircle size={16} aria-hidden /> : null}
                {isProcessing ? <Loader2 className="spin" size={16} aria-hidden /> : null}
                <span>
                    {t('ingestion_monitor_state_label')}:{' '}
                    {isProcessing
                        ? t('ingestion_monitor_state_processing')
                        : isFailed
                          ? t('ingestion_monitor_state_failed')
                          : rawStatus === 'unknown'
                            ? t('ingestion_monitor_state_unknown')
                            : t('ingestion_monitor_state_idle')}
                </span>
            </div>

            {(st.message || isFailed) && (
                <p className={`ingestion-monitor__message ${isFailed ? 'ingestion-monitor__message--error' : ''}`}>
                    {st.message || t('ingestion_failed_retry')}
                </p>
            )}

            {isProcessing && (
                <>
                    <div className="ingestion-monitor__progress-wrap">
                        <div className="ingestion-monitor__progress-bar">
                            <div className="ingestion-monitor__progress-fill" style={{ width: `${st.progress || 0}%` }} />
                        </div>
                        <span className="ingestion-monitor__progress-pct">{st.progress || 0}%</span>
                    </div>
                    {(st.file_names?.length > 0 || st.files_in_batch > 0) && (
                        <p className="ingestion-monitor__files">
                            {t('files_in_batch')}: {st.files_in_batch || st.file_names?.length || 0}
                            {st.file_names?.length > 0 && st.file_names.length <= 5
                                ? ` · ${st.file_names.join(', ')}`
                                : null}
                        </p>
                    )}
                    {st.graph_total > 0 && (
                        <p className="ingestion-monitor__graph">
                            {t('graph_chunks_progress')}: {st.graph_done || 0}/{st.graph_total} {t('chunks_unit')} ·{' '}
                            {graphPct}%
                        </p>
                    )}
                </>
            )}

            <dl className="ingestion-monitor__stats">
                <div>
                    <dt>{t('ingestion_monitor_stat_eligible')}</dt>
                    <dd>{st.eligible_file_count ?? '—'}</dd>
                </div>
                <div>
                    <dt>{t('ingestion_monitor_stat_vectors')}</dt>
                    <dd>{st.vector_chunk_count != null ? st.vector_chunk_count : '—'}</dd>
                </div>
                <div>
                    <dt>{t('ingestion_monitor_stat_nodes')}</dt>
                    <dd>{st.node_count ?? '—'}</dd>
                </div>
            </dl>
            <p className="ingestion-monitor__stat-note">{t('ingestion_monitor_node_note')}</p>

            <div className="ingestion-monitor__tips">
                <p className="ingestion-monitor__tip-title">{t('ingestion_monitor_tips_title')}</p>
                <ul>
                    <li>{t('ingestion_monitor_tip_inline')}</li>
                    <li>{t('ingestion_monitor_tip_celery')}</li>
                    <li>{t('ingestion_monitor_tip_empty_ui')}</li>
                </ul>
            </div>
        </section>
    );
}
