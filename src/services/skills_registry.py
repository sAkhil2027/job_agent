from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

@dataclass
class Skill:
    skill_id: str
    canonical_name: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    category: str = "custom"

# Central registry of canonical skills
SKILL_REGISTRY = [
    # Programming Languages
    Skill("python", "Python", "Python", ["python", "py"], "programming_languages"),
    Skill("java", "Java", "Java", ["java"], "programming_languages"),
    Skill("javascript", "JavaScript", "JavaScript", ["javascript", "js"], "programming_languages"),
    Skill("typescript", "TypeScript", "TypeScript", ["typescript", "ts"], "programming_languages"),
    Skill("cplusplus", "C++", "C++", ["c++", "cpp"], "programming_languages"),
    Skill("csharp", "C#", "C#", ["c#", "c-sharp", "csharp"], "programming_languages"),
    Skill("ruby", "Ruby", "Ruby", ["ruby"], "programming_languages"), # Deduplicated "rails" from here
    Skill("go", "Go", "Go", ["go", "golang"], "programming_languages"),
    Skill("rust", "Rust", "Rust", ["rust"], "programming_languages"),
    Skill("swift", "Swift", "Swift", ["swift"], "programming_languages"),
    Skill("kotlin", "Kotlin", "Kotlin", ["kotlin"], "programming_languages"),
    Skill("php", "PHP", "PHP", ["php"], "programming_languages"),
    Skill("html", "HTML", "HTML", ["html", "html5"], "programming_languages"),
    Skill("css", "CSS", "CSS", ["css", "css3"], "programming_languages"),
    Skill("sql", "SQL", "SQL", ["sql"], "programming_languages"),
    Skill("nosql", "NoSQL", "NoSQL", ["nosql"], "programming_languages"),
    Skill("scala", "Scala", "Scala", ["scala"], "programming_languages"),
    Skill("shell", "Shell", "Shell", ["shell", "bash", "sh"], "programming_languages"),
    Skill("r", "R", "R", ["r"], "programming_languages"), # Stricter validation handled in normalization

    # Frameworks
    Skill("react", "React", "React", ["react", "reactjs", "react.js"], "frameworks"),
    Skill("angular", "Angular", "Angular", ["angular", "angularjs", "angular.js"], "frameworks"),
    Skill("vue", "Vue", "Vue", ["vue", "vuejs", "vue.js"], "frameworks"),
    Skill("nextjs", "Next.js", "Next.js", ["next.js", "nextjs"], "frameworks"),
    Skill("express", "Express", "Express", ["express", "expressjs", "express.js"], "frameworks"),
    Skill("django", "Django", "Django", ["django"], "frameworks"),
    Skill("flask", "Flask", "Flask", ["flask"], "frameworks"),
    Skill("fastapi", "FastAPI", "FastAPI", ["fastapi"], "frameworks"),
    Skill("springboot", "Spring Boot", "Spring Boot", ["spring boot", "springboot", "spring"], "frameworks"),
    Skill("hibernate", "Hibernate", "Hibernate", ["hibernate"], "frameworks"),
    Skill("dotnet", "ASP.NET", "ASP.NET", ["asp.net", "dotnet", ".net"], "frameworks"),
    Skill("laravel", "Laravel", "Laravel", ["laravel"], "frameworks"),
    Skill("ruby_on_rails", "Ruby on Rails", "Ruby on Rails", ["ruby on rails", "rails"], "frameworks"),

    # Libraries
    Skill("tensorflow", "TensorFlow", "TensorFlow", ["tensorflow", "tf"], "libraries"),
    Skill("pytorch", "PyTorch", "PyTorch", ["pytorch"], "libraries"),
    Skill("keras", "Keras", "Keras", ["keras"], "libraries"),
    Skill("pandas", "Pandas", "Pandas", ["pandas"], "libraries"),
    Skill("numpy", "NumPy", "NumPy", ["numpy"], "libraries"),
    Skill("scikit_learn", "Scikit-Learn", "Scikit-Learn", ["scikit-learn", "sklearn"], "libraries"),
    Skill("nltk", "NLTK", "NLTK", ["nltk"], "libraries"),
    Skill("spacy", "SpaCy", "SpaCy", ["spacy"], "libraries"),
    Skill("opencv", "OpenCV", "OpenCV", ["opencv"], "libraries"),
    Skill("jquery", "JQuery", "JQuery", ["jquery"], "libraries"),
    Skill("redux", "Redux", "Redux", ["redux"], "libraries"),

    # Cloud Platforms
    Skill("aws", "AWS", "AWS", ["aws", "amazon web services", "ec2", "s3", "rds", "lambda"], "cloud_platforms"),
    Skill("azure", "Azure", "Azure", ["azure", "microsoft azure"], "cloud_platforms"),
    Skill("gcp", "GCP", "GCP", ["gcp", "google cloud platform", "google cloud"], "cloud_platforms"),
    Skill("heroku", "Heroku", "Heroku", ["heroku"], "cloud_platforms"),

    # Databases
    Skill("postgresql", "PostgreSQL", "PostgreSQL", ["postgresql", "postgres"], "databases"),
    Skill("mysql", "MySQL", "MySQL", ["mysql"], "databases"),
    Skill("mongodb", "MongoDB", "MongoDB", ["mongodb", "mongo"], "databases"),
    Skill("redis", "Redis", "Redis", ["redis"], "databases"),
    Skill("cassandra", "Cassandra", "Cassandra", ["cassandra"], "databases"),
    Skill("elasticsearch", "Elasticsearch", "Elasticsearch", ["elasticsearch", "elastic search"], "databases"),
    Skill("sqlite", "SQLite", "SQLite", ["sqlite"], "databases"),
    Skill("oracle", "Oracle", "Oracle", ["oracle"], "databases"),
    Skill("dynamodb", "DynamoDB", "DynamoDB", ["dynamodb"], "databases"),
    Skill("firebase", "Firebase", "Firebase", ["firebase", "firestore"], "databases"),

    # DevOps
    Skill("docker", "Docker", "Docker", ["docker"], "devops"),
    Skill("kubernetes", "Kubernetes", "Kubernetes", ["kubernetes", "k8s"], "devops"),
    Skill("terraform", "Terraform", "Terraform", ["terraform"], "devops"),
    Skill("ansible", "Ansible", "Ansible", ["ansible"], "devops"),
    Skill("jenkins", "Jenkins", "Jenkins", ["jenkins"], "devops"),
    Skill("cicd", "CI/CD", "CI/CD", ["ci/cd", "continuous integration", "continuous deployment"], "devops"),
    Skill("github_actions", "GitHub Actions", "GitHub Actions", ["github actions", "gha"], "devops"),
    Skill("gitlab_ci", "GitLab CI", "GitLab CI", ["gitlab ci"], "devops"),
    Skill("chef", "Chef", "Chef", ["chef"], "devops"),
    Skill("puppet", "Puppet", "Puppet", ["puppet"], "devops"),

    # AI / ML
    Skill("ai", "AI", "AI", ["ai", "artificial intelligence"], "ai_ml"),
    Skill("machine_learning", "Machine Learning", "Machine Learning", ["machine learning", "ml"], "ai_ml"),
    Skill("deep_learning", "Deep Learning", "Deep Learning", ["deep learning", "dl"], "ai_ml"),
    Skill("nlp", "Natural Language Processing", "Natural Language Processing", ["natural language processing", "nlp"], "ai_ml"),
    Skill("computer_vision", "Computer Vision", "Computer Vision", ["computer vision", "cv"], "ai_ml"),
    Skill("reinforcement_learning", "Reinforcement Learning", "Reinforcement Learning", ["reinforcement learning", "rl"], "ai_ml"),
    Skill("neural_networks", "Neural Networks", "Neural Networks", ["neural networks", "neural network"], "ai_ml"),

    # LLM Frameworks
    Skill("llm", "LLM", "LLM", ["llm", "large language model", "large language models"], "llm_frameworks"),
    Skill("generative_ai", "Generative AI", "Generative AI", ["generative ai", "genai", "gen-ai"], "llm_frameworks"),
    Skill("langchain", "LangChain", "LangChain", ["langchain"], "llm_frameworks"),
    Skill("llamaindex", "LlamaIndex", "LlamaIndex", ["llamaindex"], "llm_frameworks"),
    Skill("huggingface", "Hugging Face", "Hugging Face", ["hugging face", "huggingface"], "llm_frameworks"),
    Skill("openai", "OpenAI", "OpenAI", ["openai", "gpt", "gpt-4"], "llm_frameworks"),
    Skill("anthropic", "Anthropic", "Anthropic", ["anthropic", "claude"], "llm_frameworks"),
    Skill("rag", "RAG", "RAG", ["rag", "retrieval-augmented generation"], "llm_frameworks"),

    # Data Engineering
    Skill("spark", "Spark", "Spark", ["spark", "apache spark"], "data_engineering"),
    Skill("hadoop", "Hadoop", "Hadoop", ["hadoop"], "data_engineering"),
    Skill("kafka", "Kafka", "Kafka", ["kafka", "apache kafka"], "data_engineering"),
    Skill("airflow", "Airflow", "Airflow", ["airflow", "apache airflow"], "data_engineering"),
    Skill("etl", "ETL", "ETL", ["etl", "extract transform load"], "data_engineering"),
    Skill("data_pipelines", "Data Pipelines", "Data Pipelines", ["data pipeline", "data pipelines"], "data_engineering"),
    Skill("snowflake", "Snowflake", "Snowflake", ["snowflake"], "data_engineering"),
    Skill("databricks", "Databricks", "Databricks", ["databricks"], "data_engineering"),

    # Frontend
    Skill("html_css", "HTML/CSS", "HTML/CSS", ["html/css"], "frontend"),
    Skill("sass", "Sass", "Sass", ["sass", "scss"], "frontend"),
    Skill("tailwind_css", "Tailwind CSS", "Tailwind CSS", ["tailwind", "tailwindcss"], "frontend"),
    Skill("bootstrap", "Bootstrap", "Bootstrap", ["bootstrap"], "frontend"),
    Skill("webpack", "Webpack", "Webpack", ["webpack"], "frontend"),
    Skill("vite", "Vite", "Vite", ["vite"], "frontend"),

    # Backend
    Skill("rest_api", "REST API", "REST API", ["rest api", "restful api", "rest apis", "rest", "restful"], "backend"), # Added "rest", "restful" synonyms here
    Skill("graphql", "GraphQL", "GraphQL", ["graphql"], "backend"),
    Skill("grpc", "gRPC", "gRPC", ["grpc"], "backend"),
    Skill("microservices", "Microservices", "Microservices", ["microservices", "microservice"], "backend"),
    Skill("websockets", "WebSockets", "WebSockets", ["websockets", "websocket"], "backend"),

    # Operating Systems
    Skill("linux", "Linux", "Linux", ["linux"], "operating_systems"),
    Skill("unix", "Unix", "Unix", ["unix"], "operating_systems"),
    Skill("windows", "Windows", "Windows", ["windows"], "operating_systems"),
    Skill("macos", "macOS", "macOS", ["macos", "osx"], "operating_systems"),

    # Version Control
    Skill("git", "Git", "Git", ["git"], "version_control"),
    Skill("github", "GitHub", "GitHub", ["github"], "version_control"),
    Skill("gitlab", "GitLab", "GitLab", ["gitlab"], "version_control"),
    Skill("bitbucket", "Bitbucket", "Bitbucket", ["bitbucket"], "version_control"),

    # Testing
    Skill("unit_testing", "Unit Testing", "Unit Testing", ["unit testing", "unit tests", "pytest", "unittest"], "testing"),
    Skill("integration_testing", "Integration Testing", "Integration Testing", ["integration testing", "integration tests"], "testing"),
    Skill("selenium", "Selenium", "Selenium", ["selenium"], "testing"),
    Skill("cypress", "Cypress", "Cypress", ["cypress"], "testing"),
    Skill("jest", "Jest", "Jest", ["jest"], "testing"),

    # Security
    Skill("cybersecurity", "Cybersecurity", "Cybersecurity", ["cybersecurity", "security"], "security"),
    Skill("oauth", "OAuth", "OAuth", ["oauth", "oauth2"], "security"),
    Skill("jwt", "JWT", "JWT", ["jwt", "json web token"], "security"),
    Skill("ssl_tls", "SSL/TLS", "SSL/TLS", ["ssl", "tls"], "security"),
    Skill("cryptography", "Cryptography", "Cryptography", ["cryptography"], "security"),

    # Networking
    Skill("tcp_ip", "TCP/IP", "TCP/IP", ["tcp/ip", "tcp", "udp"], "networking"),
    Skill("dns", "DNS", "DNS", ["dns"], "networking"),
    Skill("http", "HTTP", "HTTP", ["http", "https"], "networking"),

    # Soft Skills
    Skill("communication", "Communication", "Communication", ["communication", "verbal communication", "written communication"], "soft_skills"),
    Skill("leadership", "Leadership", "Leadership", ["leadership", "team management", "mentoring"], "soft_skills"),
    Skill("problem_solving", "Problem Solving", "Problem Solving", ["problem solving", "analytical skills"], "soft_skills"),
    Skill("teamwork", "Teamwork", "Teamwork", ["teamwork", "collaboration", "team player"], "soft_skills"),
    Skill("agile", "Agile", "Agile", ["agile", "scrum", "kanban"], "soft_skills"),
    
    # Higher-Level Capabilities
    Skill("llm_engineering", "LLM Engineering", "LLM Engineering", ["llm engineering", "llm development", "large language model engineering"], "ai_ml"),
    Skill("ai_search", "AI Search", "AI Search", ["ai search", "ai search systems", "semantic search systems"], "ai_ml"),
    Skill("distributed_systems", "Distributed Systems", "Distributed Systems", ["distributed systems", "distributed system", "distributed architecture"], "architecture"),
    Skill("containerization", "Containerization", "Containerization", ["containerization", "containers", "containerizing"], "devops"),
    Skill("container_orchestration", "Container Orchestration", "Container Orchestration", ["container orchestration", "orchestrating containers"], "devops"),
    Skill("workflow_orchestration", "Workflow Orchestration", "Workflow Orchestration", ["workflow orchestration", "orchestrating workflows", "pipeline scheduling"], "devops"),
    Skill("vector_database", "Vector Database", "Vector Database", ["vector database", "vector databases", "vector store", "vector stores"], "databases"),
    Skill("semantic_search", "Semantic Search", "Semantic Search", ["semantic search", "vector similarity search"], "ai_ml"),
    Skill("distributed_computing", "Distributed Computing", "Distributed Computing", ["distributed computing", "cluster computing"], "architecture"),
    Skill("event_streaming", "Event Streaming", "Event Streaming", ["event streaming", "event-driven architecture", "message streaming"], "architecture"),
    Skill("cloud_infrastructure", "Cloud Infrastructure", "Cloud Infrastructure", ["cloud infrastructure", "cloud architecture", "cloud provisioning"], "devops"),
    Skill("ai_applications", "AI Applications", "AI Applications", ["ai applications", "ai app development", "intelligent applications"], "ai_ml"),
]

