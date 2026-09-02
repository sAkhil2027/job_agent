from dataclasses import dataclass
import logging
from src.services.skills_registry import SKILL_REGISTRY

logger = logging.getLogger(__name__)

@dataclass
class SkillRelationship:
    source_id: str             # Candidate skill ID
    target_id: str             # Required JD skill ID
    relationship_type: str     # e.g., "Cloud Platform"
    transferability_score: float # e.g., 0.90
    description: str           # Explanation for explainability

# Directional relationships registry
RELATIONSHIP_REGISTRY = [
    # Cloud Platforms
    SkillRelationship("gcp", "aws", "Cloud Platform", 0.90, "Both are major cloud platforms with highly transferable concepts."),
    SkillRelationship("azure", "aws", "Cloud Platform", 0.80, "Both are enterprise cloud platforms with similar virtual networks and services."),
    SkillRelationship("aws", "gcp", "Cloud Platform", 0.90, "Both are major cloud platforms with highly transferable concepts."),
    SkillRelationship("azure", "gcp", "Cloud Platform", 0.80, "Both are enterprise cloud platforms with similar architecture."),
    SkillRelationship("aws", "azure", "Cloud Platform", 0.85, "Both are enterprise cloud platforms with similar services."),
    SkillRelationship("gcp", "azure", "Cloud Platform", 0.85, "Both are enterprise cloud platforms with similar services."),
    
    # SQL Databases
    SkillRelationship("postgresql", "mysql", "Relational Database", 0.95, "Both use SQL syntax and share fundamental relational index concepts."),
    SkillRelationship("sqlite", "mysql", "Relational Database", 0.75, "Both are relational engines, though MySQL is enterprise-grade client/server."),
    SkillRelationship("mysql", "postgresql", "Relational Database", 0.95, "Both use SQL syntax and share fundamental relational index concepts."),
    SkillRelationship("sqlite", "postgresql", "Relational Database", 0.70, "Both are relational engines, though PostgreSQL has much richer features."),
    
    # NoSQL Databases
    SkillRelationship("mongodb", "dynamodb", "NoSQL Database", 0.85, "Both are document databases sharing key-value store concepts."),
    SkillRelationship("dynamodb", "mongodb", "NoSQL Database", 0.85, "Both are document databases sharing key-value store concepts."),
    SkillRelationship("mongodb", "cassandra", "NoSQL Database", 0.70, "Both are NoSQL systems, though Cassandra uses a wide-column store."),
    
    # AI / Deep Learning Frameworks
    SkillRelationship("pytorch", "tensorflow", "AI Framework", 0.80, "Both are tensor computation libraries used to build neural networks."),
    SkillRelationship("tensorflow", "pytorch", "AI Framework", 0.80, "Both are tensor computation libraries used to build neural networks."),
    SkillRelationship("keras", "pytorch", "AI Framework", 0.70, "Keras is higher-level; moving to PyTorch requires learning lower-level tensor operations."),
    SkillRelationship("keras", "tensorflow", "AI Framework", 0.90, "Keras runs natively on top of TensorFlow as its high-level API."),
    
    # Frontend Frameworks
    SkillRelationship("vue", "react", "Frontend Framework", 0.75, "Both are component-based frameworks with reactive virtual DOM structures."),
    SkillRelationship("angular", "react", "Frontend Framework", 0.70, "Angular is a complete model-view-controller framework, React is library-based."),
    
    # Backend Frameworks
    SkillRelationship("fastapi", "django", "Backend Framework", 0.80, "Both are Python web frameworks; Django has a built-in admin panel and ORM."),
    SkillRelationship("flask", "django", "Backend Framework", 0.75, "Both are Python web frameworks; Django is batteries-included while Flask is micro-sized."),
    SkillRelationship("fastapi", "flask", "Backend Framework", 0.90, "Both are micro-frameworks sharing request/response lifecycle paradigms."),
]

def validate_relationships(registry: list[SkillRelationship] = None) -> bool:
    """
    Validates that:
    1. Source and Target ID exist in SKILL_REGISTRY.
    2. Transferability score is between 0.0 and 1.0.
    3. No duplicate directional pairs exist.
    """
    if registry is None:
        registry = RELATIONSHIP_REGISTRY
        
    valid_ids = {s.skill_id for s in SKILL_REGISTRY}
    seen_pairs = set()
    
    for rel in registry:
        if rel.source_id not in valid_ids:
            raise ValueError(f"Relationship validation failed: Source ID '{rel.source_id}' is not in SKILL_REGISTRY.")
        if rel.target_id not in valid_ids:
            raise ValueError(f"Relationship validation failed: Target ID '{rel.target_id}' is not in SKILL_REGISTRY.")
            
        if not (0.0 <= rel.transferability_score <= 1.0):
            raise ValueError(f"Relationship '{rel.source_id} -> {rel.target_id}' has invalid transferability score: {rel.transferability_score}.")
            
        pair = (rel.source_id, rel.target_id)
        if pair in seen_pairs:
            raise ValueError(f"Duplicate relationship detected: '{rel.source_id} -> {rel.target_id}'.")
        seen_pairs.add(pair)
        
    logger.info("Skill Relationships validated successfully. No issues found.")
    return True
