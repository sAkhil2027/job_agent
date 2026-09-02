import json
import logging
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

logger = logging.getLogger(__name__)

class EmbeddingService:
    # Use a small, fast model for local embeddings
    MODEL_NAME = "all-MiniLM-L6-v2"
    _model = None

    @classmethod
    def get_model(cls):
        """Lazy load the model to save memory until needed."""
        if cls._model is None:
            logger.info(f"Loading embedding model: {cls.MODEL_NAME}...")
            cls._model = SentenceTransformer(cls.MODEL_NAME)
            logger.info("Embedding model loaded.")
        return cls._model

    @classmethod
    def generate_embedding(cls, text: str) -> list[float]:
        """Generate a vector embedding for a given text."""
        model = cls.get_model()
        # encode returns a numpy array, convert to list for easy JSON serialization
        embedding = model.encode(text)
        return embedding.tolist()

    @classmethod
    def generate_embeddings(cls, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of texts in a batch."""
        if not texts:
            return []
        model = cls.get_model()
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    @classmethod
    def compute_similarity(cls, embed1: list[float], embed2: list[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        vec1 = np.array(embed1).reshape(1, -1)
        vec2 = np.array(embed2).reshape(1, -1)
        sim = cosine_similarity(vec1, vec2)
        return float(sim[0][0])
