import React, { useEffect, useState, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import axios from 'axios';
import { useTranslation } from 'react-i18next';

const toolbarBtn = {
    fontSize: 12,
    padding: '4px 10px',
    borderRadius: 6,
    border: '1px solid rgba(148,163,184,0.45)',
    background: 'rgba(30,41,59,0.9)',
    color: '#e5e7eb',
    cursor: 'pointer',
};

const toolbarBtnPrimary = {
    ...toolbarBtn,
    border: 'none',
    background: '#6366f1',
};

/**
 * 图谱辅助页：默认突出画布与节点详情；路径查找与类型浏览弱化，避免「要点一下才看到图」的臃肿顶栏。
 */
const GraphExplorer = () => {
    const { t } = useTranslation();
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [initialGraph, setInitialGraph] = useState({ nodes: [], links: [] });
    const [loading, setLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState(null);
    const [documents, setDocuments] = useState([]);
    const [pathA, setPathA] = useState('');
    const [pathB, setPathB] = useState('');
    const [pathLoading, setPathLoading] = useState(false);
    const [overview, setOverview] = useState(null);
    const [entityTypes, setEntityTypes] = useState([]);
    const [currentType, setCurrentType] = useState(null);
    const [entities, setEntities] = useState([]);
    const [entitiesTotal, setEntitiesTotal] = useState(0);
    const [entitiesPage, setEntitiesPage] = useState(1);
    const [entitiesPageSize] = useState(20);
    const [showPathPanel, setShowPathPanel] = useState(false);

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
            const [relS, ovS, typesS] = await Promise.allSettled([
                axios.get('/api/graph/relations', { params: { limit: 200 } }),
                axios.get('/api/graph/overview'),
                axios.get('/api/graph/entity_types'),
            ]);

            if (relS.status === 'fulfilled') {
                const transformed = transformGraph(relS.value.data || {});
                setGraphData(transformed);
                setInitialGraph(transformed);
            }

            if (ovS.status === 'fulfilled' && ovS.value.data) {
                setOverview(ovS.value.data);
            } else if (ovS.status === 'rejected') {
                setOverview(null);
            }

            if (typesS.status === 'fulfilled') {
                setEntityTypes(typesS.value.data?.types || []);
            }
        } finally {
            setLoading(false);
        }
    }, []);

    const loadSubgraph = useCallback(async (entityName) => {
        if (!entityName) return;
        setLoading(true);
        try {
            const res = await axios.get('/api/graph/subgraph', {
                params: { entity: entityName, limit: 200 },
            });
            setGraphData(transformGraph(res.data || {}));
        } catch (e) {
            /* keep current graph */
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

    const loadEntitiesPage = useCallback(
        async (type, page) => {
            if (!type) return;
            try {
                const res = await axios.get('/api/graph/entities', {
                    params: { type, page, size: entitiesPageSize },
                });
                const data = res.data || {};
                const newEntities = data.entities || [];
                setEntities((prev) => (page === 1 ? newEntities : [...prev, ...newEntities]));
                setEntitiesTotal(data.total || 0);
                setEntitiesPage(page);
            } catch (e) {
                if (page === 1) {
                    setEntities([]);
                    setEntitiesTotal(0);
                    setEntitiesPage(1);
                }
            }
        },
        [entitiesPageSize]
    );

    const resetView = useCallback(() => {
        if (initialGraph.nodes.length || initialGraph.links.length) {
            setGraphData(initialGraph);
            setSelectedNode(null);
            setDocuments([]);
        } else {
            loadInitialGraph();
        }
    }, [initialGraph, loadInitialGraph]);

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
                `<div style="font-size:11px;opacity:0.8;margin-top:4px;">${t('source_label')}: ${sourceDoc}</div>`
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
        } catch (err) {
            /* ignore */
        } finally {
            setPathLoading(false);
        }
    };

    const topTypesLine =
        overview?.entity_types?.length > 0
            ? overview.entity_types
                  .slice(0, 4)
                  .map((row) => `${row.type}:${row.count}`)
                  .join(' · ')
            : null;

    return (
        <div
            style={{
                width: '100%',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                background: '#0f172a',
            }}
        >
            {loading && (
                <div
                    style={{
                        position: 'absolute',
                        top: 10,
                        right: 12,
                        zIndex: 10,
                        padding: '4px 10px',
                        borderRadius: 999,
                        fontSize: 12,
                        background: 'rgba(15,23,42,0.9)',
                        color: '#e5e7eb',
                        border: '1px solid rgba(148,163,184,0.35)',
                    }}
                >
                    {t('loading')}
                </div>
            )}

            <div
                style={{
                    flexShrink: 0,
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    gap: 10,
                    padding: '6px 12px',
                    borderBottom: '1px solid rgba(51,65,85,0.5)',
                    color: '#e5e7eb',
                    fontSize: 12,
                }}
            >
                <div style={{ flex: '1 1 200px', minWidth: 0, lineHeight: 1.45 }}>
                    {overview ? (
                        <>
                            <span style={{ fontWeight: 600, marginRight: 6 }}>{t('graph_overview')}</span>
                            <span style={{ opacity: 0.88 }}>
                                {t('nodes_label')} {overview.node_count}
                                {' · '}
                                {t('relations_count_label')} {overview.edge_count}
                                {topTypesLine ? (
                                    <>
                                        {' · '}
                                        <span style={{ opacity: 0.75 }}>{topTypesLine}</span>
                                    </>
                                ) : null}
                            </span>
                        </>
                    ) : (
                        <span style={{ opacity: 0.75 }}>{t('no_graph_overview_data')}</span>
                    )}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                    <button
                        type="button"
                        style={showPathPanel ? toolbarBtn : toolbarBtnPrimary}
                        onClick={() => setShowPathPanel((v) => !v)}
                    >
                        {showPathPanel ? t('collapse') : t('graph_path_tools')}
                    </button>
                    <button type="button" style={toolbarBtn} onClick={resetView}>
                        {t('reset_view')}
                    </button>
                </div>
            </div>

            {showPathPanel ? (
                <div
                    style={{
                        flexShrink: 0,
                        padding: '8px 12px',
                        borderBottom: '1px solid rgba(51,65,85,0.45)',
                        background: 'rgba(15,23,42,0.65)',
                    }}
                >
                    <form
                        onSubmit={handleFindPath}
                        style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}
                    >
                        <input
                            value={pathA}
                            onChange={(e) => setPathA(e.target.value)}
                            placeholder={t('entity_a_placeholder')}
                            style={{
                                width: 130,
                                maxWidth: '42vw',
                                fontSize: 12,
                                padding: '4px 8px',
                                borderRadius: 6,
                                border: '1px solid #4b5563',
                                background: 'rgba(15,23,42,0.95)',
                                color: '#e5e7eb',
                            }}
                        />
                        <span style={{ opacity: 0.65 }}>→</span>
                        <input
                            value={pathB}
                            onChange={(e) => setPathB(e.target.value)}
                            placeholder={t('entity_b_placeholder')}
                            style={{
                                width: 130,
                                maxWidth: '42vw',
                                fontSize: 12,
                                padding: '4px 8px',
                                borderRadius: 6,
                                border: '1px solid #4b5563',
                                background: 'rgba(15,23,42,0.95)',
                                color: '#e5e7eb',
                            }}
                        />
                        <button
                            type="submit"
                            disabled={pathLoading}
                            style={{ ...toolbarBtnPrimary, opacity: pathLoading ? 0.7 : 1 }}
                        >
                            {pathLoading ? t('searching') : t('find_path')}
                        </button>
                    </form>
                </div>
            ) : null}

            <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'row' }}>
                <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
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

                <aside
                    style={{
                        width: 300,
                        maxWidth: '34%',
                        flexShrink: 0,
                        borderLeft: '1px solid rgba(148,163,184,0.2)',
                        background: 'rgba(15,23,42,0.94)',
                        color: '#e5e7eb',
                        padding: '12px 12px 16px',
                        fontSize: 12,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 14,
                        overflowY: 'auto',
                    }}
                >
                    <section>
                        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>{t('node_details')}</div>
                        {selectedNode ? (
                            <>
                                <div>{nodeDisplayName(selectedNode)}</div>
                                <div style={{ opacity: 0.75, marginBottom: 6 }}>
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
                                            <div
                                                style={{ opacity: 0.8, fontSize: 11, maxHeight: 80, overflow: 'auto' }}
                                            >
                                                {doc.text || t('no_summary_text')}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </>
                        ) : (
                            <div style={{ opacity: 0.72, lineHeight: 1.5 }}>{t('click_node_to_view_docs')}</div>
                        )}
                    </section>

                    <details style={{ borderTop: '1px solid rgba(51,65,85,0.6)', paddingTop: 12 }}>
                        <summary
                            style={{
                                cursor: 'pointer',
                                fontWeight: 600,
                                fontSize: 13,
                                listStyle: 'none',
                                outline: 'none',
                            }}
                        >
                            {t('entity_browser')}
                        </summary>
                        <div style={{ marginTop: 10 }}>
                            {entityTypes && entityTypes.length > 0 ? (
                                <div
                                    style={{
                                        maxHeight: 200,
                                        overflow: 'auto',
                                        borderRadius: 6,
                                        border: '1px solid rgba(55,65,81,0.8)',
                                        padding: '6px 8px',
                                    }}
                                >
                                    {entityTypes.map((et) => (
                                        <div key={et.type} style={{ marginBottom: 8 }}>
                                            <div
                                                style={{
                                                    fontWeight: 500,
                                                    marginBottom: 4,
                                                    cursor: 'pointer',
                                                    color: currentType === et.type ? '#a5b4fc' : '#e5e7eb',
                                                }}
                                                onClick={() => {
                                                    setCurrentType(et.type);
                                                    setEntities([]);
                                                    setEntitiesTotal(0);
                                                    setEntitiesPage(1);
                                                    loadEntitiesPage(et.type, 1);
                                                }}
                                            >
                                                {et.type} ({et.count})
                                            </div>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                                {currentType === et.type &&
                                                    entities.map((name) => (
                                                        <span
                                                            key={name}
                                                            style={{
                                                                padding: '2px 6px',
                                                                borderRadius: 999,
                                                                background: 'rgba(15,23,42,0.9)',
                                                                border: '1px solid rgba(99,102,241,0.55)',
                                                                cursor: 'pointer',
                                                                fontSize: 11,
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
                                            {currentType === et.type && entities.length < entitiesTotal ? (
                                                <button
                                                    type="button"
                                                    onClick={() => loadEntitiesPage(et.type, entitiesPage + 1)}
                                                    style={{
                                                        marginTop: 4,
                                                        fontSize: 11,
                                                        padding: '2px 8px',
                                                        borderRadius: 999,
                                                        border: '1px solid rgba(148,163,184,0.75)',
                                                        background: 'transparent',
                                                        color: '#e5e7eb',
                                                        cursor: 'pointer',
                                                    }}
                                                >
                                                    {t('load_more')}
                                                </button>
                                            ) : null}
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div style={{ opacity: 0.7 }}>{t('no_browsable_entities')}</div>
                            )}
                        </div>
                    </details>
                </aside>
            </div>
        </div>
    );
};

export default GraphExplorer;
