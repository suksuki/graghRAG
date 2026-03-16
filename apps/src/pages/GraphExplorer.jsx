import React, { useEffect, useState, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import axios from 'axios';

const GraphExplorer = () => {
    const [graphData, setGraphData] = useState({ nodes: [], links: [] });
    const [initialGraph, setInitialGraph] = useState({ nodes: [], links: [] });
    const [loading, setLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState(null);
    const [documents, setDocuments] = useState([]);
    const [pathA, setPathA] = useState('');
    const [pathB, setPathB] = useState('');
    const [pathLoading, setPathLoading] = useState(false);

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
            const res = await axios.get('/api/graph/relations', { params: { limit: 200 } });
            const transformed = transformGraph(res.data || {});
            setGraphData(transformed);
            setInitialGraph(transformed);
        } catch (e) {
            // ignore, keep empty graph
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
                `<div style="font-size:11px;opacity:0.8;margin-top:4px;">source: ${sourceDoc}</div>`,
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
                    加载中…
                </div>
            )}
            <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
                <div
                    style={{
                        position: 'absolute',
                        top: 10,
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
                            placeholder="Entity A"
                            style={{ width: 120, fontSize: 12, padding: '2px 6px', borderRadius: 4, border: '1px solid #4b5563', background: 'rgba(15,23,42,0.9)', color: '#e5e7eb' }}
                        />
                        <span style={{ opacity: 0.7 }}>→</span>
                        <input
                            value={pathB}
                            onChange={(e) => setPathB(e.target.value)}
                            placeholder="Entity B"
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
                            {pathLoading ? 'Searching…' : 'Find path'}
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
                            Reset view
                        </button>
                    </form>
                </div>
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

            <div
                style={{
                    width: 320,
                    maxWidth: '30%',
                    borderLeft: '1px solid rgba(148,163,184,0.2)',
                    background: 'rgba(15,23,42,0.92)',
                    color: '#e5e7eb',
                    padding: '10px 12px',
                    fontSize: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                }}
            >
                <div style={{ fontWeight: 600, fontSize: 13 }}>节点详情</div>
                {selectedNode ? (
                    <>
                        <div>{nodeDisplayName(selectedNode)}</div>
                        <div style={{ opacity: 0.75, marginBottom: 4 }}>
                            {(selectedNode.raw?.labels || []).join(', ') || selectedNode.type}
                        </div>
                        <div style={{ fontWeight: 500, marginTop: 4 }}>相关文档</div>
                        {documents.length === 0 && (
                            <div style={{ opacity: 0.7 }}>暂无关联文档或暂未索引。</div>
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
                                        {doc.text || '（无摘要文本）'}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </>
                ) : (
                    <div style={{ opacity: 0.7 }}>点击左侧图中的任意节点，查看关联文档。</div>
                )}
            </div>
        </div>
    );
};

export default GraphExplorer;

