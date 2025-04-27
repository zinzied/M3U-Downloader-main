import time
from typing import Dict, Optional, List
import asyncio
import random

class DownloadOptimizer:
    def __init__(self,
                 min_chunk_size: int = 65536,  # 64KB default min chunk size
                 max_chunk_size: int = 4194304,  # 4MB default max chunk size
                 max_speed_limit: Optional[int] = None):  # No speed limit by default
        self.speed_history: Dict[str, list] = {}
        self.chunk_sizes: Dict[str, int] = {}
        self.last_download_time: Dict[str, float] = {}
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.max_speed_limit = max_speed_limit  # In bytes per second
        self.rate_limit_tokens: Dict[str, float] = {}
        self.last_token_update: Dict[str, float] = {}
        self.backoff_factors: Dict[str, float] = {}  # For adaptive rate limiting

    def get_optimal_chunk_size(self, url: str) -> int:
        """Get optimal chunk size based on download history."""
        return self.chunk_sizes.get(url, self.min_chunk_size)

    def set_speed_limit(self, limit_bytes_per_sec: Optional[int]) -> None:
        """Set a global speed limit for all downloads in bytes per second."""
        self.max_speed_limit = limit_bytes_per_sec

    def update_speed(self, url: str, bytes_downloaded: int, duration: float) -> None:
        """Update download speed statistics."""
        if duration > 0:
            speed = bytes_downloaded / duration  # bytes per second
            if url not in self.speed_history:
                self.speed_history[url] = []
            self.speed_history[url].append(speed)

            # Keep only last 5 measurements
            if len(self.speed_history[url]) > 5:
                self.speed_history[url].pop(0)

            # Adjust chunk size based on speed
            avg_speed = sum(self.speed_history[url]) / len(self.speed_history[url])

            # More aggressive chunk size adjustment
            # Use 1/4 of average speed as chunk size for better throughput
            new_chunk_size = min(
                max(int(avg_speed / 4), self.min_chunk_size),
                self.max_chunk_size
            )
            self.chunk_sizes[url] = new_chunk_size

            # Reset backoff if we're getting good speeds
            if url in self.backoff_factors and self.backoff_factors[url] > 1.0:
                # Gradually reduce backoff when things are going well
                self.backoff_factors[url] = max(1.0, self.backoff_factors[url] * 0.9)

    def get_download_speed(self, url: str) -> Optional[float]:
        """Get current download speed in bytes per second."""
        if url in self.speed_history and self.speed_history[url]:
            return sum(self.speed_history[url]) / len(self.speed_history[url])
        return None

    async def apply_rate_limit(self, url: str, bytes_to_download: int) -> None:
        """Apply rate limiting to avoid server bans."""
        current_time = time.time()

        # Initialize rate limiting for this URL if not already done
        if url not in self.rate_limit_tokens:
            self.rate_limit_tokens[url] = bytes_to_download
            self.last_token_update[url] = current_time
            self.backoff_factors[url] = 1.0
            return

        # Calculate tokens to add based on time elapsed and speed limit
        time_elapsed = current_time - self.last_token_update[url]
        self.last_token_update[url] = current_time

        # Determine the effective speed limit
        effective_limit = self.max_speed_limit
        if effective_limit is None:
            # If no global limit, use a reasonable default based on history
            avg_speed = self.get_download_speed(url)
            if avg_speed:
                # Allow up to 120% of observed average speed
                effective_limit = int(avg_speed * 1.2)
            else:
                # Default to 5MB/s if no history
                effective_limit = 5 * 1024 * 1024

        # Apply backoff factor to effective limit
        effective_limit = effective_limit / self.backoff_factors.get(url, 1.0)

        # Add tokens based on time elapsed and limit
        tokens_to_add = time_elapsed * effective_limit
        self.rate_limit_tokens[url] = min(
            self.rate_limit_tokens[url] + tokens_to_add,
            self.max_chunk_size * 2  # Don't accumulate too many tokens
        )

        # If we need more tokens than available, sleep
        if bytes_to_download > self.rate_limit_tokens[url]:
            # Calculate sleep time needed to accumulate enough tokens
            deficit = bytes_to_download - self.rate_limit_tokens[url]
            sleep_time = deficit / effective_limit

            # Add a small random factor to avoid synchronized requests
            sleep_time *= (1.0 + random.uniform(0, 0.1))

            # Sleep to respect rate limit
            await asyncio.sleep(sleep_time)
            self.rate_limit_tokens[url] = 0  # Reset tokens after sleep
        else:
            # Consume tokens
            self.rate_limit_tokens[url] -= bytes_to_download

    def handle_server_error(self, url: str) -> None:
        """Handle server errors by increasing backoff factor."""
        if url not in self.backoff_factors:
            self.backoff_factors[url] = 1.0

        # Increase backoff factor (up to 8x slowdown)
        self.backoff_factors[url] = min(8.0, self.backoff_factors[url] * 1.5)

    def calculate_optimal_chunks(self, url: str, file_size: int, max_chunks: int = 8) -> List[tuple]:
        """Calculate optimal chunk ranges for parallel downloading."""
        if file_size <= 0:
            return [(0, None)]  # Can't chunk if size unknown

        # Determine number of chunks based on file size
        # For small files, use fewer chunks to avoid overhead
        if file_size < 1024 * 1024:  # Less than 1MB
            num_chunks = 1
        elif file_size < 10 * 1024 * 1024:  # Less than 10MB
            num_chunks = min(2, max_chunks)
        elif file_size < 100 * 1024 * 1024:  # Less than 100MB
            num_chunks = min(4, max_chunks)
        else:
            num_chunks = max_chunks

        # Calculate chunk size
        chunk_size = file_size // num_chunks

        # Create chunks with ranges
        chunks = []
        for i in range(num_chunks):
            start = i * chunk_size
            # Last chunk gets the remainder
            end = None if i == num_chunks - 1 else (i + 1) * chunk_size - 1
            chunks.append((start, end))

        return chunks

