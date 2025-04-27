import os
import json
import time
from typing import Dict, List, Optional, Any

class DownloadState:
    """Class to manage download state persistence for resumable downloads."""
    
    def __init__(self, state_dir: str = ".download_state"):
        """
        Initialize the download state manager.
        
        Args:
            state_dir: Directory to store download state files
        """
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
    
    def _get_state_path(self, filepath: str) -> str:
        """Get the path to the state file for a download."""
        # Create a safe filename from the download path
        safe_name = filepath.replace('/', '_').replace('\\', '_').replace(':', '_')
        return os.path.join(self.state_dir, f"{safe_name}.state")
    
    def save_state(self, filepath: str, url: str, downloaded_chunks: Dict[int, int], 
                  total_size: int, chunk_ranges: List[tuple]) -> None:
        """
        Save the download state for resuming later.
        
        Args:
            filepath: Path to the file being downloaded
            url: URL being downloaded
            downloaded_chunks: Dict mapping chunk_id to bytes downloaded
            total_size: Total size of the file
            chunk_ranges: List of (start, end) tuples for each chunk
        """
        state = {
            'filepath': filepath,
            'url': url,
            'downloaded_chunks': downloaded_chunks,
            'total_size': total_size,
            'chunk_ranges': chunk_ranges,
            'timestamp': time.time()
        }
        
        state_path = self._get_state_path(filepath)
        with open(state_path, 'w') as f:
            json.dump(state, f)
    
    def load_state(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Load the download state for a file.
        
        Args:
            filepath: Path to the file
            
        Returns:
            Download state dict or None if no state exists
        """
        state_path = self._get_state_path(filepath)
        if not os.path.exists(state_path):
            return None
            
        try:
            with open(state_path, 'r') as f:
                state = json.load(f)
                
            # Validate the state
            required_keys = ['filepath', 'url', 'downloaded_chunks', 'total_size', 'chunk_ranges']
            if all(key in state for key in required_keys):
                return state
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading download state: {e}")
            
        return None
    
    def clear_state(self, filepath: str) -> None:
        """
        Clear the download state for a file.
        
        Args:
            filepath: Path to the file
        """
        state_path = self._get_state_path(filepath)
        if os.path.exists(state_path):
            os.remove(state_path)
    
    def get_incomplete_downloads(self) -> List[Dict[str, Any]]:
        """
        Get a list of all incomplete downloads.
        
        Returns:
            List of download state dicts
        """
        incomplete = []
        
        if not os.path.exists(self.state_dir):
            return incomplete
            
        for filename in os.listdir(self.state_dir):
            if filename.endswith('.state'):
                try:
                    with open(os.path.join(self.state_dir, filename), 'r') as f:
                        state = json.load(f)
                        incomplete.append(state)
                except (json.JSONDecodeError, IOError):
                    continue
                    
        return incomplete
