from core.graph_engine import GraphEngine
from configs.config import settings

def check_nodes():
    engine = GraphEngine()
    query = "MATCH (n) RETURN n.name as name, labels(n) as label LIMIT 50"
    with engine.graph_store._driver.session() as session:
        result = session.run(query)
        nodes = [(record['name'], record['label']) for record in result]
        print(f"Total nodes retrieved: {len(nodes)}")
        for name, label in nodes:
            print(f"Node: {name} [{label}]")

if __name__ == "__main__":
    check_nodes()