class ConnectionPool:
    def __init__(self, max_connections: int = 10, max_per_host: int = 4):
        self.semaphore = asyncio.Semaphore(max_connections)
        self.active_connections: Dict[str, int] = {}
        self.host_connections: Dict[str, int] = {}
        self.host_semaphores: Dict[str, asyncio.Semaphore] = {}
        self.max_per_host = max_per_host

    def _get_host(self, url: str) -> str:
        """Extract host from URL."""
        from urllib.parse import urlparse
        return urlparse(url).netloc

    async def acquire(self, url: str):
        """Acquire a connection from the pool with per-host limiting."""
        # Get host from URL
        host = self._get_host(url)

        # Create host semaphore if it doesn't exist
        if host not in self.host_semaphores:
            self.host_semaphores[host] = asyncio.Semaphore(self.max_per_host)

        # Acquire both global and host-specific semaphores
        await self.semaphore.acquire()
        await self.host_semaphores[host].acquire()

        # Update connection counters
        self.active_connections[url] = self.active_connections.get(url, 0) + 1
        self.host_connections[host] = self.host_connections.get(host, 0) + 1

    def release(self, url: str):
        """Release a connection back to the pool."""
        host = self._get_host(url)

        # Update URL-specific counter
        if url in self.active_connections:
            self.active_connections[url] -= 1
            if self.active_connections[url] <= 0:
                del self.active_connections[url]

        # Update host-specific counter
        if host in self.host_connections:
            self.host_connections[host] -= 1
            if self.host_connections[host] <= 0:
                del self.host_connections[host]

        # Release semaphores
        if host in self.host_semaphores:
            self.host_semaphores[host].release()
        self.semaphore.release()

    def get_active_connections(self, url: str) -> int:
        """Get number of active connections for a URL."""
        return self.active_connections.get(url, 0)

    def get_host_connections(self, url: str) -> int:
        """Get number of active connections for a host."""
        host = self._get_host(url)
        return self.host_connections.get(host, 0)