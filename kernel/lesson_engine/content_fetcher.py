# kernel/lesson_engine/content_fetcher.py
"""
v1.0.0 — Content Fetcher for Lesson Engine

Fetches actual document content from URLs found during retrieval.
This turns "go read this URL" into "based on this content, learn X, Y, Z".

Design:
- Fetch top N resources per subdomain (default: 2)
- Extract readable text from HTML
- Summarize key learning points with LLM
- Attach content summary to EvidencePack

Rate limiting and error handling included.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Generator, List, Optional, Tuple
from urllib.parse import urlparse

# HTTP client
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

# HTML parsing
try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


# =============================================================================
# CONFIGURATION
# =============================================================================

# How many resources to fetch per subdomain
MAX_RESOURCES_PER_SUBDOMAIN = 2

# Request settings
REQUEST_TIMEOUT = 15  # seconds
REQUEST_DELAY = 0.5   # seconds between requests (rate limiting)

# Content limits
MAX_CONTENT_CHARS = 15000  # Max chars to extract from a page
MAX_SUMMARY_CHARS = 2000   # Max chars for LLM summary

# User agent - be honest about what we are
USER_AGENT = "NovaOS-LessonEngine/1.0 (Educational Content Fetcher)"

# Domains to skip (known to block bots or require auth)
SKIP_DOMAINS = {
    "linkedin.com",
    "udemy.com",
    "pluralsight.com",
    "coursera.org",
    "skillshare.com",
    "oreilly.com",
    "packtpub.com",
}

# Domains that work well
PRIORITY_DOMAINS = {
    "docs.aws.amazon.com",
    "learn.microsoft.com",
    "cloud.google.com",
    "developer.mozilla.org",
    "docs.python.org",
    "kubernetes.io",
    "docker.com",
    "nginx.org",
    "postgresql.org",
    "redis.io",
    "elastic.co",
    "splunk.com",
    "cisco.com",
    "owasp.org",
    "portswigger.net",
    "tryhackme.com",
    "hackthebox.com",
    "wikipedia.org",
    "github.com",
    "medium.com",
}


# =============================================================================
# URL FETCHING
# =============================================================================

def _should_fetch_url(url: str) -> Tuple[bool, str]:
    """
    Check if we should attempt to fetch this URL.
    
    Returns:
        (should_fetch, reason)
    """
    if not url:
        return False, "empty URL"
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        
        # Check skip list
        for skip in SKIP_DOMAINS:
            if skip in domain:
                return False, f"domain {skip} requires auth"
        
        # Check for video platforms (can't extract text)
        if any(v in domain for v in ["youtube.com", "youtu.be", "vimeo.com", "twitch.tv"]):
            return False, "video platform"
        
        # Check protocol
        if parsed.scheme not in ("http", "https"):
            return False, f"unsupported protocol {parsed.scheme}"
        
        return True, "ok"
        
    except Exception as e:
        return False, f"parse error: {e}"


def _fetch_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch content from a URL.
    
    Returns:
        (html_content, error_message)
    """
    if not _HAS_HTTPX:
        return None, "httpx not installed"
    
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            
            if response.status_code == 200:
                return response.text, None
            else:
                return None, f"HTTP {response.status_code}"
                
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.RequestError as e:
        return None, f"request error: {type(e).__name__}"
    except Exception as e:
        return None, f"error: {e}"


# =============================================================================
# CONTENT EXTRACTION
# =============================================================================

def _extract_text_from_html(html: str, max_chars: int = MAX_CONTENT_CHARS) -> str:
    """
    Extract readable text from HTML, removing navigation, scripts, etc.
    """
    if not _HAS_BS4:
        # Fallback: basic regex extraction
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text[:max_chars].strip()
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Remove unwanted elements
    for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 
                              'aside', 'form', 'button', 'iframe', 'noscript']):
        tag.decompose()
    
    # Remove elements by common class/id patterns
    for element in soup.find_all(class_=re.compile(
        r'(nav|menu|sidebar|footer|header|cookie|banner|ad|social|share|comment)', 
        re.IGNORECASE
    )):
        element.decompose()
    
    # Try to find main content area
    main_content = None
    for selector in ['main', 'article', '[role="main"]', '.content', '.post', '.entry']:
        main_content = soup.select_one(selector)
        if main_content:
            break
    
    if main_content:
        text = main_content.get_text(separator=' ', strip=True)
    else:
        text = soup.get_text(separator=' ', strip=True)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text[:max_chars].strip()