def validate_registry(registry: list[Skill] = None) -> bool:
    """
    Validates the registry to ensure no duplicate alias ownership,
    no duplicate IDs, no empty values, etc.
    Raises ValueError if validation fails.
    """
    if registry is None:
        registry = SKILL_REGISTRY
        
    seen_ids = set()
    seen_aliases = {} # alias.lower() -> skill_id
    
    for skill in registry:
        if not skill.skill_id:
            raise ValueError("Found skill with empty skill_id.")
        if not skill.canonical_name:
            raise ValueError(f"Skill '{skill.skill_id}' has empty canonical_name.")
            
        if skill.skill_id in seen_ids:
            raise ValueError(f"Duplicate skill_id detected: '{skill.skill_id}'.")
        seen_ids.add(skill.skill_id)
        
        for alias in skill.aliases:
            if not alias or not alias.strip():
                raise ValueError(f"Skill '{skill.skill_id}' contains an empty alias.")
                
            alias_clean = alias.strip().lower()
            if alias_clean in seen_aliases:
                conflict_id = seen_aliases[alias_clean]
                raise ValueError(
                    f"Conflicting alias ownership! The alias '{alias}' is registered "
                    f"under both '{skill.skill_id}' and '{conflict_id}'."
                )
            seen_aliases[alias_clean] = skill.skill_id
            
    logger.info("Skill Registry validated successfully. No conflicts found.")
    return True
