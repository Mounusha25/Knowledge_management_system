"""
Advanced Document Processing Module

This module provides sophisticated document processing capabilities with multiple
chunking strategies for optimal RAG performance.
"""

import hashlib
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.document_loaders import PyPDFLoader, TextLoader
import logging
import time

logger = logging.getLogger(__name__)

class ChunkingStrategy(ABC):
    """Abstract base class for different chunking strategies"""
    
    @abstractmethod
    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Chunk text using the specific strategy"""
        pass

class RecursiveChunker(ChunkingStrategy):
    """Recursive character-based chunking strategy"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
    
    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Chunk text using recursive character splitting"""
        chunks = self.splitter.split_text(text)
        
        result = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = metadata.copy()
            chunk_metadata.update({
                'chunk_index': i,
                'chunk_size': len(chunk),
                'chunking_strategy': 'recursive'
            })
            
            result.append({
                'content': chunk,
                'metadata': chunk_metadata,
                'chunk_id': hashlib.md5(f"{metadata.get('filename', 'unknown')}_{i}_{chunk[:50]}".encode()).hexdigest()
            })
        
        return result

class SemanticChunker(ChunkingStrategy):
    """Semantic-based chunking strategy (simplified implementation)"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Chunk text using semantic boundaries (paragraph-based)"""
        # Split by paragraphs first
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        chunks = []
        current_chunk = ""
        chunk_index = 0
        
        for paragraph in paragraphs:
            # If adding this paragraph would exceed chunk size, finalize current chunk
            if len(current_chunk) + len(paragraph) > self.chunk_size and current_chunk:
                chunk_metadata = metadata.copy()
                chunk_metadata.update({
                    'chunk_index': chunk_index,
                    'chunk_size': len(current_chunk),
                    'chunking_strategy': 'semantic'
                })
                
                chunks.append({
                    'content': current_chunk.strip(),
                    'metadata': chunk_metadata,
                    'chunk_id': hashlib.md5(f"{metadata.get('filename', 'unknown')}_{chunk_index}_{current_chunk[:50]}".encode()).hexdigest()
                })
                
                # Start new chunk with overlap
                overlap_text = current_chunk[-self.chunk_overlap:] if len(current_chunk) > self.chunk_overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + paragraph
                chunk_index += 1
            else:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
        
        # Add the last chunk
        if current_chunk:
            chunk_metadata = metadata.copy()
            chunk_metadata.update({
                'chunk_index': chunk_index,
                'chunk_size': len(current_chunk),
                'chunking_strategy': 'semantic'
            })
            
            chunks.append({
                'content': current_chunk.strip(),
                'metadata': chunk_metadata,
                'chunk_id': hashlib.md5(f"{metadata.get('filename', 'unknown')}_{chunk_index}_{current_chunk[:50]}".encode()).hexdigest()
            })
        
        return chunks

class HybridChunker(ChunkingStrategy):
    """Hybrid chunking strategy combining semantic and recursive approaches"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.semantic_chunker = SemanticChunker(chunk_size, chunk_overlap)
        self.recursive_chunker = RecursiveChunker(chunk_size, chunk_overlap)
    
    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Use semantic chunking first, then recursive for oversized chunks"""
        # Try semantic chunking first
        semantic_chunks = self.semantic_chunker.chunk_text(text, metadata)
        
        # Check if any chunks are too large and need recursive splitting
        final_chunks = []
        for chunk in semantic_chunks:
            if len(chunk['content']) > self.semantic_chunker.chunk_size * 1.5:
                # Split large chunks recursively
                recursive_chunks = self.recursive_chunker.chunk_text(chunk['content'], chunk['metadata'])
                for rc in recursive_chunks:
                    rc['metadata']['chunking_strategy'] = 'hybrid'
                    final_chunks.append(rc)
            else:
                chunk['metadata']['chunking_strategy'] = 'hybrid'
                final_chunks.append(chunk)
        
        return final_chunks

