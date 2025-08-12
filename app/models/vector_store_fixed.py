import chromadb
from chromadb.config import Settings
from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from typing import List, Dict, Any, Optional, Tuple
import logging
import time
import hashlib
import json
import numpy as np
import re
from config import Config

logger = logging.getLogger(__name__)

class EnhancedVectorStore:
    """Enhanced vector store with optimized search for any kind of documents"""
    
    def __init__(self, embedding_model: str = None, persist_directory: str = None):
        self.embedding_model = embedding_model or Config.EMBEDDING_MODEL
        self.persist_directory = persist_directory or Config.VECTOR_DB_PATH
        
        # Initialize embeddings
        self.embeddings = HuggingFaceEmbeddings(
            model_name=self.embedding_model,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=self.persist_directory,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Initialize vector store
        self.vectorstore = Chroma(
            client=self.client,
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory,
            collection_name="documents"
        )
        
        # Query cache for performance
        self.query_cache = {}
        self.cache_ttl = Config.CACHE_TTL_SECONDS
        
        logger.info(f"Initialized EnhancedVectorStore with model: {self.embedding_model}")

    def add_documents(self, documents: List[Document]) -> List[str]:
        """Add documents to the vector store"""
        try:
            # Remove duplicates
            unique_docs = self._remove_duplicates(documents)
            logger.info(f"Adding {len(unique_docs)} unique documents")
            
            # Add to vector store
            result = self.vectorstore.add_documents(unique_docs)
            
            logger.info(f"Successfully added {len(unique_docs)} documents")
            return result
            
        except Exception as e:
            logger.error(f"Error adding documents: {str(e)}")
            raise

    def similarity_search(self, query, k=7, threshold=0.15):
        """
        Optimized similarity search that works with any kind of documents
        """
        try:
            logger.info(f"Performing optimized similarity search for: {query[:50]}...")
            
            # Log vector store statistics  
            stats = self.get_collection_stats()
            logger.info(f"Vector store stats: {stats}")
            
            # Enhanced query preprocessing
            processed_query = self._preprocess_query(query)
            
            # Use ChromaDB with optimized parameters
            results = self.vectorstore.similarity_search_with_score(
                processed_query, 
                k=min(k * 2, 20)  # Get more candidates
            )
            
            documents = []
            if results:
                logger.info(f"Found {len(results)} candidate documents")
                
                for i, (doc, score) in enumerate(results):
                    # Convert score to similarity
                    similarity_score = 1 - score if score <= 1 else 1 / (1 + score)
                    
                    # Adaptive threshold
                    adjusted_threshold = self._get_adaptive_threshold(query, threshold)
                    
                    if similarity_score >= adjusted_threshold:
                        # Enhanced relevance scoring
                        enhanced_score = self._calculate_enhanced_relevance(
                            query, doc.page_content, similarity_score, doc.metadata
                        )
                        
                        if i < 3:  # Debug first few
                            logger.info(f"Result {i}: score={enhanced_score:.3f}, {doc.page_content[:100]}...")
                        
                        documents.append({
                            'content': doc.page_content,
                            'metadata': {
                                **doc.metadata,
                                'relevance_score': round(enhanced_score, 3),
                                'search_type': 'optimized_semantic'
                            }
                        })
            
            # Sort by relevance
            documents.sort(key=lambda x: x['metadata']['relevance_score'], reverse=True)
            final_docs = documents[:k]
            
            logger.info(f"Returning {len(final_docs)} optimized documents")
            return final_docs
            
        except Exception as e:
            logger.error(f"Error in optimized search, using fallback: {str(e)}")
            # Simple fallback
            try:
                basic_results = self.vectorstore.similarity_search(query, k=k)
                return [{
                    'content': doc.page_content,
                    'metadata': {**doc.metadata, 'search_type': 'fallback_basic'}
                } for doc in basic_results]
            except Exception as fallback_error:
                logger.error(f"Fallback search failed: {str(fallback_error)}")
                return []

    def _preprocess_query(self, query):
        """Enhanced query preprocessing for better matching"""
        # Remove extra whitespace
        query = re.sub(r'\s+', ' ', query.strip())
        
        # Expand common abbreviations
        abbreviations = {
            'NHD': 'National Hydrography Dataset',
            'USGS': 'United States Geological Survey',
            'GIS': 'Geographic Information System'
        }
        
        for abbrev, expansion in abbreviations.items():
            if abbrev in query and expansion not in query:
                query = f"{query} {expansion}"
        
        return query
    
    def _get_adaptive_threshold(self, query, base_threshold):
        """Adjust threshold based on query characteristics"""
        # Lower threshold for comparison queries
        if any(term in query.lower() for term in ['difference', 'compare', 'versus', 'vs']):
            return max(0.1, base_threshold - 0.05)
        
        # Lower threshold for short queries
        if len(query.split()) <= 3:
            return max(0.05, base_threshold - 0.1)
        
        return base_threshold
    
    def _calculate_enhanced_relevance(self, query, document, similarity_score, metadata):
        """Calculate enhanced relevance score"""
        score = similarity_score
        
        # Boost for keyword matches
        query_words = set(query.lower().split())
        doc_words = set(document.lower().split())
        keyword_overlap = len(query_words.intersection(doc_words)) / len(query_words)
        score += keyword_overlap * 0.1
        
        # Boost for substantial content
        if len(document) > 100:
            score += 0.05
        
        return min(1.0, score)

    def _remove_duplicates(self, documents):
        """Remove duplicate documents"""
        seen_hashes = set()
        unique_docs = []
        
        for doc in documents:
            content_hash = hashlib.md5(doc.page_content.encode()).hexdigest()
            
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                doc.metadata['content_hash'] = content_hash
                unique_docs.append(doc)
        
        logger.info(f"Removed {len(documents) - len(unique_docs)} duplicates")
        return unique_docs

    def get_collection_stats(self):
        """Get vector store statistics"""
        try:
            collection = self.client.get_collection("documents")
            count = collection.count()
            return {
                'total_documents': count,
                'embedding_model': self.embedding_model,
                'cache_size': len(self.query_cache),
                'last_updated': time.time()
            }
        except Exception as e:
            logger.warning(f"Could not get collection stats: {str(e)}")
            return {
                'total_documents': 0,
                'embedding_model': self.embedding_model,
                'cache_size': 0,
                'last_updated': time.time()
            }

# Backward compatibility
class VectorStore(EnhancedVectorStore):
    """Backward compatibility alias"""
    pass
