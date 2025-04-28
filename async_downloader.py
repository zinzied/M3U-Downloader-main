import aiohttp
import aiofiles
import asyncio
from typing import Callable, Optional, Dict, List, Tuple
import os
from concurrent.futures import ThreadPoolExecutor
from download_optimizer import DownloadOptimizer, ConnectionPool
import time
from iptv_auth import IPTVAuthenticator
from utils import format_speed
import logging
from download_state import DownloadState

# Setup logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('async_downloader')

class AsyncDownloader:
    def __init__(self,
                 max_concurrent: int = 3,
                 max_chunks: int = 4,
                 max_speed_limit: Optional[int] = None,
                 enable_resume: bool = True,
                 enable_chunked: bool = True):
        self.max_concurrent = max_concurrent
        self.max_chunks = max_chunks
        self.optimizer = DownloadOptimizer(max_speed_limit=max_speed_limit)
        self.connection_pool = ConnectionPool(
            max_connections=max_concurrent * 2,
            max_per_host=max_concurrent
        )
        self.session = None
        self.retry_count = 3  # Add retry count for failed requests
        self.authenticator = IPTVAuthenticator()
        self.chunk_download_tasks = {}  # Track chunk download tasks
        self.enable_resume = enable_resume
        self.enable_chunked = enable_chunked
        self.download_state = DownloadState() if enable_resume else None
        self.active_downloads = {}

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=60)
        conn = aiohttp.TCPConnector(limit=self.max_concurrent * 2, force_close=True)
        self.session = aiohttp.ClientSession(timeout=timeout, connector=conn)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.authenticator:
            await self.authenticator.close()
        if self.session:
            await self.session.close()

    async def _refresh_token(self, url: str) -> str:
        # Extract base URL and parameters
        from urllib.parse import urlparse, parse_qs, urlencode
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        # If there's a play_token, try to refresh it
        if 'play_token' in params:
            # Construct token refresh URL - adjust this according to your server's API
            base_url = f"{parsed.scheme}://{parsed.netloc}/player_api.php"
            refresh_params = {
                'mac': params.get('mac', [''])[0],
                'type': params.get('type', [''])[0],
                'stream': params.get('stream', [''])[0],
                'refresh': '1'
            }

            async with self.session.get(f"{base_url}?{urlencode(refresh_params)}") as response:
                if response.status == 200:
                    data = await response.json()
                    if 'play_token' in data:
                        params['play_token'] = [data['play_token']]
                        # Reconstruct URL with new token
                        return parsed._replace(query=urlencode(params, doseq=True)).geturl()

        return url

    def set_speed_limit(self, limit_bytes_per_sec: Optional[int]) -> None:
        """Set a global speed limit for all downloads in bytes per second."""
        self.optimizer.set_speed_limit(limit_bytes_per_sec)

    async def _download_chunk(self,
                             url: str,
                             filepath: str,
                             start: Optional[int] = None,
                             end: Optional[int] = None,
                             chunk_id: int = 0,
                             total_chunks: int = 1,
                             total_size: int = 0,
                             progress_callback: Optional[Callable] = None,
                             resume_from: int = 0) -> int:
        """
        Download a specific chunk of a file with resume support.

        Args:
            url: URL to download from
            filepath: Path to save the file
            start: Start byte position for range request
            end: End byte position for range request
            chunk_id: ID of this chunk
            total_chunks: Total number of chunks
            total_size: Total file size
            progress_callback: Callback for progress updates
            resume_from: Byte position to resume from (for partial downloads)

        Returns:
            Number of bytes downloaded
        """
        temp_filepath = f"{filepath}.part{chunk_id}"
        bytes_downloaded = resume_from
        retries = 0

        # Track this download in active_downloads
        download_key = f"{filepath}_{chunk_id}"
        self.active_downloads[download_key] = {
            'url': url,
            'filepath': filepath,
            'chunk_id': chunk_id,
            'bytes_downloaded': bytes_downloaded,
            'total_size': (end - start + 1) if end is not None and start is not None else total_size
        }

        # Check if we need to resume and if the temp file exists
        file_mode = 'ab' if resume_from > 0 and os.path.exists(temp_filepath) else 'wb'

        while retries < self.retry_count:
            try:
                await self.connection_pool.acquire(url)

                # Prepare headers with range if specified
                headers = {
                    'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16',
                    'Accept': '*/*',
                    'Connection': 'keep-alive'
                }

                # Adjust range for resume
                if start is not None:
                    adjusted_start = start + resume_from
                    range_header = f"bytes={adjusted_start}-"
                    if end is not None:
                        range_header = f"bytes={adjusted_start}-{end}"
                    headers['Range'] = range_header
                elif resume_from > 0:
                    # If no start was specified but we're resuming
                    headers['Range'] = f"bytes={resume_from}-"

                # Apply rate limiting before making request
                chunk_size = 65536  # Default chunk size for reading from response
                await self.optimizer.apply_rate_limit(url, chunk_size)

                async with self.session.get(url, headers=headers, allow_redirects=True) as response:
                    if response.status == 458:  # Token expired
                        if retries < self.retry_count - 1:
                            url = await self.authenticator.authenticate(url)
                            retries += 1
                            await asyncio.sleep(2)
                            continue

                    # Check if range request was accepted
                    supports_resume = response.status == 206

                    if (start is not None or resume_from > 0) and not supports_resume:
                        # If server doesn't support range requests, fall back to full download
                        # but only for the first chunk
                        if chunk_id != 0:
                            raise Exception(f"Server doesn't support range requests (HTTP {response.status})")
                        logger.warning(f"Server doesn't support range requests, falling back to full download")

                        # If we were trying to resume, we need to start over
                        if resume_from > 0:
                            logger.warning(f"Server doesn't support resume, starting from beginning")
                            bytes_downloaded = 0
                            file_mode = 'wb'  # Start from scratch

                    if response.status not in (200, 206):
                        self.optimizer.handle_server_error(url)
                        raise Exception(f"HTTP {response.status}: {response.reason}")

                    # Create directory if it doesn't exist
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)

                    # Download the chunk
                    start_time = time.time()
                    last_update = start_time
                    speed_samples = []  # For calculating average speed
                    last_save_state = start_time

                    async with aiofiles.open(temp_filepath, file_mode) as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            await f.write(chunk)
                            bytes_downloaded += len(chunk)
                            speed_samples.append((time.time(), len(chunk)))

                            # Update active download tracking
                            self.active_downloads[download_key]['bytes_downloaded'] = bytes_downloaded

                            # Save download state periodically (every 5 seconds)
                            current_time = time.time()
                            if self.enable_resume and current_time - last_save_state >= 5:
                                if self.download_state and filepath in self.active_downloads:
                                    # Collect all chunk progress
                                    downloaded_chunks = {}
                                    chunk_ranges = []

                                    for key, data in self.active_downloads.items():
                                        if key.startswith(f"{filepath}_"):
                                            chunk_id = data['chunk_id']
                                            downloaded_chunks[chunk_id] = data['bytes_downloaded']

                                    # Save state for resuming later if needed
                                    self.download_state.save_state(
                                        filepath=filepath,
                                        url=url,
                                        downloaded_chunks=downloaded_chunks,
                                        total_size=total_size,
                                        chunk_ranges=[(start, end) for _, (start, end) in enumerate(self.active_downloads)]
                                    )
                                    last_save_state = current_time

                            # Apply rate limiting for next chunk
                            await self.optimizer.apply_rate_limit(url, chunk_size)

                            # Calculate speed and update progress
                            if current_time - last_update >= 0.5 and progress_callback:
                                # Remove old samples from calculation
                                speed_samples = [(t, s) for t, s in speed_samples
                                               if current_time - t <= 2]

                                if speed_samples:
                                    duration = current_time - speed_samples[0][0]
                                    if duration > 0:
                                        speed = sum(s for _, s in speed_samples) / duration
                                        speed_str = format_speed(speed)

                                        # Update optimizer with speed information
                                        self.optimizer.update_speed(url,
                                                                   sum(s for _, s in speed_samples),
                                                                   duration)

                                        if total_size > 0:
                                            # Calculate overall progress considering all chunks
                                            chunk_size_bytes = (end - start + 1) if end is not None and start is not None else total_size
                                            chunk_progress = bytes_downloaded / chunk_size_bytes
                                            overall_progress = (chunk_id / total_chunks) + (chunk_progress / total_chunks)
                                            progress = overall_progress * 100

                                            progress_callback(
                                                os.path.basename(filepath),
                                                progress,
                                                speed_str
                                            )

                                last_update = current_time

                    # Chunk download successful
                    # Remove from active downloads
                    if download_key in self.active_downloads:
                        del self.active_downloads[download_key]

                    return bytes_downloaded

            except Exception as e:
                logger.error(f"Chunk {chunk_id} download error for {url}: {str(e)}")

                # Don't delete the temp file if we're going to resume
                if not self.enable_resume and os.path.exists(temp_filepath):
                    os.remove(temp_filepath)

                if retries >= self.retry_count - 1:
                    # If we've exhausted retries but have resume enabled, keep the partial file
                    if not self.enable_resume and os.path.exists(temp_filepath):
                        os.remove(temp_filepath)
                    raise

                retries += 1
                await asyncio.sleep(2 * (retries))  # Exponential backoff
            finally:
                self.connection_pool.release(url)

        return bytes_downloaded  # Return how much we downloaded before failing

    async def _merge_chunks(self, filepath: str, chunk_count: int) -> None:
        """Merge downloaded chunks into the final file."""
        try:
            # Open the output file
            async with aiofiles.open(filepath, 'wb') as outfile:
                # Read and write each chunk
                for i in range(chunk_count):
                    chunk_path = f"{filepath}.part{i}"
                    if os.path.exists(chunk_path):
                        async with aiofiles.open(chunk_path, 'rb') as infile:
                            while True:
                                chunk = await infile.read(8192)
                                if not chunk:
                                    break
                                await outfile.write(chunk)
                        # Remove the chunk file after merging
                        os.remove(chunk_path)
                    else:
                        logger.warning(f"Chunk file {chunk_path} not found during merge")
        except Exception as e:
            logger.error(f"Error merging chunks for {filepath}: {str(e)}")
            raise

    async def download_file(self, url: str, filepath: str,
                          progress_callback: Optional[Callable[[str, float, Optional[str]], None]] = None) -> None:
        """Download a file with support for chunked downloading and resume capability."""
        retries = 0

        # Check if we have a saved state for this file
        resume_state = None
        if self.enable_resume and self.download_state:
            resume_state = self.download_state.load_state(filepath)
            if resume_state:
                logger.info(f"Found resume state for {filepath}, attempting to resume download")

        while retries < self.retry_count:
            try:
                # Authenticate and get fresh URL if needed
                if 'play_token' in url:
                    url = await self.authenticator.authenticate(url)

                # First, make a HEAD request to get file size and check if server supports range requests
                headers = {
                    'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16',
                    'Accept': '*/*',
                }

                supports_range = False
                file_size = 0

                await self.connection_pool.acquire(url)
                try:
                    async with self.session.head(url, headers=headers, allow_redirects=True) as head_response:
                        if head_response.status == 200:
                            file_size = int(head_response.headers.get('content-length', 0))
                            supports_range = 'accept-ranges' in head_response.headers and head_response.headers['accept-ranges'] == 'bytes'

                            # Check if server supports range requests
                            if 'accept-ranges' in head_response.headers:
                                if head_response.headers['accept-ranges'] == 'bytes':
                                    supports_range = True
                finally:
                    self.connection_pool.release(url)

                # Determine download strategy
                if self.enable_chunked and supports_range and file_size > 0:
                    # Use chunked downloading if enabled and supported by server
                    chunks = self.optimizer.calculate_optimal_chunks(url, file_size, self.max_chunks)

                    # If we have a resume state and the file size matches, use it
                    downloaded_chunks = {}
                    if resume_state and resume_state['total_size'] == file_size and resume_state['url'] == url:
                        downloaded_chunks = resume_state['downloaded_chunks']
                        logger.info(f"Resuming download of {filepath} with {sum(downloaded_chunks.values())} bytes already downloaded")

                    logger.info(f"Downloading {url} in {len(chunks)} chunks")

                    # Create tasks for each chunk
                    tasks = []
                    for i, (start, end) in enumerate(chunks):
                        # Check if we have already downloaded some of this chunk
                        resume_from = 0
                        if str(i) in downloaded_chunks:
                            resume_from = downloaded_chunks[str(i)]

                        task = asyncio.create_task(
                            self._download_chunk(
                                url=url,
                                filepath=filepath,
                                start=start,
                                end=end,
                                chunk_id=i,
                                total_chunks=len(chunks),
                                total_size=file_size,
                                progress_callback=progress_callback,
                                resume_from=resume_from
                            )
                        )
                        tasks.append(task)

                    # Wait for all chunks to download
                    await asyncio.gather(*tasks)

                    # Merge chunks into final file
                    await self._merge_chunks(filepath, len(chunks))

                    # Clear the download state since we've completed the download
                    if self.enable_resume and self.download_state:
                        self.download_state.clear_state(filepath)
                else:
                    # Fall back to single-chunk download
                    if not self.enable_chunked:
                        logger.info(f"Chunked downloading is disabled, using single download")
                    elif not supports_range:
                        logger.info(f"Server doesn't support range requests, using single download")
                    elif file_size <= 0:
                        logger.info(f"File size unknown, using single download")

                    # Check if we have a partial download
                    resume_from = 0
                    if resume_state and os.path.exists(f"{filepath}.part0"):
                        # Get the size of the partial file
                        resume_from = os.path.getsize(f"{filepath}.part0")
                        if resume_from > 0:
                            logger.info(f"Resuming single-chunk download from byte {resume_from}")

                    await self._download_chunk(
                        url=url,
                        filepath=filepath,
                        progress_callback=progress_callback,
                        resume_from=resume_from
                    )

                    # Rename the part file to the final filename
                    if os.path.exists(f"{filepath}.part0"):
                        os.rename(f"{filepath}.part0", filepath)

                    # Clear the download state
                    if self.enable_resume and self.download_state:
                        self.download_state.clear_state(filepath)

                # Download successful
                return

            except Exception as e:
                logger.error(f"Download error for {url}: {str(e)}")

                # If resume is enabled, don't clean up partial downloads
                if not self.enable_resume:
                    # Clean up any partial downloads
                    for i in range(self.max_chunks):
                        chunk_path = f"{filepath}.part{i}"
                        if os.path.exists(chunk_path):
                            os.remove(chunk_path)

                    if os.path.exists(filepath):
                        os.remove(filepath)

                if retries >= self.retry_count - 1:
                    raise

                retries += 1
                # Exponential backoff
                await asyncio.sleep(2 ** retries)

                # Handle server errors by adjusting rate limiting
                self.optimizer.handle_server_error(url)

