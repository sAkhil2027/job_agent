import threading
import time
import json
import logging

logger = logging.getLogger(__name__)

class MetricsTracker:
    _lock = threading.Lock()
    
    # Core Counters
    total_matches = 0
    llm_calls = 0
    llm_calls_skipped = 0
    local_cache_hits = 0
    llm_cache_hits = 0
    llm_failures = 0
    
    # Latencies
    total_local_match_time = 0.0
    total_embedding_time = 0.0
    total_llm_time = 0.0
    
    # Token usage (if available)
    total_input_tokens = 0
    total_output_tokens = 0
    token_usage_records = 0
    
    # Adjustments & Confidence
    total_llm_adjustment = 0.0
    llm_adjustment_count = 0
    confidence_sum = 0.0
    
    # Distributions
    processing_modes = {
        "deterministic": 0,
        "hybrid": 0,
        "deterministic_fallback": 0
    }
    
    @classmethod
    def record_match(cls, processing_mode: str, confidence: float, local_hit: bool, llm_hit: bool, is_llm_used: bool, llm_adjustment: float, local_latency: float, embedding_latency: float, llm_latency: float, llm_failed: bool = False):
        with cls._lock:
            cls.total_matches += 1
            
            # Cache Hits
            if local_hit:
                cls.local_cache_hits += 1
            if llm_hit:
                cls.llm_cache_hits += 1
                
            # LLM stats
            if is_llm_used:
                if llm_hit:
                    cls.llm_calls_skipped += 1
                else:
                    if llm_failed:
                        cls.llm_failures += 1
                        cls.llm_calls += 1
                    else:
                        cls.llm_calls += 1
                        cls.total_llm_adjustment += abs(llm_adjustment)
                        cls.llm_adjustment_count += 1
            else:
                # LLM was completely skipped (either router offline or options use_llm=False)
                cls.llm_calls_skipped += 1
                
            # Mode distributions
            cls.processing_modes[processing_mode] = cls.processing_modes.get(processing_mode, 0) + 1
            
            # Confidence
            cls.confidence_sum += confidence
            
            # Latencies
            cls.total_local_match_time += local_latency
            cls.total_embedding_time += embedding_latency
            cls.total_llm_time += llm_latency
            
    @classmethod
    def record_tokens(cls, input_tokens: int, output_tokens: int):
        with cls._lock:
            if input_tokens > 0 or output_tokens > 0:
                cls.total_input_tokens += input_tokens
                cls.total_output_tokens += output_tokens
                cls.token_usage_records += 1

    @classmethod
    def get_metrics(cls) -> dict:
        with cls._lock:
            total = cls.total_matches or 1
            llm_total = cls.llm_calls + cls.llm_calls_skipped or 1
            llm_adj_count = cls.llm_adjustment_count or 1
            token_records = cls.token_usage_records or 1
            
            llm_avoidance_rate = (cls.total_matches - cls.llm_calls) / total
            llm_call_rate = cls.llm_calls / total
            local_cache_hit_rate = cls.local_cache_hits / total
            llm_cache_hit_rate = cls.llm_cache_hits / total
            llm_failure_rate = cls.llm_failures / (cls.llm_calls or 1)
            
            avg_local_latency = cls.total_local_match_time / total
            avg_embedding_latency = cls.total_embedding_time / total
            avg_llm_latency = cls.total_llm_time / (cls.llm_calls or 1)
            
            avg_adjustment = cls.total_llm_adjustment / llm_adj_count
            avg_confidence = cls.confidence_sum / total
            
            avg_input_tokens = cls.total_input_tokens / token_records
            avg_output_tokens = cls.total_output_tokens / token_records
            
            metrics = {
                "total_matches_processed": cls.total_matches,
                "llm_calls": cls.llm_calls,
                "llm_calls_skipped": cls.llm_calls_skipped,
                "llm_call_rate": round(llm_call_rate, 4),
                "llm_avoidance_rate": round(llm_avoidance_rate, 4),
                "local_cache_hit_rate": round(local_cache_hit_rate, 4),
                "llm_cache_hit_rate": round(llm_cache_hit_rate, 4),
                "avg_local_matching_latency_seconds": round(avg_local_latency, 4),
                "avg_embedding_latency_seconds": round(avg_embedding_latency, 4),
                "avg_llm_latency_seconds": round(avg_llm_latency, 4),
                "llm_failure_rate": round(llm_failure_rate, 4),
                "avg_llm_adjustment": round(avg_adjustment, 2),
                "avg_input_tokens": round(avg_input_tokens, 1) if cls.total_input_tokens else None,
                "avg_output_tokens": round(avg_output_tokens, 1) if cls.total_output_tokens else None,
                "processing_mode_distribution": dict(cls.processing_modes),
                "avg_confidence": round(avg_confidence, 2)
            }
            logger.info(f"Observability Metrics: {json.dumps(metrics)}")
            return metrics