def _extract_key_sections(text: str, subdomain: str) -> Dict[str, Any]:
    """
    Extract structured information from page text.
    
    Returns dict with:
    - content: The main text content
    - headings: List of section headings found
    - code_snippets: Any code blocks detected
    - estimated_read_time: Minutes to read
    """
    # Estimate read time (avg 200 words/min)
    word_count = len(text.split())
    read_time = max(5, word_count // 200)
    
    # Try to find headings (patterns like "## Title" or all-caps lines)
    headings = []
    lines = text.split('. ')
    for line in lines[:50]:  # Check first 50 sentences
        line = line.strip()
        if len(line) < 100 and line.endswith(':'):
            headings.append(line[:-1])
        elif len(line) < 60 and line.isupper():
            headings.append(line.title())
    
    return {
        "content": text,
        "headings": headings[:10],  # Max 10 headings
        "word_count": word_count,
        "estimated_read_time": read_time,
    }


# =============================================================================
# CONTENT SUMMARIZATION
# =============================================================================

def _summarize_content_with_llm(
    content: str,
    subdomain: str,
    resource_title: str,
    llm_client: Any,
) -> Optional[str]:
    """
    Use LLM to summarize content into key learning points.
    """
    if not llm_client:
        return None
    
    # Truncate content if too long
    if len(content) > 8000:
        content = content[:8000] + "..."
    
    system = """You are a learning content summarizer. Extract the KEY learning points from educational content.

OUTPUT FORMAT:
Return a concise summary with:
1. MAIN CONCEPTS (3-5 bullet points of what this teaches)
2. KEY TERMS (important vocabulary/concepts defined)
3. PRACTICAL TAKEAWAYS (what someone can DO after reading this)

Keep total response under 500 words. Focus on actionable learning."""

    prompt = f"""Summarize this educational content about "{subdomain}":

SOURCE: {resource_title}

CONTENT:
{content}

Extract the key learning points:"""

    try:
        response = llm_client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            model="gpt-4.1-mini",  # Use mini for cost efficiency
            temperature=0.3,
            max_tokens=800,
        )
        
        if response and hasattr(response, 'content'):
            return response.content[:MAX_SUMMARY_CHARS]
        elif isinstance(response, dict) and response.get('content'):
            return response['content'][:MAX_SUMMARY_CHARS]
        elif isinstance(response, str):
            return response[:MAX_SUMMARY_CHARS]
            
    except Exception as e:
        print(f"[ContentFetcher] LLM summary error: {e}", flush=True)
    
    return None


# =============================================================================
# MAIN FETCHER
# =============================================================================

