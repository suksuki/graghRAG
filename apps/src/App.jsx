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

    const chatEndRef = useRef(null);

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

        return () => {
            clearInterval(timer);
            window.removeEventListener('keydown', handleKeyPress);
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
        } catch (e) { }
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
        setSaveStatus('Saving...');
        try {
            await axios.post('/api/settings/update', {
                llm_model: appSettings.llm_model,
                extraction_model: appSettings.extraction_model,
                embedding_model: appSettings.embedding_model,
                ollama_base_url: appSettings.ollama_base_url
            });
            setSaveStatus('Settings saved successfully!');
            fetchAppSettings();
            setTimeout(() => setSaveStatus(null), 3000);
        } catch (e) {
            setSaveStatus('Failed to save settings.');
        }
    };

    const testConnection = async (type) => {
        setTestResult({ type, msg: 'Testing...' });
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
            setTestResult({ type, msg: 'Connection failed', success: false });
        }
    };

    const handleQuery = async (e) => {
        e.preventDefault();
        if (!query.trim() || loading) return;
        setMessages(prev => [...prev, { role: 'user', text: query }]);
        setQuery('');
        setLoading(true);
        try {
            const res = await axios.post('/api/query', { query, mode: queryMode });
            setMessages(prev => [...prev, { role: 'assistant', text: res.data.answer, sources: res.data.sources }]);
        } catch (e) {
            setMessages(prev => [...prev, { role: 'assistant', text: t('error_query') }]);
        } finally { setLoading(false); }
    };

    const deleteDocument = async (name) => {
        if (!window.confirm(`确定要删除文档 ${name} 吗？`)) return;
        try {
            await axios.delete(`/api/documents/${encodeURIComponent(name)}`);
            fetchDocuments(); // Refresh list
        } catch (e) {
            alert('删除失败: ' + (e.response?.data?.detail || e.message));
        }
    };

    const formatSize = (bytes) => {
        if (bytes < 1024) return bytes + ' Bytes';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1048576).toFixed(1) + ' MB';
    };

    const [isUploading, setIsUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [lastUploadedFiles, setLastUploadedFiles] = useState([]);
    const handleFileUpload = async (e) => {
        const files = e.target.files;
        if (!files.length) return;
        setIsUploading(true);
        setUploadProgress(0);
        setLastUploadedFiles([]);
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) formData.append('files', files[i]);
        try {
            const res = await axios.post('/api/upload', formData, {
                onUploadProgress: (progressEvent) => {
                    const percentCompleted = progressEvent.total
                        ? Math.round((progressEvent.loaded * 100) / progressEvent.total)
                        : 0;
                    setUploadProgress(percentCompleted);
                }
            });
            const names = res.data?.files || [];
            setLastUploadedFiles(names);
            fetchIngestionStatus();
            if (names.length > 0) setTimeout(() => setLastUploadedFiles([]), 8000);
        } catch (e) { } finally {
            setIsUploading(false);
            setUploadProgress(0);
        }
    };

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
                        <span>{t('ingestion_status')}: {ingestionStatus.status === 'processing' ? (ingestionStatus.message || t('analyzing')) : t('idle')}</span>
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
                                    {t('graph_chunks_progress')}: {ingestionStatus.graph_done || 0}/{ingestionStatus.graph_total} {t('chunks_unit')} · {ingestionStatus.progress || 0}%
                                </div>
                            )}
                        </>
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
                <div className="content-viewport">
                    {activeTab === 'chat' && (
                        <div className="chat-layout">
                            <section className="messages-container">
                                {messages.map((msg, i) => (
                                    <div key={i} className={`message-wrapper ${msg.role}`}>
                                        <div className={`message-bubble ${msg.role === 'user' ? 'primary' : 'glass'}`}>
                                            <div>{msg.text}</div>
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