class DownloadManager:
    def __init__(self,
                 max_concurrent: int = 3,
                 max_chunks: int = 4,
                 max_speed_limit: Optional[int] = None,
                 enable_resume: bool = True,
                 enable_chunked: bool = True):
        """
        Initialize the download manager.

        Args:
            max_concurrent: Maximum number of concurrent downloads
            max_chunks: Maximum number of chunks per file
            max_speed_limit: Optional speed limit in bytes per second
            enable_resume: Whether to enable resumable downloads
            enable_chunked: Whether to enable chunked downloading
        """
        self.max_concurrent = max_concurrent
        self.max_chunks = max_chunks if enable_chunked else 1
        self.max_speed_limit = max_speed_limit
        self.enable_resume = enable_resume
        self.enable_chunked = enable_chunked
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self.download_state = DownloadState() if enable_resume else None
        self.active_downloader = None

    def set_speed_limit(self, limit_bytes_per_sec: Optional[int]) -> None:
        """Set a global speed limit for all downloads in bytes per second."""
        self.max_speed_limit = limit_bytes_per_sec

    def get_incomplete_downloads(self) -> List[Dict]:
        """Get a list of all incomplete downloads that can be resumed."""
        if self.enable_resume and self.download_state:
            return self.download_state.get_incomplete_downloads()
        return []

    def resume_all_downloads(self, progress_callback: Optional[Callable] = None):
        """Resume all incomplete downloads."""
        if not self.enable_resume:
            logger.warning("Resume feature is disabled")
            return

        incomplete = self.get_incomplete_downloads()
        if not incomplete:
            logger.info("No incomplete downloads to resume")
            return

        downloads = [(state['url'], state['filepath']) for state in incomplete]
        logger.info(f"Resuming {len(downloads)} incomplete downloads")
        self.start_downloads(downloads, progress_callback)

    def start_downloads(self, downloads: list, progress_callback: Optional[Callable] = None):
        """
        Start downloading a list of files.

        Args:
            downloads: List of (url, filepath) tuples
            progress_callback: Callback function for progress updates
        """
        async def run_downloads():
            # Create a new downloader instance
            downloader = AsyncDownloader(
                self.max_concurrent,
                self.max_chunks,
                self.max_speed_limit,
                self.enable_resume,
                self.enable_chunked
            )

            # Store reference to active downloader for status updates
            self.active_downloader = downloader

            async with downloader:
                tasks = []
                for url, filepath in downloads:
                    task = asyncio.create_task(
                        downloader.download_file(url, filepath, progress_callback)
                    )
                    tasks.append(task)
                await asyncio.gather(*tasks, return_exceptions=True)

            # Clear reference when done
            self.active_downloader = None

        def run_async_downloads():
            asyncio.run(run_downloads())

        self.executor.submit(run_async_downloads)

    def get_active_downloads(self) -> Dict[str, Dict]:
        """
        Get information about active downloads including speed.

        Returns:
            Dictionary mapping filepath to download info including speed
        """
        result = {}

        # If we have an active downloader, get its active downloads
        if hasattr(self, 'active_downloader') and self.active_downloader:
            # Process active downloads to extract speed information
            for key, info in self.active_downloader.active_downloads.items():
                filepath = info['filepath']

                # Get speed from optimizer if available
                speed = 0
                if hasattr(self.active_downloader, 'optimizer'):
                    speed = self.active_downloader.optimizer.get_download_speed(info['url']) or 0

                # Combine information from multiple chunks for the same file
                if filepath in result:
                    # Update existing entry
                    result[filepath]['bytes_downloaded'] += info['bytes_downloaded']
                    # Use max speed from chunks
                    if speed > result[filepath].get('speed', 0):
                        result[filepath]['speed'] = speed
                else:
                    # Create new entry
                    result[filepath] = {
                        'url': info['url'],
                        'bytes_downloaded': info['bytes_downloaded'],
                        'total_size': info.get('total_size', 0),
                        'speed': speed
                    }

        return result

    def shutdown(self):
        """Shutdown the download manager and cancel any pending downloads."""
        self.executor.shutdown(wait=False)