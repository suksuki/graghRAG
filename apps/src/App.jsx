import React, { useState, useEffect, useRef } from 'react';
import { Send, Upload, Share2, Database, Network, Search, FileText, Image as ImageIcon, CheckCircle, Loader2, Languages, Trash2, Settings as SettingsIcon, Activity, Zap, Clock, User } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import axios from 'axios';
import './App.css';
import GraphExplorer from './pages/GraphExplorer.jsx';

const App = () => {
    const { t, i18n } = useTranslation();
    const [activeTab, setActiveTab] = useState('chat'); // chat, graph, docs, settings
    const [query, setQuery] = useState('');
    const [queryMode, setQueryMode] = useState('vector'); // vector | graph | hybrid
    const [messages, setMessages] = useState([{ role: 'assistant', text: t('welcome') }]);
    const [loading, setLoading] = useState(false);

    // Data States
    const [documents, setDocuments] = useState([]);
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [ingestionStatus, setIngestionStatus] = useState({ status: 'idle', node_count: 0 });
    const [appSettings, setAppSettings] = useState({});
    const [availableModels, setAvailableModels] = useState([]);
    const [testResult, setTestResult] = useState({ type: null, msg: '' });
    const [saveStatus, setSaveStatus] = useState(null);
    const [expandedGraph, setExpandedGraph] = useState({});
    const [errorModal, setErrorModal] = useState(null);

    const chatEndRef = useRef(null);

    const triggerFollowupEntityQuery = (entity) => {
        try {
            localStorage.setItem('graphrag_suggested_question', t('followup_entity_query', { entity }));
        } catch (e) { }
        window.scrollTo(0, 0);
        window.dispatchEvent(new CustomEvent('graphrag_open_chat'));
    };

    const hasGraphDataMsg = (msg) => (
        ((msg?.graph?.relations?.length ?? 0) > 0) ||
        ((msg?.graph?.summary?.length ?? 0) > 0) ||
        ((msg?.graph?.two_hop?.length ?? 0) > 0) ||
        ((msg?.debug?.graph_relations_count ?? 0) > 0)
    );

    const getErrorUI = (code) => {
        switch (code) {
            case 'FILE_TOO_LARGE':
                return {
                    icon: '📦',
                    title: t('error_ui_file_too_large_title'),
                    color: '#60a5fa',
                    bg: 'rgba(59,130,246,0.14)',
                    border: 'rgba(96,165,250,0.35)',
                };
            case 'UNSUPPORTED_FILE_TYPE':
                return {
                    icon: '📄',
                    title: t('error_ui_unsupported_type_title'),
                    color: '#f59e0b',
                    bg: 'rgba(245,158,11,0.14)',
                    border: 'rgba(251,191,36,0.35)',
                };
            default:
                return {
                    icon: '⚠️',
                    title: t('error_ui_system_title'),
                    color: '#f87171',
                    bg: 'rgba(248,113,113,0.14)',
                    border: 'rgba(248,113,113,0.35)',
                };
        }
    };

    const openErrorModal = (errorObj) => {
        if (!errorObj) return;
        const code = errorObj.code || 'UNKNOWN_ERROR';
        const ui = getErrorUI(code);
        setErrorModal({
            code,
            icon: ui.icon,
            title: ui.title,
            color: ui.color,
            bg: ui.bg,
            border: ui.border,
            message: errorObj.message || (t('upload_failed') || '操作失败'),
            detail: errorObj.detail || '',
            suggestion: errorObj.suggestion || '',
        });
    };

    useEffect(() => {
        fetchAppSettings(); // Initial Load
        const timer = setInterval(fetchIngestionStatus, 1500); // 处理中时进度更跟手

        const handleKeyPress = (e) => {
            if (e.altKey && e.key.toLowerCase() === 'l') {
                const languages = ['zh', 'en', 'ko'];
                const nextIdx = (languages.indexOf(i18n.language) + 1) % languages.length;
                i18n.changeLanguage(languages[nextIdx]);
            }
        };
        window.addEventListener('keydown', handleKeyPress);
        const openChat = () => setActiveTab('chat');
        window.addEventListener('graphrag_open_chat', openChat);

        return () => {
            clearInterval(timer);
            window.removeEventListener('keydown', handleKeyPress);
            window.removeEventListener('graphrag_open_chat', openChat);
        };
    }, [i18n.language]);

    useEffect(() => {
        if (activeTab === 'docs') fetchDocuments();
        if (activeTab === 'graph') fetchGraphData();
        if (activeTab === 'settings') {
            fetchAppSettings();
            fetchAvailableModels();
        }
    }, [activeTab]);

    const fetchIngestionStatus = async () => {
        try {
            const res = await axios.get('/api/ingestion/status');
            setIngestionStatus(res.data);
        } catch (e) {
            setIngestionStatus(prev => ({
                ...prev,
                status: 'failed',
                message: t('ingestion_status_fetch_failed'),
            }));
        }
    };

    const fetchDocuments = async () => {
        try {
            const res = await axios.get('/api/documents');
            setDocuments(res.data);
        } catch (e) { }
    };

    const fetchGraphData = async () => {
        try {
            const res = await axios.get('/api/graph/data');
            setGraphData(res.data);
        } catch (e) { }
    };

    const fetchAppSettings = async () => {
        try {
            const res = await axios.get('/api/settings');
            setAppSettings(res.data);
        } catch (e) { }
    };

    const fetchAvailableModels = async (customUrl) => {
        try {
            const url = customUrl || appSettings.ollama_base_url;
            const res = await axios.get(`/api/ollama/models?url=${encodeURIComponent(url)}`);
            setAvailableModels(res.data.models);
        } catch (e) { }
    };

    const updateSetting = async (key, val) => {
        setAppSettings(prev => ({ ...prev, [key]: val }));
    };

    const saveSettings = async () => {
        setSaveStatus(t('saving'));
        try {
            await axios.post('/api/settings/update', {
                llm_model: appSettings.llm_model,
                extraction_model: appSettings.extraction_model,
                embedding_model: appSettings.embedding_model,
                ollama_base_url: appSettings.ollama_base_url
            });
            setSaveStatus(t('settings_saved'));
            fetchAppSettings();
            setTimeout(() => setSaveStatus(null), 3000);
        } catch (e) {
            setSaveStatus(t('settings_save_failed'));
        }
    };

    const testConnection = async (type) => {
        setTestResult({ type, msg: t('testing') });
        try {
            const payload = {
                type,
                url: type === 'llm' ? appSettings.ollama_base_url : null
            };
            const res = await axios.post('/api/settings/test', payload);
            setTestResult({ type, msg: res.data.message, success: res.data.status === 'success' });
            // If LLM test succeeds, refresh available models for that new URL
            if (type === 'llm' && res.data.status === 'success') {
                fetchAvailableModels(appSettings.ollama_base_url);
            }
        } catch (e) {
            setTestResult({ type, msg: t('connection_failed'), success: false });
        }
    };

    const submitQuery = async (inputQuery) => {
        const userQuery = (inputQuery || '').trim();
        if (!userQuery || loading) return;
        setMessages(prev => [...prev, { role: 'user', text: userQuery }]);
        setQuery('');
        setLoading(true);
        try {
            const res = await fetch('/api/query/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-lang': i18n.language || 'zh' },
                body: JSON.stringify({ query: userQuery, mode: queryMode }),
            });
            if (!res.ok) throw new Error(res.statusText);
            const assistantId = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
            setMessages(prev => [...prev, { id: assistantId, role: 'assistant', text: '', sources: null, pipeline_latency_ms: null, suggestions: [] }]);
            const reader = res.body.getReader();
            const dec = new TextDecoder();
            let buffer = '';
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += dec.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const event = JSON.parse(line);
                        if (event.type === 'chunk' && event.text && !event.thinking) {
                            setMessages(prev => {
                                const next = [...prev];
                                const last = next[next.length - 1];
                                if (last && last.role === 'assistant') next[next.length - 1] = { ...last, text: (last.text || '') + event.text };
                                return next;
                            });
                        } else if (event.type === 'done') {
                            const lat = event.pipeline_latency_ms || {};
                            if (event.first_token_ms != null) lat.first_token_ms = event.first_token_ms;
                            if (event.total_ms != null) lat.total_ms = event.total_ms;
                            const finalLang = event.lang_final || i18n.language || 'zh';
                            const normalizedGraph = {
                                relations: Array.isArray(event.graph?.relations) ? event.graph.relations : [],
                                summary: typeof event.graph?.summary === 'string' ? event.graph.summary : '',
                                two_hop: Array.isArray(event.graph?.two_hop) ? event.graph.two_hop : [],
                                count: Number(event.graph?.count ?? (Array.isArray(event.graph?.relations) ? event.graph.relations.length : 0)),
                                used: Boolean(event.graph?.used),
                            };
                            const rel0 = normalizedGraph.relations[0] || null;
                            const entity = rel0?.source || event.debug?.entity_used_for_graph || null;
                            console.log("GRAPH UI DATA:", normalizedGraph);
                            setMessages(prev => {
                                const next = [...prev];
                                const last = next[next.length - 1];
                                if (last && last.role === 'assistant') next[next.length - 1] = {
                                    ...last,
                                    text: event.answer ?? last.text,
                                    sources: event.sources ?? last.sources,
                                    pipeline_latency_ms: lat,
                                    graph: normalizedGraph,
                                    debug: event.debug ?? null,
                                    lang_ui: event.lang_ui || i18n.language || 'zh',
                                    lang_detected: event.lang_detected || finalLang,
                                    lang_final: finalLang,
                                    suggest_switch: Boolean(event.suggest_switch),
                                };
                                return next;
                            });
                            if (entity) {
                                try {
                                    const sres = await fetch(`/api/graph/suggestions?entity=${encodeURIComponent(entity)}`, {
                                        headers: { 'x-lang': finalLang },
                                    });
                                    if (sres.ok) {
                                        const sdata = await sres.json();
                                        const qs = Array.isArray(sdata?.questions) ? sdata.questions : [];
                                        setMessages(prev => prev.map(m => (m?.id === assistantId ? { ...m, suggestions: qs } : m)));
                                    }
                                } catch (_) { }
                            }
                        } else if (event.type === 'error') {
                            openErrorModal(event.error || { message: event.detail || t('error_query') });
                            setMessages(prev => {
                                const next = [...prev];
                                const last = next[next.length - 1];
                                if (last && last.role === 'assistant') next[next.length - 1] = { ...last, text: (last.text || '') + '\n[错误] ' + (event.detail || '') };
                                return next;
                            });
                        }
                    } catch (_) { /* skip malformed line */ }
                }
            }
        } catch (e) {
            openErrorModal(e?.response?.data?.error || { message: t('error_query'), detail: e.message || '' });
            setMessages(prev => [...prev, { role: 'assistant', text: t('error_query') + ' ' + (e.message || '') }]);
        } finally { setLoading(false); }
    };

    const handleQuery = async (e) => {
        e.preventDefault();
        await submitQuery(query);
    };

    // 当从 Graph Studio 选择推荐问题时，自动填充并发送
    useEffect(() => {
        if (activeTab !== 'chat') return;
        try {
            const stored = localStorage.getItem('graphrag_suggested_question');
            if (stored && stored.trim()) {
                setQuery(stored);
                localStorage.removeItem('graphrag_suggested_question');
                setTimeout(() => {
                    submitQuery(stored);
                }, 0);
            }
        } catch (e) { }
    }, [activeTab]);

    const deleteDocument = async (name) => {
        if (!window.confirm(t('delete_confirm', { name }))) return;
        try {
            await axios.delete(`/api/documents/${encodeURIComponent(name)}`);
            fetchDocuments(); // Refresh list
        } catch (e) {
            openErrorModal(e?.response?.data?.error || { message: t('delete_failed'), detail: e.response?.data?.detail || e.message });
        }
    };

    const formatSize = (bytes) => {
        if (bytes < 1024) return `${bytes} ${t('unit_bytes')}`;
        if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} ${t('unit_kb')}`;
        return `${(bytes / 1048576).toFixed(1)} ${t('unit_mb')}`;
    };

    const [isUploading, setIsUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [lastUploadedFiles, setLastUploadedFiles] = useState([]);
    const [uploadJobs, setUploadJobs] = useState([]);
    const graphProgressPct = (ingestionStatus.graph_total > 0)
        ? Math.round(((ingestionStatus.graph_done || 0) * 100) / ingestionStatus.graph_total)
        : 0;
    const handleFileUpload = async (e) => {
        const files = e.target.files;
        if (!files.length) return;
        const MAX_FILE_SIZE = 50 * 1024 * 1024;
        const ALLOWED = ['.pdf', '.docx', '.doc', '.pptx', '.xlsx', '.txt', '.md', '.html', '.jpg', '.png', '.jpeg', '.xdmp'];
        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const ext = (f.name.slice(f.name.lastIndexOf('.')) || '').toLowerCase();
            if (!ALLOWED.includes(ext)) {
                openErrorModal({
                    code: 'UNSUPPORTED_FILE_TYPE',
                    message: t('unsupported_file_type_message'),
                    detail: t('upload_file_detail', { name: f.name }),
                    suggestion: t('unsupported_file_type_suggestion'),
                });
                return;
            }
            if (f.size > MAX_FILE_SIZE) {
                openErrorModal({
                    code: 'FILE_TOO_LARGE',
                    message: t('file_too_large_message', { size: 50 }),
                    detail: t('upload_file_size_detail', { name: f.name, size: formatSize(f.size) }),
                    suggestion: t('file_too_large_suggestion'),
                });
                return;
            }
        }
        setIsUploading(true);
        setUploadProgress(0);
        setLastUploadedFiles([]);
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) formData.append('files', files[i]);
        try {
            const res = await axios.post('/api/upload', formData, {
                headers: { 'x-lang': i18n.language || 'zh' },
                onUploadProgress: (progressEvent) => {
                    const percentCompleted = progressEvent.total
                        ? Math.round((progressEvent.loaded * 100) / progressEvent.total)
                        : 0;
                    setUploadProgress(percentCompleted);
                }
            });
            const names = res.data?.files || [];
            const jobs = res.data?.jobs || [];
            setLastUploadedFiles(names);
            setUploadJobs(jobs);
            fetchIngestionStatus();
            if (names.length > 0) setTimeout(() => setLastUploadedFiles([]), 8000);
        } catch (e) {
            openErrorModal(e?.response?.data?.error || { message: t('upload_failed'), detail: e?.response?.data?.detail || e?.message || t('unknown_error') });
        } finally {
            setIsUploading(false);
            setUploadProgress(0);
        }
    };

    useEffect(() => {
        if (!uploadJobs.length) return;
        let stopped = false;
        const timer = setInterval(async () => {
            try {
                const statuses = await Promise.all(
                    uploadJobs.map(async (j) => {
                        const r = await axios.get(`/api/ingest/status?job_id=${encodeURIComponent(j.job_id)}`);
                        return { ...j, ...r.data };
                    })
                );
                if (stopped) return;
                setUploadJobs(statuses);
                const failed = statuses.find(s => s.status === 'failed');
                if (failed) {
                    setIngestionStatus(prev => ({
                        ...prev,
                        status: 'failed',
                        message: failed?.error?.message || t('upload_processing_failed'),
                    }));
                    openErrorModal(failed.error || { message: t('upload_processing_failed'), detail: t('unknown_error') });
                }
                const allDone = statuses.every(s => s.status === 'done' || s.status === 'failed');
                if (allDone) {
                    clearInterval(timer);
                    fetchDocuments();
                    fetchIngestionStatus();
                }
            } catch (e) {
                setIngestionStatus(prev => ({
                    ...prev,
                    status: 'failed',
                    message: e?.response?.data?.detail || e?.message || t('polling_status_failed'),
                }));
                openErrorModal(e?.response?.data?.error || { message: t('polling_status_failed'), detail: e?.message || '' });
            }
        }, 1500);
        return () => { stopped = true; clearInterval(timer); };
    }, [uploadJobs.length]);

    return (
        <div className="app-container">
            <aside className="sidebar glass">
                <div className="logo-section">
                    <Share2 size={32} className="logo-icon" />
                    <h1 className="logo-text">GraphRAG<span> Platform</span></h1>
                </div>

                <div className="lang-switcher glass" style={{ marginBottom: '16px', padding: '8px 12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', opacity: 0.8 }}>
                        <Languages size={14} />
                        <select 
                            value={i18n.language} 
                            onChange={(e) => i18n.changeLanguage(e.target.value)}
                            style={{ background: 'transparent', border: 'none', color: 'inherit', outline: 'none', cursor: 'pointer' }}
                        >
                            <option value="zh">简体中文 (Alt+L)</option>
                            <option value="en">English (Alt+L)</option>
                            <option value="ko">한국어 (Alt+L)</option>
                        </select>
                    </div>
                </div>

                <nav className="nav-menu">
                    <div className={`nav-item ${activeTab === 'chat' ? 'active' : ''}`} onClick={() => setActiveTab('chat')}>
                        <Database size={18} /><span>{t('knowledge_base')}</span>
                    </div>
                    <div className={`nav-item ${activeTab === 'graph' ? 'active' : ''}`} onClick={() => setActiveTab('graph')}>
                        <Network size={18} /><span>{t('graph_overview')}</span>
                    </div>
                    <div className={`nav-item ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>
                        <FileText size={18} /><span>{t('doc_management')}</span>
                    </div>
                    <div className={`nav-item ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => setActiveTab('settings')}>
                        <SettingsIcon size={18} /><span>{t('system_settings')}</span>
                    </div>
                </nav>

                <div className="ingestion-indicator glass">
                    <div className="indicator-header">
                        <Activity size={14} className={ingestionStatus.status === 'processing' ? 'pulse' : ''} />
                        <span>
                            {t('ingestion_status')}: {
                                ingestionStatus.status === 'processing'
                                    ? (ingestionStatus.message || t('analyzing'))
                                    : ingestionStatus.status === 'failed'
                                        ? (ingestionStatus.message || t('ingestion_failed'))
                                        : t('idle')
                            }
                        </span>
                    </div>
                    {ingestionStatus.status === 'processing' && (
                        <>
                            {(ingestionStatus.files_in_batch > 0 || (ingestionStatus.file_names && ingestionStatus.file_names.length > 0)) && (
                                <div className="indicator-stat" style={{ marginTop: '6px', fontSize: '11px', color: '#64748b', lineHeight: 1.3 }}>
                                    {t('files_in_batch')}: {ingestionStatus.files_in_batch || ingestionStatus.file_names?.length || 0}
                                    {ingestionStatus.file_names?.length > 0 && ingestionStatus.file_names.length <= 4 && (
                                        <span style={{ marginLeft: '4px', opacity: 0.9 }}>
                                            {ingestionStatus.file_names.join(', ')}
                                        </span>
                                    )}
                                    {ingestionStatus.file_names?.length > 4 && (
                                        <span style={{ marginLeft: '4px', opacity: 0.9 }}>
                                            {ingestionStatus.file_names.slice(0, 2).join(', ')} {t('and_n_more', { n: ingestionStatus.file_names.length - 2 })}
                                        </span>
                                    )}
                                </div>
                            )}
                            <div className="progress-bar-container" style={{ marginTop: '6px', background: '#e2e8f0', height: '8px', borderRadius: '4px', overflow: 'hidden' }}>
                                <div className="progress-bar-fill" style={{ width: `${ingestionStatus.progress || 0}%`, background: '#6366f1', height: '100%', transition: 'width 0.4s ease-out' }}></div>
                            </div>
                            {ingestionStatus.graph_total > 0 && (
                                <div className="indicator-stat" style={{ marginTop: '4px', fontSize: '12px', color: '#64748b' }}>
                                    {t('graph_chunks_progress')}: {ingestionStatus.graph_done || 0}/{ingestionStatus.graph_total} {t('chunks_unit')} · {graphProgressPct}%
                                </div>
                            )}
                        </>
                    )}
                    {ingestionStatus.status === 'failed' && (
                        <div style={{ marginTop: '8px', fontSize: '12px', color: '#fca5a5', lineHeight: 1.4 }}>
                            ❌ {ingestionStatus.message || t('ingestion_failed_retry')}
                        </div>
                    )}
                    {lastUploadedFiles.length > 0 && (
                        <div className="indicator-stat" style={{ marginTop: '6px', fontSize: '11px', color: '#22c55e' }}>
                            {lastUploadedFiles.length === 1
                                ? t('upload_success') + ': ' + lastUploadedFiles[0]
                                : t('upload_success_multi', { count: lastUploadedFiles.length }) + ': ' + lastUploadedFiles.slice(0, 3).join(', ') + (lastUploadedFiles.length > 3 ? ' …' : '')}
                        </div>
                    )}
                    <div className="indicator-stat" style={{ marginTop: '8px' }}>
                        {t('record_count')}: {ingestionStatus.node_count ?? 0}{t('entities_unit') ? ` ${t('entities_unit')}` : ''}
                    </div>
                </div>

                <div className="upload-section">
                    <label className="upload-btn">
                        {isUploading ? (
                            <>
                                <Loader2 className="spin" size={18} />
                                <span style={{ marginLeft: '8px', fontSize: '12px' }}>{uploadProgress}%</span>
                            </>
                        ) : (
                            <>
                                <Upload size={18} />
                                <span>{t('upload')}</span>
                            </>
                        )}
                        <input type="file" multiple hidden onChange={(e) => { handleFileUpload(e); e.target.value = null; }} />
                    </label>
                </div>
            </aside>

            <main className="chat-area">
                {errorModal && (
                    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
                        <div className="glass" style={{ width: 'min(560px, 92vw)', padding: '18px', borderRadius: '14px' }}>
                            <div style={{ fontWeight: 700, fontSize: '18px', marginBottom: '10px', color: errorModal.color, display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span>{errorModal.icon}</span>
                                <span>{errorModal.title || t('upload_failed_title')}</span>
                            </div>
                            <div style={{ fontSize: '14px', marginBottom: '10px' }}>{errorModal.message}</div>
                            {errorModal.detail ? (
                                <details style={{ marginBottom: '10px', fontSize: '12px', opacity: 0.9 }}>
                                    <summary>{t('view_detail') || '查看详情'}</summary>
                                    <div style={{ marginTop: '8px', whiteSpace: 'pre-wrap' }}>{errorModal.detail}</div>
                                </details>
                            ) : null}
                            {errorModal.suggestion ? (
                                <div style={{ marginBottom: '14px', padding: '8px 10px', borderRadius: '8px', background: errorModal.bg, border: `1px solid ${errorModal.border}` }}>
                                    💡 {errorModal.suggestion}
                                </div>
                            ) : null}
                            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                <button type="button" onClick={() => setErrorModal(null)} style={{ padding: '6px 12px', borderRadius: '8px', border: '1px solid rgba(148,163,184,0.5)', background: 'transparent', color: 'inherit' }}>
                                    {t('close') || '关闭'}
                                </button>
                            </div>
                        </div>
                    </div>
                )}
                <div className="content-viewport">
                    {activeTab === 'chat' && (
                        <div className="chat-layout">
                            <section className="messages-container">
                                {messages.map((msg, i) => (
                                    <div key={i} className={`message-wrapper ${msg.role}`}>
                                        <div className={`message-bubble ${msg.role === 'user' ? 'primary' : 'glass'}`}>
                                            {msg.role === 'assistant' && (
                                                <>
                                                <div style={{ marginBottom: '8px', fontSize: '12px', opacity: 0.9 }}>
                                                    {hasGraphDataMsg(msg)
                                                        ? t('answer_powered_by_graph')
                                                        : t('answer_based_on_text_only')}
                                                </div>
                                                </>
                                            )}
                                            <div>{msg.text}</div>
                                            {msg.role === 'assistant' && Array.isArray(msg.suggestions) && msg.suggestions.length > 0 && (
                                                <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                                                    <div style={{ fontWeight: 600, fontSize: '12px', marginBottom: '6px' }}>{t('suggested_questions_title')}</div>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
                                                        {msg.suggestions.slice(0, 6).map((q, qidx) => (
                                                            <button
                                                                key={qidx}
                                                                type="button"
                                                                onClick={() => {
                                                                    setQuery(q);
                                                                    setTimeout(() => submitQuery(q), 0);
                                                                }}
                                                                style={{
                                                                    textAlign: 'left',
                                                                    background: 'rgba(99,102,241,0.10)',
                                                                    border: '1px solid rgba(99,102,241,0.25)',
                                                                    color: 'inherit',
                                                                    borderRadius: '10px',
                                                                    padding: '8px 10px',
                                                                    cursor: 'pointer',
                                                                    opacity: 0.95,
                                                                }}
                                                            >
                                                                {q}
                                                            </button>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {msg.role === 'assistant' && msg.graph && (
                                                <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                                                    {(() => {
                                                        const hasGraphData = hasGraphDataMsg(msg);

                                                        if (!hasGraphData) {
                                                            return (
                                                                <div style={{ fontSize: '12px', opacity: 0.85 }}>
                                                                    {t('no_structured_knowledge')}
                                                                    <div style={{ marginTop: '6px', opacity: 0.8 }}>
                                                                        {t('try_specific_questions')}
                                                                    </div>
                                                                </div>
                                                            );
                                                        }

                                                        return (
                                                            <>
                                                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                                                                    <div style={{ fontWeight: 600, fontSize: '12px' }}>{t('knowledge_graph_title')}</div>
                                                                    {Array.isArray(msg.graph?.relations) && msg.graph.relations.length > 8 && (
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => setExpandedGraph(prev => ({ ...prev, [i]: !prev[i] }))}
                                                                            style={{ background: 'transparent', border: '1px solid rgba(148,163,184,0.4)', color: 'inherit', borderRadius: '8px', padding: '2px 8px', fontSize: '11px', cursor: 'pointer', opacity: 0.9 }}
                                                                        >
                                                                            {expandedGraph[i] ? t('collapse') : t('expand')}
                                                                        </button>
                                                                    )}
                                                                </div>

                                                                {msg.graph?.summary && (
                                                                    <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '12px' }}>
                                                                        <div style={{ fontWeight: 600, marginBottom: '4px' }}>{t('key_insight_title')}</div>
                                                                        <div style={{ opacity: 0.9 }}>{msg.graph.summary}</div>
                                                                    </div>
                                                                )}

                                                                {Array.isArray(msg.graph?.two_hop) && msg.graph.two_hop.length > 0 && (
                                                                    <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '12px' }}>
                                                                        <div style={{ fontWeight: 600, marginBottom: '6px' }}>{t('two_hop_title')}</div>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                                            {msg.graph.two_hop.slice(0, 6).map((row, ridx) => (
                                                                                <div key={ridx} style={{ opacity: 0.9 }}>
                                                                                    <span style={{ fontWeight: 600 }}>{row?.product || ''}</span>
                                                                                    {Array.isArray(row?.domains) && row.domains.length > 0 && (
                                                                                        <span style={{ opacity: 0.8 }}> → {row.domains.slice(0, 6).join(', ')}</span>
                                                                                    )}
                                                                                </div>
                                                                            ))}
                                                                        </div>
                                                                    </div>
                                                                )}

                                                                {(() => {
                                                                    const rels = Array.isArray(msg.graph?.relations) ? msg.graph.relations : [];
                                                                    const provides = rels.filter(r => (r?.relation || '').toUpperCase() === 'PROVIDES').map(r => r?.target).filter(Boolean);
                                                                    const applies = rels.filter(r => (r?.relation || '').toUpperCase() === 'APPLIES_TO').map(r => r?.target).filter(Boolean);
                                                                    const products = [...new Set(provides)].slice(0, 8);
                                                                    const industries = [...new Set(applies)].slice(0, 8);
                                                                    const hasGroups = products.length > 0 || industries.length > 0;

                                                                    if (!hasGroups) return null;

                                                                    return (
                                                                        <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '12px' }}>
                                                                            {products.length > 0 && (
                                                                                <div style={{ marginBottom: '10px' }}>
                                                                                    <div style={{ fontWeight: 600, marginBottom: '6px' }}>{t('products_title')}</div>
                                                                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                                                                        {products.map((p, pidx) => (
                                                                                            <span
                                                                                                key={pidx}
                                                                                                onClick={() => p && triggerFollowupEntityQuery(p)}
                                                                                                style={{ cursor: p ? 'pointer' : 'default', background: 'rgba(99,102,241,0.14)', border: '1px solid rgba(99,102,241,0.25)', padding: '4px 10px', borderRadius: '999px', opacity: 0.95 }}
                                                                                            >
                                                                                                {p}
                                                                                            </span>
                                                                                        ))}
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                            {industries.length > 0 && (
                                                                                <div>
                                                                                    <div style={{ fontWeight: 600, marginBottom: '6px' }}>{t('industries_title')}</div>
                                                                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                                                                        {industries.map((d, didx) => (
                                                                                            <span
                                                                                                key={didx}
                                                                                                onClick={() => d && triggerFollowupEntityQuery(d)}
                                                                                                style={{ cursor: d ? 'pointer' : 'default', background: 'rgba(16,185,129,0.14)', border: '1px solid rgba(16,185,129,0.25)', padding: '4px 10px', borderRadius: '999px', opacity: 0.95 }}
                                                                                            >
                                                                                                {d}
                                                                                            </span>
                                                                                        ))}
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                    );
                                                                })()}

                                                                {Array.isArray(msg.graph?.relations) && msg.graph.relations.length > 0 && (
                                                                    <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                                                                        <div style={{ fontWeight: 600, fontSize: '12px', marginBottom: '6px' }}>{t('relations_title')}</div>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
                                                                            {(expandedGraph[i] ? msg.graph.relations : msg.graph.relations.slice(0, 8)).map((r, ridx) => (
                                                                                <div key={ridx} style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                                                                    <span
                                                                                        onClick={() => r?.source && triggerFollowupEntityQuery(r.source)}
                                                                                        style={{ cursor: r?.source ? 'pointer' : 'default', textDecoration: r?.source ? 'underline' : 'none', textUnderlineOffset: 2 }}
                                                                                    >
                                                                                        {r?.source || ''}
                                                                                    </span>
                                                                                    <span style={{ background: 'rgba(99,102,241,0.18)', border: '1px solid rgba(99,102,241,0.35)', color: '#a5b4fc', padding: '1px 8px', borderRadius: '999px', fontSize: '11px' }}>
                                                                                        {r?.relation || ''}
                                                                                    </span>
                                                                                    <span
                                                                                        onClick={() => r?.target && triggerFollowupEntityQuery(r.target)}
                                                                                        style={{ cursor: r?.target ? 'pointer' : 'default', textDecoration: r?.target ? 'underline' : 'none', textUnderlineOffset: 2, opacity: 0.95 }}
                                                                                    >
                                                                                        {r?.target || ''}
                                                                                    </span>
                                                                                </div>
                                                                            ))}
                                                                        </div>
                                                                    </div>
                                                                )}
                                                            </>
                                                        );
                                                    })()}
                                                </div>
                                            )}
                                            {msg.sources && msg.sources.length > 0 && (
                                                <div className="sources-container" style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.1)', fontSize: '12px' }}>
                                                    <div style={{ opacity: 0.6, marginBottom: '4px' }}>{t('knowledge_sources')}</div>
                                                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                                        {[...new Set(msg.sources.map(s => s.file))].map((file, idx) => (
                                                            <span key={idx} className="source-tag" style={{ background: 'rgba(99, 102, 241, 0.2)', padding: '2px 8px', borderRadius: '4px', color: '#818cf8' }}>
                                                                {file}
                                                            </span>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {msg.pipeline_latency_ms && (
                                                <div className="pipeline-latency" style={{ marginTop: '8px', paddingTop: '6px', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '11px', opacity: 0.85, fontFamily: 'monospace' }}>
                                                    ⏱ {[
                                                        msg.pipeline_latency_ms.first_token_ms != null && `${t('first_token_short')} ${(msg.pipeline_latency_ms.first_token_ms / 1000).toFixed(1)}s`,
                                                        `planner ${msg.pipeline_latency_ms.planner_ms ?? 0}ms`,
                                                        `vector ${msg.pipeline_latency_ms.vector_retrieval_ms ?? 0}ms`,
                                                        `graph ${msg.pipeline_latency_ms.graph_retrieval_ms ?? 0}ms`,
                                                        `LLM ${((msg.pipeline_latency_ms.llm_generation_ms ?? 0) / 1000).toFixed(1)}s`,
                                                        `${t('total_time_short')} ${((msg.pipeline_latency_ms.total_ms ?? 0) / 1000).toFixed(1)}s`,
                                                    ].filter(Boolean).join(' · ')}
                                                    {(msg.pipeline_latency_ms.prompt_chars != null || msg.pipeline_latency_ms.prompt_tokens != null) && (
                                                        <div style={{ marginTop: '4px', opacity: 0.75 }}>
                                                            {t('prompt_label')}: {msg.pipeline_latency_ms.prompt_chars ?? 0} {t('characters_unit')}{msg.pipeline_latency_ms.prompt_tokens != null ? ` · ~${msg.pipeline_latency_ms.prompt_tokens} ${t('tokens_unit')}` : ''}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                            {msg.role === 'assistant' && (
                                                <div style={{ marginTop: '6px', fontSize: '11px', opacity: 0.8, fontFamily: 'monospace' }}>
                                                    ⚡ {t('debug_context')}: {msg.debug?.context_tokens ?? 0}<br />
                                                    🧠 {t('debug_graph_relations')}: {msg.graph?.count ?? 0}<br />
                                                    📄 {t('debug_chunks_used')}: {msg.debug?.chunks_used ?? 0}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                                {loading && <div className="message-wrapper assistant"><div className="message-bubble glass typing"><span></span><span></span><span></span></div></div>}
                                <div ref={chatEndRef} />
                            </section>
                            <footer className="chat-footer">
                                <div className="chat-controls">
                                    <div className="mode-select glass" style={{ marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
                                        <Search size={14} />
                                        <span style={{ opacity: 0.8 }}>{t('query_mode') || '查询模式'}</span>
                                        <select
                                            value={queryMode}
                                            onChange={(e) => setQueryMode(e.target.value)}
                                            style={{ background: 'transparent', borderRadius: '6px', border: '1px solid rgba(148, 163, 184, 0.8)', padding: '2px 8px', fontSize: '12px', color: 'inherit' }}
                                        >
                                            <option value="vector">{t('mode_fast') || '快速（向量优先）'}</option>
                                            <option value="hybrid">{t('mode_smart') || '智能（自动选择）'}</option>
                                            <option value="graph">{t('mode_graph') || '图模式（关系更强）'}</option>
                                        </select>
                                    </div>
                                    <form className="input-container glass" onSubmit={handleQuery}>
                                        <input value={query} onChange={e => setQuery(e.target.value)} placeholder={t('placeholder')} />
                                        <button type="submit" className="send-btn"><Send size={18} /></button>
                                    </form>
                                </div>
                            </footer>
                        </div>
                    )}

                    {activeTab === 'graph' && (
                        <div className="graph-container" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                            <div className="graph-intro glass" style={{ flexShrink: 0, margin: '12px 16px', padding: '12px 16px', borderRadius: '10px', fontSize: '13px', lineHeight: 1.5 }}>
                                <div style={{ fontWeight: '600', marginBottom: '6px' }}>{t('graph_overview_title')}</div>
                                <div style={{ opacity: 0.85 }}>{t('graph_overview_desc')}</div>
                            </div>
                            <div style={{ flex: 1, minHeight: 0 }}>
                                <GraphExplorer />
                            </div>
                        </div>
                    )}

                    {activeTab === 'docs' && (
                        <div className="docs-container">
                            <h2>{t('doc_management')}</h2>
                            <div className="docs-grid">
                                {documents.map((doc, i) => (
                                    <div key={i} className="doc-item glass" style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '20px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', flex: 1 }}>
                                                <FileText size={24} className="doc-icon" style={{ flexShrink: 0, marginTop: '2px' }} /> 
                                                <span className="doc-name" style={{ fontWeight: 'bold' }}>{doc.name}</span>
                                            </div>
                                            <button 
                                                onClick={() => deleteDocument(doc.name)}
                                                style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', padding: '4px', flexShrink: 0 }}
                                                className="delete-doc-btn"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                <Clock size={12} /> <span>{doc.uploaded_at}</span>
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                <User size={12} /> <span>{doc.uploader}</span>
                                            </div>
                                            <div style={{ marginTop: '4px', opacity: 0.7, fontWeight: '500' }}>
                                                {formatSize(doc.size)}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {activeTab === 'settings' && (
                        <div className="settings-container">
                            <div className="section-header">
                                <h2 className="section-title">{t('core_config')}</h2>
                                <button onClick={saveSettings} className="save-btn glass">
                                    {saveStatus ? t('saving') : t('save_changes')}
                                </button>
                            </div>

                            <div className="settings-grid">
                                <div className="setting-card glass setting-card-llm">
                                    <div className="card-header">
                                        <Zap size={20} color="#6366f1" />
                                        <div>
                                            <h3 className="card-title">{t('reasoning_model')}</h3>
                                            <span className="card-subtitle">{t('reasoning_model_subtitle')}</span>
                                        </div>
                                    </div>
                                    <div className="setting-info">
                                        <label>{t('select_model')}</label>
                                        <select
                                            value={appSettings.llm_model}
                                            onChange={(e) => updateSetting('llm_model', e.target.value)}
                                            className="model-select"
                                        >
                                            {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
                                        </select>
                                        <label>{t('server_address')}</label>
                                        <input
                                            type="text"
                                            value={appSettings.ollama_base_url || ''}
                                            onChange={(e) => updateSetting('ollama_base_url', e.target.value)}
                                            className="settings-input"
                                            placeholder="http://192.168.0.x:11434"
                                        />
                                    </div>
                                    <button onClick={() => testConnection('llm')} className="test-btn">{t('test_ollama')}</button>
                                    {testResult.type === 'llm' && <p className={`test-msg ${testResult.success ? 'success' : 'error'}`}>{testResult.msg}</p>}
                                </div>

                                <div className="setting-card glass setting-card-embed">
                                    <div className="card-header">
                                        <Database size={20} color="#10b981" />
                                        <div>
                                            <h3 className="card-title">{t('vector_model')}</h3>
                                            <span className="card-subtitle">{t('vector_model_subtitle')}</span>
                                        </div>
                                    </div>
                                    <div className="setting-info">
                                        <label>{t('select_vector_model')}</label>
                                        <select
                                            value={appSettings.embedding_model}
                                            onChange={(e) => updateSetting('embedding_model', e.target.value)}
                                            className="model-select"
                                        >
                                            {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
                                        </select>
                                        <label>{t('storage_backend')}</label>
                                        <code>PostgreSQL (pgvector)</code>
                                    </div>
                                    <button onClick={() => testConnection('graph')} className="test-btn">{t('test_db')}</button>
                                    {testResult.type === 'graph' && <p className={`test-msg ${testResult.success ? 'success' : 'error'}`}>{testResult.msg}</p>}
                                </div>

                                <div className="setting-card glass setting-card-extract">
                                    <div className="card-header">
                                        <Zap size={20} color="#f59e0b" />
                                        <div>
                                            <h3 className="card-title">{t('extraction_model')}</h3>
                                            <span className="card-subtitle">{t('extraction_model_subtitle')}</span>
                                        </div>
                                    </div>
                                    <div className="setting-info">
                                        <label>{t('select_model')}</label>
                                        <select
                                            value={appSettings.extraction_model || ''}
                                            onChange={(e) => updateSetting('extraction_model', e.target.value)}
                                            className="model-select"
                                        >
                                            {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
                                        </select>
                                        <p className="setting-tip">💡 {t('extraction_tip')}</p>
                                    </div>
                                    <button onClick={() => testConnection('llm')} className="test-btn">{t('test_ollama')}</button>
                                    {testResult.type === 'llm' && <p className={`test-msg ${testResult.success ? 'success' : 'error'}`}>{testResult.msg}</p>}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </main>
            
            <footer className="status-bar">
                <div className="status-left">
                    <div className="status-item">
                        <div className="status-dot"></div>
                        <span>{t('system_online')}</span>
                    </div>
                    <div className="status-item">
                        <Activity size={12} />
                        <span>{t('database_status')}</span>
                    </div>
                </div>
                <div className="status-right">
                    <div className="status-item">
                        <span>{t('current_llm')}</span>
                        <span className="model-badge">{appSettings.llm_model || '…'}</span>
                    </div>
                    <div className="status-item">
                        <span>{t('current_extraction')}</span>
                        <span className="model-badge model-badge-extract">{appSettings.extraction_model || '…'}</span>
                    </div>
                    <div className="status-item">
                        <span>{t('current_embedding')}</span>
                        <span className="model-badge">{appSettings.embedding_model || '…'}</span>
                    </div>
                </div>
            </footer>
        </div>
    );
};

export default App;
