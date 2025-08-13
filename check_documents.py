#!/usr/bin/env python3
"""
Quick script to check actual document count in vector database
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.models.vector_store_fixed import EnhancedVectorStore

def check_document_count():
    try:
        # Initialize vector store
        vector_store = EnhancedVectorStore()
        
        # Get collection stats
        stats = vector_store.get_collection_stats()
        
        print("=== Vector Database Statistics ===")
        print(f"Total documents: {stats.get('total_documents', 0)}")
        print(f"Embedding model: {stats.get('embedding_model', 'Unknown')}")
        print(f"Cache size: {stats.get('cache_size', 0)}")
        
        # Get database size
        import os
        db_path = "vector_db/chroma.sqlite3"
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            size_mb = size_bytes / (1024 * 1024)
            print(f"Database size: {size_mb:.1f} MB ({size_bytes:,} bytes)")
        
        return stats.get('total_documents', 0)
        
    except Exception as e:
        print(f"Error checking document count: {str(e)}")
        return 0

if __name__ == "__main__":
    count = check_document_count()
    print(f"\n📊 Your RAG system currently has {count} documents in the vector database.")
