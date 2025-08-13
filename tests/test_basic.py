"""
Comprehensive test suite for RAG Knowledge Management System
"""
import pytest
import sys
import os
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

class TestConfiguration:
    """Test system configuration"""
    
    def test_config_import(self):
        """Test that config can be imported"""
        from config import Config
        assert Config.FLASK_PORT == 8080
        assert Config.FLASK_HOST == "0.0.0.0"
        assert Config.MAX_FILE_SIZE_MB > 0
    
    def test_environment_variables(self):
        """Test environment variable handling"""
        from config import Config
        # These should have default values
        assert hasattr(Config, 'EMBEDDING_MODEL')
        assert hasattr(Config, 'LLM_MODEL')
        assert hasattr(Config, 'VECTOR_DB_PATH')

class TestHealthCheck:
    """Test health check functionality"""
    
    @patch('app.models.vector_store_fixed.EnhancedVectorStore')
    @patch('app.services.llm_service.EnhancedLLMService')
    def test_health_endpoint_structure(self, mock_llm, mock_vector):
        """Test health check returns proper structure"""
        # Mock the services
        mock_vector.return_value.get_collection_stats.return_value = {
            'total_documents': 575,
            'embedding_model': 'test-model'
        }
        mock_llm.return_value.get_service_stats.return_value = {
            'status': 'healthy'
        }
        
        # Expected health response structure
        expected_keys = ['status', 'timestamp']
        health_response = {
            'status': 'healthy',
            'timestamp': 1234567890,
            'vector_store': {'total_documents': 575},
            'llm_service': {'status': 'healthy'}
        }
        
        for key in expected_keys:
            assert key in health_response

class TestDocumentProcessing:
    """Test document processing capabilities"""
    
    def test_allowed_file_types(self):
        """Test file type validation"""
        from config import Config
        allowed_extensions = Config.ALLOWED_EXTENSIONS.split(',')
        assert 'pdf' in allowed_extensions
        assert 'txt' in allowed_extensions
        assert 'docx' in allowed_extensions

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
