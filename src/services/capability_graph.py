from dataclasses import dataclass
import logging
from src.services.skills_registry import SKILL_REGISTRY

logger = logging.getLogger(__name__)

@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    weight: float
    description: str

CAPABILITY_EDGES = [
    # RAG -> Embeddings -> Vector Search -> AI Search
    GraphEdge("rag", "vector_database", 0.95, "RAG relies on vector databases for document index lookup"),
    GraphEdge("vector_database", "semantic_search", 0.90, "Vector databases power semantic search"),
    GraphEdge("semantic_search", "ai_search", 0.95, "Semantic search is the core component of AI Search systems"),
    
    # LangChain -> LLM Engineering -> AI Applications
    GraphEdge("langchain", "llm_engineering", 0.95, "LangChain is a framework for LLM orchestration and application development"),
    GraphEdge("llamaindex", "llm_engineering", 0.95, "LlamaIndex is an index-based data framework for LLMs"),
    GraphEdge("llm_engineering", "ai_applications", 0.90, "LLM engineering forms the core logic of intelligent AI Applications"),
    GraphEdge("openai", "llm_engineering", 0.90, "OpenAI APIs are commonly integrated during LLM engineering"),
    GraphEdge("huggingface", "llm_engineering", 0.85, "Hugging Face transformers are used to run open-source models in LLM applications"),
    
    # Spark/Airflow -> Distributed Computing/Workflow Orchestration -> Data Pipeline
    GraphEdge("spark", "distributed_computing", 0.95, "Apache Spark is a distributed cluster-computing framework"),
    GraphEdge("distributed_computing", "data_pipelines", 0.90, "Distributed computing scales complex Data Pipelines"),
    GraphEdge("airflow", "workflow_orchestration", 0.95, "Apache Airflow orchestrates tasks in pipelines"),
    GraphEdge("workflow_orchestration", "data_pipelines", 0.90, "Workflow orchestration schedules and manages Data Pipelines"),
    
    # Kafka -> Event Streaming -> Distributed Systems
    GraphEdge("kafka", "event_streaming", 0.95, "Kafka is a distributed platform designed for real-time Event Streaming"),
    GraphEdge("event_streaming", "distributed_systems", 0.90, "Event streaming systems are distributed architectures"),
    
    # Docker/Kubernetes -> Containerization/Container Orchestration -> Cloud Infrastructure -> DevOps
    GraphEdge("docker", "containerization", 0.95, "Docker enables sandbox Containerization"),
    GraphEdge("containerization", "cicd", 0.90, "Containerization is key to running reliable CI/CD pipelines"),
    GraphEdge("kubernetes", "container_orchestration", 0.95, "Kubernetes automates Container Orchestration"),
    GraphEdge("container_orchestration", "cloud_infrastructure", 0.90, "Container orchestration runs modern Cloud Infrastructure"),
    GraphEdge("cloud_infrastructure", "cicd", 0.90, "Cloud infrastructure hosting supports CI/CD automations"),
    GraphEdge("terraform", "cloud_infrastructure", 0.95, "Terraform provisions Cloud Infrastructure via code"),
]

def validate_capability_graph(edges: list[GraphEdge] = None) -> bool:
    """
    Validates that:
    1. Source and Target ID exist in SKILL_REGISTRY.
    2. Edge weights are between 0.0 and 1.0.
    """
    if edges is None:
        edges = CAPABILITY_EDGES
        
    valid_ids = {s.skill_id for s in SKILL_REGISTRY}
    
    for edge in edges:
        if edge.source_id not in valid_ids:
            raise ValueError(f"Capability Graph validation failed: Source ID '{edge.source_id}' is not in SKILL_REGISTRY.")
        if edge.target_id not in valid_ids:
            raise ValueError(f"Capability Graph validation failed: Target ID '{edge.target_id}' is not in SKILL_REGISTRY.")
        if not (0.0 <= edge.weight <= 1.0):
            raise ValueError(f"Capability edge '{edge.source_id} -> {edge.target_id}' has invalid weight: {edge.weight}.")
            
    logger.info("Capability Graph validated successfully.")
    return True

def find_capability_path(source_id: str, target_id: str, edges: list[GraphEdge] = None) -> tuple[float, list[str]]:
    """
    Finds a path from source_id to target_id in the Capability Graph.
    Uses simple BFS to locate the shortest path by edge count.
    Returns:
      - score (float): Cumulative score of the path (product of edge weights), or 0.0 if not reachable.
      - path_descriptions (list[str]): Step-by-step descriptions explaining the match.
    """
    if edges is None:
        edges = CAPABILITY_EDGES
        
    if source_id == target_id:
        return 1.0, [f"Exact match on {source_id}"]
        
    # Build graph adjacency list
    graph = {}
    for edge in edges:
        if edge.source_id not in graph:
            graph[edge.source_id] = []
        graph[edge.source_id].append(edge)
        
    # Queue stores: (current_node, current_path_score, path_descriptions_list, visited_set)
    queue = [(source_id, 1.0, [], {source_id})]
    
    while queue:
        curr, score, desc, visited = queue.pop(0)
        
        if curr == target_id:
            return score, desc
            
        if curr not in graph:
            continue
            
        for edge in graph[curr]:
            if edge.target_id not in visited:
                new_visited = set(visited)
                new_visited.add(edge.target_id)
                new_desc = list(desc)
                new_desc.append(edge.description)
                queue.append((edge.target_id, score * edge.weight, new_desc, new_visited))
                
    return 0.0, []
