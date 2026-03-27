import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Send, Share2, Database, Network, CheckCircle, Loader2, Languages, Settings as SettingsIcon, Activity, Zap, Library, Sparkles } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import './App.css';
import GraphExplorer from './pages/GraphExplorer.jsx';
import DocumentPage from './pages/DocumentPage.jsx';
import DocumentDetail from './pages/DocumentDetail.jsx';
import EntityPage from './pages/EntityPage.jsx';
import SearchPage from './pages/SearchPage.jsx';
import InsightPage from './pages/InsightPage.jsx';
import DocScopePicker from './components/DocScopePicker.jsx';
import { logInsightEvent } from './utils/insightEvents';

const App = () => {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();
    const location = useLocation();
    const [activeTab, setActiveTab] = useState('chat'); // chat, graph, documents, search, entity, settings
    const [query, setQuery] = useState('');
    const queryMode = 'hybrid';
    const [messages, setMessages] = useState([{ role: 'assistant', text: t('welcome') }]);
    const [loading, setLoading] = useState(false);

    // Data States
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [ingestionStatus, setIngestionStatus] = useState({ status: 'idle', node_count: 0 });
    const [appSettings, setAppSettings] = useState({});
    const [availableModels, setAvailableModels] = useState([]);
    const [testResult, setTestResult] = useState({ type: null, msg: '' });
    const [saveStatus, setSaveStatus] = useState(null);
    const [expandedGraph, setExpandedGraph] = useState({});
    const [errorModal, setErrorModal] = useState(null);

    // 文档中心 / 搜索 / 实体页（P0 产品化）
    const [selectedLibraryDoc, setSelectedLibraryDoc] = useState(null);
    const [entityViewName, setEntityViewName] = useState(null);
    const [scopeDocs, setScopeDocs] = useState([]);
    const [selectedScopeDoc, setSelectedScopeDoc] = useState(null);
    const lastQueryRef = useRef({ ts: 0, len: 0 });

    const chatEndRef = useRef(null);

    const openEntityPage = (name) => {
        if (!name) return;
        setEntityViewName(name);
        setActiveTab('entity');
        navigate(`/entity/${encodeURIComponent(name)}`);
    };

    // 与 URL 同步：/search、/documents、/docs/{doc_id}
    useEffect(() => {
        const pathname = location.pathname || '';
        if (pathname.startsWith('/entity/')) {
            const encoded = pathname.slice('/entity/'.length);
            if (encoded) {
                try {
                    setEntityViewName(decodeURIComponent(encoded));
                    setActiveTab('entity');
                } catch (_) { /* ignore */ }
            }
            return;
        }
        if (pathname.startsWith('/docs/')) {
            const encoded = pathname.slice('/docs/'.length);
            if (encoded) {
                try {
                    setSelectedLibraryDoc(decodeURIComponent(encoded));
                    setActiveTab('documents');
                } catch (_) { /* ignore malformed path */ }
            }
            return;
        }
        if (pathname === '/search') {
            setActiveTab('search');
            return;
        }
        if (pathname === '/insight') {
            setActiveTab('insight');
            return;
        }
        if (pathname === '/documents') {
            setSelectedLibraryDoc(null);
            setActiveTab('documents');
        }
    }, [location.pathname]);

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
    const sourceLabel = (source) => {
        if (source === 'facts') return '基于文档结构解析';
        if (source === 'rag') return '基于文档内容分析';
        return '';
    };
    const containsNotFoundAnswer = (text) => {
        const s = String(text || '').toLowerCase();
        return (
            s.includes('未提及') ||
            s.includes('无法确定') ||
            s.includes('没有信息') ||
            s.includes('未明确提及')
        );
    };
    const containsSemanticExpansion = (text) => {
        const s = String(text || '');
        const hasFactBoundary = s.includes('未直接提及') || s.includes('文档未提及');
        const hasSemanticHint =
            s.includes('可能相关') ||
            s.includes('相关角色') ||
            s.includes('可能对应');
        return hasFactBoundary && hasSemanticHint;
    };

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

    const persistLastUpload = useCallback((payload) => {
        try {
            localStorage.setItem('graphrag_last_upload', JSON.stringify({ at: Date.now(), ...payload }));
            window.dispatchEvent(new Event('graphrag_last_upload_changed'));
        } catch (_) {
            /* ignore */
        }
    }, []);

    const fetchGraphData = async () => {
        try {
            const res = await axios.get('/api/graph/data');
            setGraphData(res.data);
        } catch (e) { }
    };

    useEffect(() => {
        if (activeTab === 'graph') fetchGraphData();
        if (activeTab === 'settings') {
            fetchAppSettings();
            fetchAvailableModels();
        }
    }, [activeTab, selectedLibraryDoc]);

    useEffect(() => {
        if (activeTab !== 'chat') return;
        let cancelled = false;
        (async () => {
            try {
                const res = await axios.get('/api/knowledge/docs', {
                    headers: { 'x-lang': i18n.language || 'zh' },
                });
                if (cancelled) return;
                setScopeDocs(Array.isArray(res.data?.documents) ? res.data.documents : []);
            } catch (e) {
                if (!cancelled) setScopeDocs([]);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [activeTab, i18n.language]);

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

    const resolveScopeDocId = useCallback((doc) => String(doc?.file_name || '').trim(), []);
    const isDocScopeAssertOn = useCallback(() => {
        if (import.meta.env.DEV) return true;
        try {
            return localStorage.getItem('graphrag_debug_doc_scope_assert') === '1';
        } catch (_) {
            return false;
        }
    }, []);

    const submitQuery = async (inputQuery) => {
        const userQuery = (inputQuery || '').trim();
        if (!userQuery || loading) return;
        const scopedDocId = resolveScopeDocId(selectedScopeDoc);
        if (selectedScopeDoc && !scopedDocId && isDocScopeAssertOn()) {
            console.warn('[DocScope ERROR] doc scoped query not using document insight API', {
                endpoint: '/api/v1/insights/document',
                doc_id: scopedDocId,
                selectedScopeDoc,
            });
        }
        if (scopedDocId) {
            logInsightEvent({
                event: 'query_with_doc_scope',
                doc_id: scopedDocId,
                payload: {
                    query_len: userQuery.length,
                },
            });
        }
        setMessages(prev => [...prev, { role: 'user', text: userQuery }]);
        setQuery('');
        setLoading(true);
        try {
            if (scopedDocId) {
                const payload = {
                    query: userQuery,
                    top_k: 8,
                    doc_id: scopedDocId,
                    include_graph_relations: true,
                };
                if (isDocScopeAssertOn()) {
                    const expected = resolveScopeDocId(selectedScopeDoc);
                    if (!expected || payload.doc_id !== expected) {
                        console.warn('[DocScope ERROR] doc scoped query not using document insight API', {
                            endpoint: '/api/v1/insights/document',
                            doc_id: payload.doc_id,
                            selectedScopeDoc,
                        });
                    }
                }
                const r = await axios.post(
                    '/api/v1/insights/document',
                    payload,
                    {
                        headers: {
                            'Content-Type': 'application/json',
                            'x-lang': i18n.language || 'zh',
                        },
                    }
                );
                const data = r?.data || {};
                const relations = Array.isArray(data?.key_relations)
                    ? data.key_relations.map((x) => ({
                        source: x?.source || '',
                        relation: x?.relation || '',
                        target: x?.target || '',
                    }))
                    : [];
                setMessages(prev => [
                    ...prev,
                    {
                        role: 'assistant',
                        text: data?.summary || t('error_query'),
                        source: data?.source || 'rag',
                        sources: null,
                        pipeline_latency_ms: null,
                        suggestions: [],
                        graph: {
                            relations,
                            summary: '',
                            two_hop: [],
                            count: relations.length,
                            used: relations.length > 0,
                        },
                        debug: data?.debug || null,
                    },
                ]);
                logInsightEvent({
                    event: 'answer_generated',
                    doc_id: scopedDocId || '__search__',
                    payload: {
                        source: data?.source || 'rag',
                        answer_len: String(data?.summary || '').length,
                        contains_not_found: containsNotFoundAnswer(data?.summary),
                        semantic_expansion_used: containsSemanticExpansion(data?.summary),
                    },
                });
                return;
            }

            const res = await fetch('/api/query/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-lang': i18n.language || 'zh' },
                body: JSON.stringify({
                    query: userQuery,
                    mode: queryMode,
                    doc_id: undefined,
                }),
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
                            const finalAnswer = event.answer ?? '';
                            logInsightEvent({
                                event: 'answer_generated',
                                doc_id: scopedDocId || '__search__',
                                payload: {
                                    source: event?.source || 'rag',
                                    answer_len: String(finalAnswer).length,
                                    contains_not_found: containsNotFoundAnswer(finalAnswer),
                                    semantic_expansion_used: containsSemanticExpansion(finalAnswer),
                                },
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
        const q = String(query || '').trim();
        const scopedDocId = resolveScopeDocId(selectedScopeDoc);
        const now = Date.now();
        const prev = lastQueryRef.current || { ts: 0, len: 0 };
        if (q && prev.ts > 0 && now - prev.ts <= 30000) {
            logInsightEvent({
                event: 'follow_up_query',
                doc_id: scopedDocId || '__search__',
                payload: {
                    prev_query_len: prev.len || 0,
                    new_query_len: q.length,
                },
            });
        }
        if (q) {
            logInsightEvent({
                event: 'query_submitted',
                doc_id: scopedDocId || '__search__',
                payload: {
                    has_doc_scope: Boolean(scopedDocId),
                    query_len: q.length,
                    doc_id: scopedDocId || '__search__',
                },
            });
            lastQueryRef.current = { ts: now, len: q.length };
        }
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

    const deleteLibraryDocument = async (doc) => {
        const name = doc?.name;
        if (!name) return;
        if (!window.confirm(t('delete_confirm', { name }))) return;
        try {
            await axios.delete(`/api/documents/${encodeURIComponent(name)}`);
            const key = doc?.id ?? doc?.doc_id ?? name;
            if (
                selectedLibraryDoc &&
                (selectedLibraryDoc === name || selectedLibraryDoc === key || String(selectedLibraryDoc) === String(doc?.id))
            ) {
                setSelectedLibraryDoc(null);
                navigate('/documents');
            }
            window.dispatchEvent(new Event('graphrag_refetch_docs'));
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
            persistLastUpload({
                status: res.data?.status || (jobs.length > 0 ? 'queued' : 'unknown'),
                ingestion_mode: res.data?.ingestion_mode || (jobs.length > 0 ? 'celery' : 'unknown'),
                files: names,
            });
            if (res.data?.ingestion_mode === 'inline' || res.data?.status === 'completed') {
                try {
                    window.dispatchEvent(new Event('graphrag_refetch_docs'));
                } catch (_) { /* ignore */ }
            }
            if (names.length === 1) {
                const id = names[0];
                setSelectedLibraryDoc(id);
                setActiveTab('documents');
                navigate(`/docs/${encodeURIComponent(id)}`, { state: { fromUpload: true } });
            }
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
                    const anyFailed = statuses.some(s => s.status === 'failed');
                    const doneFiles = statuses.map((s) => s.file).filter(Boolean);
                    try {
                        localStorage.setItem(
                            'graphrag_last_upload',
                            JSON.stringify({
                                at: Date.now(),
                                status: anyFailed ? 'failed' : 'completed',
                                ingestion_mode: 'celery',
                                files: doneFiles,
                            })
                        );
                        window.dispatchEvent(new Event('graphrag_last_upload_changed'));
                    } catch (_) {
                        /* ignore */
                    }
                    try {
                        window.dispatchEvent(new Event('graphrag_refetch_docs'));
                    } catch (_) { /* ignore */ }
                    fetchIngestionStatus();
                    const okFiles = statuses.filter((s) => s.status === 'done').map((s) => s.file).filter(Boolean);
                    if (!anyFailed && okFiles.length === 1) {
                        const id = okFiles[0];
                        setSelectedLibraryDoc(id);
                        setActiveTab('documents');
                        navigate(`/docs/${encodeURIComponent(id)}`, { state: { fromUpload: true } });
                    }
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

    const workspaceDocActive = activeTab === 'documents' || activeTab === 'entity';

    return (
        <div className="app-container">
            <header className="top-nav glass">
                <div className="top-nav__left">
                    <button
                        type="button"
                        className="top-nav__brand"
                        onClick={() => {
                            setSelectedLibraryDoc(null);
                            navigate('/documents');
                            setActiveTab('documents');
                        }}
                    >
                        <Share2 size={22} className="top-nav__brand-icon" aria-hidden />
                        <span className="top-nav__brand-text">
                            GraphRAG<span className="top-nav__brand-muted"> Platform</span>
                        </span>
                    </button>
                    <nav className="top-nav__links" aria-label={t('nav_main_label')}>
                        <button
                            type="button"
                            className={`top-nav__link ${workspaceDocActive ? 'top-nav__link--active' : ''}`}
                            onClick={() => {
                                setSelectedLibraryDoc(null);
                                navigate('/documents');
                                setActiveTab('documents');
                            }}
                        >
                            <Library size={17} aria-hidden />
                            {t('nav_document_center')}
                        </button>
                        <button
                            type="button"
                            className={`top-nav__link ${activeTab === 'chat' ? 'top-nav__link--active' : ''}`}
                            onClick={() => {
                                navigate('/');
                                setActiveTab('chat');
                            }}
                        >
                            <Database size={17} aria-hidden />
                            {t('knowledge_base')}
                        </button>
                        <button
                            type="button"
                            className={`top-nav__link ${activeTab === 'graph' ? 'top-nav__link--active' : ''}`}
                            onClick={() => {
                                navigate('/');
                                setActiveTab('graph');
                            }}
                        >
                            <Network size={17} aria-hidden />
                            {t('graph_overview')}
                        </button>
                        <button
                            type="button"
                            className={`top-nav__link ${activeTab === 'insight' ? 'top-nav__link--active' : ''}`}
                            onClick={() => {
                                navigate('/insight');
                                setActiveTab('insight');
                            }}
                        >
                            <Sparkles size={17} aria-hidden />
                            {t('nav_insight')}
                        </button>
                        <button
                            type="button"
                            className={`top-nav__link ${activeTab === 'settings' ? 'top-nav__link--active' : ''}`}
                            onClick={() => {
                                navigate('/');
                                setActiveTab('settings');
                            }}
                        >
                            <SettingsIcon size={17} aria-hidden />
                            {t('system_settings')}
                        </button>
                    </nav>
                </div>
                <div className="top-nav__right">
                    <div className="top-nav__lang">
                        <Languages size={14} aria-hidden />
                        <select
                            value={i18n.language}
                            onChange={(e) => i18n.changeLanguage(e.target.value)}
                            aria-label={t('language') || 'Language'}
                        >
                            <option value="zh">简体中文 (Alt+L)</option>
                            <option value="en">English (Alt+L)</option>
                            <option value="ko">한국어 (Alt+L)</option>
                        </select>
                    </div>
                </div>
            </header>

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
                                                {sourceLabel(msg.source) ? (
                                                    <div style={{ marginBottom: '6px', fontSize: '12px', opacity: 0.78 }}>
                                                        {sourceLabel(msg.source)}
                                                    </div>
                                                ) : null}
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
                                                                {Array.isArray(msg.graph?.relations) && msg.graph.relations.length > 0 && (
                                                                    <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                                                                        <div style={{ fontWeight: 600, fontSize: '12px', marginBottom: '6px' }}>{t('relations_title')}</div>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
                                                                            {(expandedGraph[i] ? msg.graph.relations : msg.graph.relations.slice(0, 8)).map((r, ridx) => (
                                                                                <div key={ridx} style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                                                                    <span>{r?.source || ''}</span>
                                                                                    <span style={{ background: 'rgba(99,102,241,0.18)', border: '1px solid rgba(99,102,241,0.35)', color: '#a5b4fc', padding: '1px 8px', borderRadius: '999px', fontSize: '11px' }}>
                                                                                        {r?.relation || ''}
                                                                                    </span>
                                                                                    <span style={{ opacity: 0.95 }}>{r?.target || ''}</span>
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
                                        </div>
                                    </div>
                                ))}
                                {loading && <div className="message-wrapper assistant"><div className="message-bubble glass typing"><span></span><span></span><span></span></div></div>}
                                <div ref={chatEndRef} />
                            </section>
                            <footer className="chat-footer">
                                <div className="chat-controls">
                                    {(selectedScopeDoc?.name || selectedScopeDoc?.file_name) ? (
                                        <div
                                            style={{
                                                marginBottom: 8,
                                                fontSize: 12,
                                                opacity: 0.85,
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: 8,
                                            }}
                                        >
                                            <span>📄 当前范围：{selectedScopeDoc?.name || selectedScopeDoc?.file_name}</span>
                                            <button
                                                type="button"
                                                onClick={() => setSelectedScopeDoc(null)}
                                                style={{
                                                    border: 'none',
                                                    background: 'transparent',
                                                    color: '#94a3b8',
                                                    cursor: 'pointer',
                                                    textDecoration: 'underline',
                                                }}
                                            >
                                                清除
                                            </button>
                                        </div>
                                    ) : null}
                                    <div className="mode-select glass" style={{ marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
                                        <DocScopePicker
                                            docs={scopeDocs}
                                            onSelect={(doc) => {
                                                setSelectedScopeDoc(doc || null);
                                                const scopedDocId = resolveScopeDocId(doc);
                                                if (scopedDocId) {
                                                    logInsightEvent({
                                                        event: 'select_doc_scope',
                                                        doc_id: scopedDocId,
                                                        payload: { doc_id: scopedDocId },
                                                    });
                                                }
                                            }}
                                        />
                                        <span style={{ opacity: 0.75 }}>{t('search_single_turn_hint')}</span>
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
                            <p
                                className="graph-page-lead"
                                style={{
                                    flexShrink: 0,
                                    margin: '8px 16px 4px',
                                    fontSize: 12,
                                    lineHeight: 1.45,
                                    color: 'rgba(226, 232, 240, 0.78)',
                                }}
                            >
                                {t('graph_overview_lead')}
                            </p>
                            <div style={{ flex: 1, minHeight: 0 }}>
                                <GraphExplorer />
                            </div>
                        </div>
                    )}

                    {activeTab === 'documents' && (
                        <div className="document-hub">
                            <DocumentPage
                                selectedDocId={selectedLibraryDoc}
                                onSelectDoc={(id) => {
                                    setSelectedLibraryDoc(id);
                                    navigate(`/docs/${encodeURIComponent(id)}`);
                                }}
                                onDeleteDocument={deleteLibraryDocument}
                                upload={{
                                    onFileChange: handleFileUpload,
                                    isUploading,
                                    uploadProgress,
                                }}
                            />
                            {selectedLibraryDoc ? (
                                <div className="document-hub__detail">
                                    <DocumentDetail
                                        key={selectedLibraryDoc}
                                        docId={selectedLibraryDoc}
                                        onBack={() => {
                                            setSelectedLibraryDoc(null);
                                            navigate('/documents');
                                        }}
                                        onEntityNavigate={openEntityPage}
                                        onSuggestedQuestion={(q) => {
                                            setActiveTab('chat');
                                            setQuery(q);
                                            setTimeout(() => submitQuery(q), 0);
                                        }}
                                        onOpenGraphStudio={() => {
                                            navigate('/');
                                            setActiveTab('graph');
                                        }}
                                    />
                                </div>
                            ) : null}
                        </div>
                    )}

                    {activeTab === 'search' && <SearchPage />}

                    {activeTab === 'insight' && <InsightPage />}

                    {activeTab === 'entity' && (
                        entityViewName ? (
                            <EntityPage
                                entityName={entityViewName}
                                onBack={() => {
                                    setEntityViewName(null);
                                    navigate('/documents');
                                }}
                                onNavigateEntity={(name) => openEntityPage(name)}
                                onNavigateDocument={(docId) => navigate(`/docs/${encodeURIComponent(docId)}`)}
                                onSuggestedQuestion={(q) => {
                                    setActiveTab('chat');
                                    setQuery(q);
                                    setTimeout(() => submitQuery(q), 0);
                                }}
                            />
                        ) : (
                            <div className="docs-container" style={{ padding: '24px 20px' }}>
                                <div className="glass" style={{ padding: '24px', borderRadius: '12px', textAlign: 'center', opacity: 0.85 }}>
                                    {t('entity_page_hint')}
                                </div>
                            </div>
                        )
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
                    <div className="status-item status-item--nodes" aria-live="polite">
                        <span>{t('status_bar_neo4j_nodes', { count: ingestionStatus.node_count ?? 0 })}</span>
                    </div>
                    <div className="status-item">
                        <span>{t('status_bar_postgres')}</span>
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
                    {ingestionStatus.status === 'processing' ? (
                        <div
                            className="status-item status-ingest status-ingest--processing status-ingest--trailing"
                            title={
                                ingestionStatus.file_names?.length
                                    ? ingestionStatus.file_names.join(', ')
                                    : (ingestionStatus.message || t('analyzing'))
                            }
                        >
                            <Activity size={12} className="pulse" aria-hidden />
                            <span className="status-ingest__text">{ingestionStatus.message || t('analyzing')}</span>
                        </div>
                    ) : null}
                    {ingestionStatus.status === 'failed' ? (
                        <div
                            className="status-item status-ingest status-ingest--fail status-ingest--trailing"
                            title={ingestionStatus.message || t('ingestion_failed')}
                        >
                            <Activity size={12} aria-hidden />
                            <span className="status-ingest__text">{t('ingestion_failed')}</span>
                        </div>
                    ) : null}
                </div>
            </footer>
        </div>
    );
};

export default App;