class DocumentProcessor:
    """Advanced document processor with multiple chunking strategies"""
    
    SUPPORTED_EXTENSIONS = {'.pdf', '.txt', '.md'}
    
    def __init__(self, chunking_strategy: ChunkingStrategy = None, max_file_size_mb: int = 10):
        self.chunking_strategy = chunking_strategy or HybridChunker()
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.processed_hashes = set()  # For deduplication
        
        logger.info(f"DocumentProcessor initialized with {self.chunking_strategy.__class__.__name__}")
    
    def validate_file(self, file_path: str) -> bool:
        """Validate file before processing"""
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                logger.error(f"File does not exist: {file_path}")
                return False
            
            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size_bytes:
                logger.error(f"File too large: {file_size} bytes (max: {self.max_file_size_bytes})")
                return False
            
            # Check file extension
            _, ext = os.path.splitext(file_path.lower())
            if ext not in self.SUPPORTED_EXTENSIONS:
                logger.error(f"Unsupported file type: {ext}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"File validation error: {str(e)}")
            return False
    
    def extract_text(self, file_path: str) -> Optional[str]:
        """Extract text from various file formats"""
        try:
            _, ext = os.path.splitext(file_path.lower())
            logger.info(f"Extracting text from {file_path} with extension {ext}")
            
            if ext == '.pdf':
                logger.info("Using PyPDFLoader for PDF file")
                loader = PyPDFLoader(file_path)
                documents = loader.load()
                text = "\n\n".join([doc.page_content for doc in documents])
                logger.info(f"PDF extraction completed. Text length: {len(text)}")
                return text
            
            elif ext in ['.txt', '.md']:
                logger.info(f"Using TextLoader for {ext} file")
                loader = TextLoader(file_path)
                documents = loader.load()
                text = documents[0].page_content if documents else ""
                logger.info(f"Text extraction completed. Text length: {len(text)}")
                return text
            
            else:
                logger.error(f"Unsupported file type: {ext}")
                return None
                
        except Exception as e:
            logger.error(f"Text extraction error for {file_path}: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def generate_content_hash(self, content: str) -> str:
        """Generate SHA-256 hash for content deduplication"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def is_duplicate(self, content: str) -> bool:
        """Check if content has been processed before"""
        content_hash = self.generate_content_hash(content)
        if content_hash in self.processed_hashes:
            return True
        self.processed_hashes.add(content_hash)
        return False
    
    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract comprehensive metadata from file"""
        try:
            stat = os.stat(file_path)
            filename = os.path.basename(file_path)
            
            return {
                'filename': filename,
                'file_path': file_path,
                'file_size': stat.st_size,
                'file_extension': os.path.splitext(filename)[1].lower(),
                'created_time': stat.st_ctime,
                'modified_time': stat.st_mtime,
                'processing_timestamp': time.time()
            }
            
        except Exception as e:
            logger.error(f"Metadata extraction error: {str(e)}")
            return {'filename': os.path.basename(file_path)}
    
    def process_document(self, file_path: str) -> List[Dict[str, Any]]:
        """Process a document and return chunks with metadata"""
        try:
            # Validate file
            if not self.validate_file(file_path):
                return []
            
            # Extract text
            text = self.extract_text(file_path)
            if not text:
                logger.error(f"No text extracted from {file_path}")
                return []
            
            # Check for duplicates
            if self.is_duplicate(text):
                logger.info(f"Duplicate content detected, skipping: {file_path}")
                return []
            
            # Extract metadata
            metadata = self.extract_metadata(file_path)
            metadata['content_hash'] = self.generate_content_hash(text)
            
            # Chunk the text
            chunks = self.chunking_strategy.chunk_text(text, metadata)
            
            logger.info(f"Processed {file_path}: {len(chunks)} chunks created")
            return chunks
            
        except Exception as e:
            logger.error(f"Document processing error for {file_path}: {str(e)}")
            return []
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return {
            'processed_documents': len(self.processed_hashes),
            'chunking_strategy': self.chunking_strategy.__class__.__name__,
            'max_file_size_mb': self.max_file_size_bytes / (1024 * 1024),
            'supported_extensions': list(self.SUPPORTED_EXTENSIONS)
        }
