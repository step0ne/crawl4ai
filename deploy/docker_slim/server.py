from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import uvicorn
from crawl4ai import BrowserConfig, CrawlerRunConfig, AsyncWebCrawler
from crawl4ai.crawler.dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.crawler.rate_limiter import RateLimiter
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Crawl4AI Slim API")

# Models
class CrawlRequest(BaseModel):
    urls: List[str]
    browser_config: Optional[Dict] = None
    crawler_config: Optional[Dict] = None

# Helper function to get memory usage
def _get_memory_mb() -> Optional[float]:
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except:
        return None

async def handle_crawl_request(
    urls: List[str],
    browser_config: dict,
    crawler_config: dict,
) -> dict:
    """Handle crawl requests."""
    start_mem_mb = _get_memory_mb()
    start_time = time.time()
    mem_delta_mb = None
    peak_mem_mb = start_mem_mb
    
    try:
        # Normalize URLs
        urls = [('https://' + url) if not url.startswith(('http://', 'https://')) else url for url in urls]
        
        # Load configurations
        browser_config = BrowserConfig.load(browser_config or {})
        crawler_config = CrawlerRunConfig.load(crawler_config or {})

        # Create dispatcher
        dispatcher = MemoryAdaptiveDispatcher(
            memory_threshold_percent=80,  # Default threshold
            rate_limiter=RateLimiter(base_delay=(1, 2))  # Default rate limiter
        )
        
        # Run crawler
        async with AsyncWebCrawler(config=browser_config) as crawler:
            func = getattr(crawler, "arun" if len(urls) == 1 else "arun_many")
            results = await func(
                urls[0] if len(urls) == 1 else urls,
                config=crawler_config,
                dispatcher=dispatcher
            )
        
        end_mem_mb = _get_memory_mb()
        end_time = time.time()
        
        if start_mem_mb is not None and end_mem_mb is not None:
            mem_delta_mb = end_mem_mb - start_mem_mb
            peak_mem_mb = max(peak_mem_mb if peak_mem_mb else 0, end_mem_mb)
        
        logger.info(f"Memory usage: Start: {start_mem_mb} MB, End: {end_mem_mb} MB, Delta: {mem_delta_mb} MB, Peak: {peak_mem_mb} MB")
        
        return {
            "success": True,
            "results": [result.model_dump() for result in results],
            "server_processing_time_s": end_time - start_time,
            "server_memory_delta_mb": mem_delta_mb,
            "server_peak_memory_mb": peak_mem_mb
        }

    except Exception as e:
        logger.error(f"Crawl error: {str(e)}", exc_info=True)
        end_mem_mb_error = _get_memory_mb()
        if start_mem_mb is not None and end_mem_mb_error is not None:
            mem_delta_mb = end_mem_mb_error - start_mem_mb

        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "server_memory_delta_mb": mem_delta_mb,
                "server_peak_memory_mb": max(peak_mem_mb if peak_mem_mb else 0, end_mem_mb_error or 0)
            }
        )

@app.post("/crawl")
async def crawl(request: Request, crawl_request: CrawlRequest):
    """
    Crawl a list of URLs and return the results as JSON.
    """
    if not crawl_request.urls:
        raise HTTPException(400, "At least one URL required")
    
    res = await handle_crawl_request(
        urls=crawl_request.urls,
        browser_config=crawl_request.browser_config,
        crawler_config=crawl_request.crawler_config,
    )
    return JSONResponse(res)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"} 