def fetch_content_for_evidence_packs(
    evidence_packs: List[Any],
    kernel: Any = None,
    max_per_subdomain: int = MAX_RESOURCES_PER_SUBDOMAIN,
) -> Generator[Dict[str, Any], None, List[Any]]:
    """
    Fetch and process content for evidence packs.
    
    This enriches EvidencePacks with actual document content.
    
    Args:
        evidence_packs: List of EvidencePack objects from retrieval
        kernel: NovaKernel for LLM access
        max_per_subdomain: Max resources to fetch per subdomain
    
    Yields:
        Progress events
    
    Returns:
        Enriched evidence packs
    """
    yield {"type": "log", "message": "[ContentFetcher] Starting content fetch phase"}
    
    # Check dependencies
    if not _HAS_HTTPX:
        yield {"type": "log", "message": "[ContentFetcher] httpx not installed, skipping fetch"}
        yield {"type": "log", "message": "[ContentFetcher] Install with: pip install httpx"}
        return evidence_packs
    
    if not _HAS_BS4:
        yield {"type": "log", "message": "[ContentFetcher] beautifulsoup4 not installed (optional, using basic extraction)"}
    
    # Get LLM client for summarization
    llm_client = getattr(kernel, 'llm_client', None) if kernel else None
    
    total_packs = len(evidence_packs)
    total_fetched = 0
    total_failed = 0
    
    for i, pack in enumerate(evidence_packs):
        subdomain = pack.subdomain
        pct = int(((i + 1) / total_packs) * 100)
        
        yield {"type": "progress", "message": f"Fetching: {subdomain[:40]}...", "percent": pct}
        
        # Get URLs to fetch (prioritize by domain quality)
        resources = pack.resources if hasattr(pack, 'resources') else []
        urls_to_fetch = []
        
        for resource in resources:
            url = resource.url if hasattr(resource, 'url') else resource.get('url', '')
            if not url:
                continue
            
            should_fetch, reason = _should_fetch_url(url)
            if should_fetch:
                # Prioritize known-good domains
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                priority = 1 if any(p in domain for p in PRIORITY_DOMAINS) else 0
                urls_to_fetch.append((priority, url, resource))
        
        # Sort by priority (higher first) and take top N
        urls_to_fetch.sort(key=lambda x: -x[0])
        urls_to_fetch = urls_to_fetch[:max_per_subdomain]
        
        if not urls_to_fetch:
            yield {"type": "log", "message": f"[ContentFetcher] No fetchable URLs for {subdomain}"}
            continue
        
        # Fetch each URL
        for priority, url, resource in urls_to_fetch:
            title = resource.title if hasattr(resource, 'title') else resource.get('title', url)
            
            yield {"type": "log", "message": f"[ContentFetcher] Fetching: {title[:50]}..."}
            
            html, error = _fetch_url(url)
            
            if error:
                yield {"type": "log", "message": f"[ContentFetcher] Failed: {error}"}
                total_failed += 1
                continue
            
            # Extract text
            text = _extract_text_from_html(html)
            
            if len(text) < 200:
                yield {"type": "log", "message": f"[ContentFetcher] Too little content extracted"}
                total_failed += 1
                continue
            
            # Extract structure
            sections = _extract_key_sections(text, subdomain)
            
            yield {"type": "log", "message": f"[ContentFetcher] Extracted {sections['word_count']} words (~{sections['estimated_read_time']} min read)"}
            
            # Summarize with LLM
            summary = None
            if llm_client:
                yield {"type": "log", "message": f"[ContentFetcher] Summarizing content..."}
                summary = _summarize_content_with_llm(text, subdomain, title, llm_client)
                if summary:
                    yield {"type": "log", "message": f"[ContentFetcher] Summary generated ({len(summary)} chars)"}
            
            # Attach content to resource
            if hasattr(resource, 'fetched_content'):
                resource.fetched_content = text[:5000]  # Store truncated
            if hasattr(resource, 'content_summary'):
                resource.content_summary = summary
            if hasattr(resource, 'extracted_headings'):
                resource.extracted_headings = sections['headings']
            if hasattr(resource, 'actual_read_time'):
                resource.actual_read_time = sections['estimated_read_time']
            
            # Also store as dict attributes for flexibility
            resource._fetched = {
                "content": text[:5000],
                "summary": summary,
                "headings": sections['headings'],
                "read_time": sections['estimated_read_time'],
                "word_count": sections['word_count'],
            }
            
            total_fetched += 1
            
            # Rate limiting
            time.sleep(REQUEST_DELAY)
    
    yield {"type": "log", "message": f"[ContentFetcher] Complete: {total_fetched} fetched, {total_failed} failed"}
    
    return evidence_packs


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_content_for_subdomain(evidence_pack: Any) -> Optional[str]:
    """
    Get the best available content for a subdomain's evidence pack.
    
    Checks for fetched content, summaries, or falls back to descriptions.
    """
    resources = evidence_pack.resources if hasattr(evidence_pack, 'resources') else []
    
    content_parts = []
    
    for resource in resources:
        # Check for fetched content
        fetched = getattr(resource, '_fetched', None)
        if fetched:
            if fetched.get('summary'):
                content_parts.append(f"## {resource.title}\n{fetched['summary']}")
            elif fetched.get('content'):
                content_parts.append(f"## {resource.title}\n{fetched['content'][:1000]}...")
            continue
        
        # Fall back to description
        desc = resource.description if hasattr(resource, 'description') else resource.get('description', '')
        if desc:
            content_parts.append(f"## {resource.title}\n{desc}")
    
    return "\n\n".join(content_parts) if content_parts else None


def has_fetched_content(evidence_pack: Any) -> bool:
    """Check if an evidence pack has any fetched content."""
    resources = evidence_pack.resources if hasattr(evidence_pack, 'resources') else []
    return any(getattr(r, '_fetched', None) for r in resources)
