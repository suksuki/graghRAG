import React, { useEffect, useState, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

const GraphExplorer = () => {
    const { t, i18n } = useTranslation();
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [initialGraph, setInitialGraph] = useState({ nodes: [], links: [] });
    const [loading, setLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState(null);
    const [documents, setDocuments] = useState([]);
    const [pathA, setPathA] = useState('');
    const [pathB, setPathB] = useState('');
    const [pathLoading, setPathLoading] = useState(false);
    const [overview, setOverview] = useState(null);
    const [suggestedQuestions, setSuggestedQuestions] = useState([]);
    const [entityTypes, setEntityTypes] = useState([]);
    const [currentType, setCurrentType] = useState(null);
    const [entities, setEntities] = useState([]);
    const [entitiesTotal, setEntitiesTotal] = useState(0);
    const [entitiesPage, setEntitiesPage] = useState(1);
    const [entitiesPageSize] = useState(20);

    const transformGraph = (data) => {
        const nodes = (data.nodes || []).map((n) => {
            const props = n.properties || {};
            const name = props.name || props.title || props.file_name || String(n.id);
            const type = (n.labels && n.labels[0]) || props.type || 'Node';
            return {
                id: String(n.id),
                name,
                type,
                raw: n,
            };
        });

        const links = (data.edges || []).map((e, idx) => ({
            id: idx,
            source: String(e.source),
            target: String(e.target),
            label: e.type || (e.properties && e.properties.type) || 'REL',
            raw: e,
        }));

        return { nodes, links };
    };

    const loadInitialGraph = useCallback(async () => {
        setLoading(true);
        try {
            const [relationsRes, overviewRes, suggRes, typesRes] = await Promise.all([
                axios.get('/api/graph/relations', { params: { limit: 200 } }),
                axios.get('/api/graph/overview'),
                axios.get('/api/graph/suggested_questions', {
                    headers: { 'x-lang': i18n.language || 'zh' },
                }),
                axios.get('/api/graph/entity_types'),
            ]);
            const transformed = transformGraph(relationsRes.data || {});
            setGraphData(transformed);
            setInitialGraph(transformed);
            setOverview(overviewRes.data || null);
            setSuggestedQuestions(suggRes.data?.questions || []);
            setEntityTypes(typesRes.data?.types || []);
        } catch (e) {
            // ignore, keep current graph
        } finally {
            setLoading(false);
        }
    }, [i18n.language]);

    const loadSubgraph = useCallback(async (entityName) => {
        if (!entityName) return;
        setLoading(true);
        try {
            const res = await axios.get('/api/graph/subgraph', {
                params: { entity: entityName, limit: 200 },
            });
            setGraphData(transformGraph(res.data || {}));
        } catch (e) {
            // ignore, keep current graph
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadInitialGraph();
    }, [loadInitialGraph]);

    const loadNodeDocuments = useCallback(async (entityName) => {
        if (!entityName) return;
        try {
            const res = await axios.get('/api/graph/node_documents', {
                params: { entity: entityName, limit: 10 },
            });
            setDocuments(res.data?.documents || []);
        } catch (e) {
            setDocuments([]);
        }
    }, []);

    const loadEntitiesPage = useCallback(async (type, page) => {
        if (!type) return;
        try {
            const res = await axios.get('/api/graph/entities', {
                params: { type, page, size: entitiesPageSize },
            });
            const data = res.data || {};
            const newEntities = data.entities || [];
            setEntities(prev => (page === 1 ? newEntities : [...prev, ...newEntities]));
            setEntitiesTotal(data.total || 0);
            setEntitiesPage(page);
        } catch (e) {
            if (page === 1) {
                setEntities([]);
                setEntitiesTotal(0);
                setEntitiesPage(1);
            }
        }
    }, [entitiesPageSize]);

    const handleNodeClick = (node) => {
        const name = node?.raw?.properties?.name || node?.name;
        if (name) {
            setSelectedNode(node);
            loadSubgraph(name);
            loadNodeDocuments(name);
        }
    };

    const nodeDisplayName = (node) =>
        node?.raw?.properties?.name || node?.raw?.properties?.title || node?.name;

    const nodeLabel = (node) => {
        const props = node.raw?.properties || {};
        const sourceDoc = props.file_name || props.source || '';
        const lines = [
            `<div><strong>${node.name}</strong></div>`,
            `<div style="font-size:11px;opacity:0.8;">${node.type}</div>`,
        ];
        if (sourceDoc) {
            lines.push(
                `<div style="font-size:11px;opacity:0.8;margin-top:4px;">${t('source_label')}: ${sourceDoc}</div>`,
            );
        }
        return lines.join('');
    };

    const handleFindPath = async (e) => {
        e.preventDefault();
        if (!pathA.trim() || !pathB.trim()) return;
        setPathLoading(true);
        try {
            const res = await axios.get('/api/graph/path', {
                params: { a: pathA.trim(), b: pathB.trim(), max_hops: 4 },
            });
            setGraphData(transformGraph(res.data || {}));
        } catch (e) {
            // ignore
        } finally {
            setPathLoading(false);
        }
    };

    return (
        <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex' }}>
            {loading && (
                <div
                    style={{
                        position: 'absolute',
                        top: 12,
                        right: 16,
                        zIndex: 10,
                        padding: '4px 10px',
                        borderRadius: '999px',
                        fontSize: 12,
                        background: 'rgba(15,23,42,0.85)',
                        color: '#e5e7eb',
                    }}
                >
                    {t('loading')}
                </div>
            )}
            <div style={{ flex: 1, minWidth: 0, position: 'relative', display: 'flex', flexDirection: 'column' }}>
                <div
                    style={{
                        flexShrink: 0,
                        padding: '8px 12px',
                        display: 'flex',
                        gap: 16,
                        color: '#e5e7eb',
                        fontSize: 12,
                    }}
                >
                    <div
                        style={{
                            minWidth: 200,
                            padding: '8px 10px',
                            borderRadius: 8,
                            background: 'rgba(15,23,42,0.9)',
                            border: '1px solid rgba(148,163,184,0.4)',
                        }}
                    >
                        <div style={{ fontWeight: 600, marginBottom: 4 }}>{t('graph_overview')}</div>
                        {overview ? (
                            <>
                                <div>{t('nodes_label')}: {overview.node_count}</div>
                                <div>{t('relations_count_label')}: {overview.edge_count}</div>
                                {overview.entity_types && overview.entity_types.length > 0 && (
                                    <div style={{ marginTop: 6 }}>
                                        <div style={{ opacity: 0.8, marginBottom: 2 }}>{t('top_entity_types')}</div>
                                        {overview.entity_types.slice(0, 4).map((t, idx) => (
                                            <div key={idx}>
                                                {t.type}: {t.count}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </>
                        ) : (
                            <div style={{ opacity: 0.7 }}>{t('no_graph_overview_data')}</div>
                        )}
                    </div>

                    <div
                        style={{
                            flex: 1,
                            padding: '8px 10px',
                            borderRadius: 8,
                            background: 'rgba(15,23,42,0.9)',
                            border: '1px solid rgba(148,163,184,0.4)',
                            maxHeight: 120,
                            overflow: 'auto',
                        }}
                    >
                        <div style={{ fontWeight: 600, marginBottom: 4 }}>{t('suggested_questions_plain')}</div>
                        {suggestedQuestions && suggestedQuestions.length > 0 ? (
                            <ul style={{ paddingLeft: 18, margin: 0 }}>
                                {suggestedQuestions.map((q, idx) => (
                                    <li
                                        key={idx}
                                        style={{
                                            marginBottom: 4,
                                            cursor: 'pointer',
                                            textDecoration: 'underline',
                                            textUnderlineOffset: 2,
                                        }}
                                        onClick={() => {
                                            try {
                                                localStorage.setItem('graphrag_suggested_question', q);
                                            } catch (e) { }
                                            window.scrollTo(0, 0);
                                            window.dispatchEvent(new CustomEvent('graphrag_open_chat'));
                                        }}
                                    >
                                        {q}
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <div style={{ opacity: 0.7 }}>{t('no_suggested_questions')}</div>
                        )}
                    </div>
                </div>
                <div
                    style={{
                        position: 'absolute',
                        top: 70,
                        left: 10,
                        zIndex: 10,
                        padding: '6px 10px',
                        borderRadius: '8px',
                        background: 'rgba(15,23,42,0.9)',
                        color: '#e5e7eb',
                        fontSize: 12,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                    }}
                >
                    <form onSubmit={handleFindPath} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <input
                            value={pathA}
                            onChange={(e) => setPathA(e.target.value)}
                            placeholder={t('entity_a_placeholder')}
                            style={{ width: 120, fontSize: 12, padding: '2px 6px', borderRadius: 4, border: '1px solid #4b5563', background: 'rgba(15,23,42,0.9)', color: '#e5e7eb' }}
                        />
                        <span style={{ opacity: 0.7 }}>→</span>
                        <input
                            value={pathB}
                            onChange={(e) => setPathB(e.target.value)}
                            placeholder={t('entity_b_placeholder')}
                            style={{ width: 120, fontSize: 12, padding: '2px 6px', borderRadius: 4, border: '1px solid #4b5563', background: 'rgba(15,23,42,0.9)', color: '#e5e7eb' }}
                        />
                        <button
                            type="submit"
                            disabled={pathLoading}
                            style={{
                                fontSize: 12,
                                padding: '2px 8px',
                                borderRadius: 4,
                                border: 'none',
                                background: '#6366f1',
                                color: '#e5e7eb',
                                cursor: 'pointer',
                            }}
                        >
                            {pathLoading ? t('searching') : t('find_path')}
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                if (initialGraph.nodes.length || initialGraph.links.length) {
                                    setGraphData(initialGraph);
                                    setSelectedNode(null);
                                    setDocuments([]);
                                } else {
                                    loadInitialGraph();
                                }
                            }}
                            style={{
                                fontSize: 12,
                                padding: '2px 8px',
                                borderRadius: 4,
                                border: '1px solid #4b5563',
                                background: 'transparent',
                                color: '#e5e7eb',
                                cursor: 'pointer',
                            }}
                        >
                            {t('reset_view')}
                        </button>
                    </form>
                </div>
                <div style={{ flex: 1, minHeight: 0 }}>
                    <ForceGraph2D
                        graphData={graphData}
                        nodeLabel={nodeLabel}
                        nodeAutoColorBy="type"
                        linkColor={() => 'rgba(96,165,250,0.85)'}
                        linkWidth={() => 1.8}
                        linkDirectionalArrowLength={6}
                        linkDirectionalArrowRelPos={0.95}
                        linkLabel={(link) => link.label}
                        onNodeClick={handleNodeClick}
                        width={undefined}
                        height={undefined}
                    />
                </div>
            </div>

            <div
                style={{
                    width: 340,
                    maxWidth: '30%',
                    borderLeft: '1px solid rgba(148,163,184,0.2)',
                    background: 'rgba(15,23,42,0.92)',
                    color: '#e5e7eb',
                    padding: '10px 12px',
                    fontSize: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 12,
                }}
            >
                <div>
                    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{t('entity_browser')}</div>
                    {entityTypes && entityTypes.length > 0 ? (
                        <div
                            style={{
                                maxHeight: 140,
                                overflow: 'auto',
                                borderRadius: 6,
                                border: '1px solid rgba(55,65,81,0.8)',
                                padding: '6px 8px',
                            }}
                        >
                            {entityTypes.map((t) => (
                                <div key={t.type} style={{ marginBottom: 6 }}>
                                    <div
                                        style={{
                                            fontWeight: 500,
                                            marginBottom: 2,
                                            cursor: 'pointer',
                                            color: currentType === t.type ? '#a5b4fc' : '#e5e7eb',
                                        }}
                                        onClick={() => {
                                            setCurrentType(t.type);
                                            setEntities([]);
                                            setEntitiesTotal(0);
                                            setEntitiesPage(1);
                                            loadEntitiesPage(t.type, 1);
                                        }}
                                    >
                                        {t.type} ({t.count})
                                    </div>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                        {currentType === t.type &&
                                            entities.map((name) => (
                                            <span
                                                key={name}
                                                style={{
                                                    padding: '2px 6px',
                                                    borderRadius: 999,
                                                    background: 'rgba(15,23,42,0.9)',
                                                    border: '1px solid rgba(99,102,241,0.6)',
                                                    cursor: 'pointer',
                                                }}
                                                onClick={() => {
                                                    setSelectedNode(null);
                                                    loadSubgraph(name);
                                                    loadNodeDocuments(name);
                                                }}
                                            >
                                                {name}
                                            </span>
                                            ))}
                                    </div>
                                    {currentType === t.type && entities.length < entitiesTotal && (
                                        <button
                                            type="button"
                                            onClick={() => loadEntitiesPage(t.type, entitiesPage + 1)}
                                            style={{
                                                marginTop: 4,
                                                fontSize: 11,
                                                padding: '2px 6px',
                                                borderRadius: 999,
                                                border: '1px solid rgba(148,163,184,0.8)',
                                                background: 'transparent',
                                                color: '#e5e7eb',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            {t('load_more')}
                                        </button>
                                    )}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div style={{ opacity: 0.7 }}>{t('no_browsable_entities')}</div>
                    )}
                </div>

                <div>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{t('node_details')}</div>
                    {selectedNode ? (
                        <>
                            <div>{nodeDisplayName(selectedNode)}</div>
                            <div style={{ opacity: 0.75, marginBottom: 4 }}>
                                {(selectedNode.raw?.labels || []).join(', ') || selectedNode.type}
                            </div>
                            <div style={{ fontWeight: 500, marginTop: 4 }}>{t('related_documents')}</div>
                            {documents.length === 0 && (
                                <div style={{ opacity: 0.7 }}>{t('no_related_documents')}</div>
                            )}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                                {documents.map((doc, idx) => (
                                    <div
                                        key={idx}
                                        style={{
                                            padding: '6px 8px',
                                            borderRadius: 6,
                                            background: 'rgba(15,23,42,0.9)',
                                            border: '1px solid rgba(55,65,81,0.8)',
                                        }}
                                    >
                                        <div style={{ fontWeight: 500, marginBottom: 4 }}>{doc.file}</div>
                                        <div style={{ opacity: 0.8, fontSize: 11, maxHeight: 80, overflow: 'auto' }}>
                                            {doc.text || t('no_summary_text')}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    ) : (
                        <div style={{ opacity: 0.7 }}>{t('click_node_to_view_docs')}</div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default GraphExplorer;
