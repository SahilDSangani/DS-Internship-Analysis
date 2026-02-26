"""
process_data.py — Internship data pipeline

Steps:
  1. Download raw internship markdown from SpeedyApply GitHub repo
  2. Parse FAANG, Quant, and General internship tables into DataFrames
  3. Scrape job descriptions from each posting URL
  4. Cache the enriched DataFrame to disk (Parquet) so step 3 only runs once

Usage:
  python process_data.py              # runs full pipeline, uses cache if available
  python process_data.py --refresh    # re-scrapes descriptions even if cache exists
"""

import argparse
import json
import re
import time
import warnings
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        return it

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RAW_MD_URL  = "https://raw.githubusercontent.com/speedyapply/2026-AI-College-Jobs/main/README.md"
RAW_MD_PATH = Path("raw_internships.md")
CACHE_PATH  = Path("general_df_with_descriptions.parquet")

SCRAPE_DELAY = 0.5  # seconds between requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Step 1: Download raw markdown
# ---------------------------------------------------------------------------

def download_raw_md(url: str = RAW_MD_URL, dest: Path = RAW_MD_PATH) -> str:
    print(f"Downloading {url} → {dest}")
    response = requests.get(url)
    response.raise_for_status()
    dest.write_text(response.text, encoding="utf-8")
    return response.text


def load_raw_md(path: Path = RAW_MD_PATH) -> str:
    if not path.exists():
        return download_raw_md(dest=path)
    print(f"Loading cached markdown from {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 2: Parse markdown tables into DataFrames
# ---------------------------------------------------------------------------

def extract_md_table(md_text: str, start_marker: str, end_marker: str):
    pattern = rf"{re.escape(start_marker)}\n(.*?)\n{re.escape(end_marker)}"
    match = re.search(pattern, md_text, flags=re.DOTALL)
    if not match:
        return None

    table_md = match.group(1).strip()
    df = pd.read_csv(StringIO(table_md), sep="|", engine="python")

    df = df.dropna(axis=1, how="all")
    df.columns = df.columns.str.strip()
    df = df.iloc[1:]  # remove markdown separator row
    df = df.apply(lambda col: col.str.strip() if col.dtype == object else col)

    if "Company" in df.columns:
        df[["Company Link", "Company"]] = df["Company"].str.extract(
            r'href="([^"]+)".*?<strong>(.*?)</strong>'
        )

    if "Posting" in df.columns:
        df["Posting"] = df["Posting"].str.extract(r'href="([^"]+)"')

    return df


def load_tables(md_text: str):
    faang_df = extract_md_table(md_text, "<!-- TABLE_FAANG_START -->", "<!-- TABLE_FAANG_END -->")
    quant_df = extract_md_table(md_text, "<!-- TABLE_QUANT_START -->", "<!-- TABLE_QUANT_END -->")
    general_df = extract_md_table(md_text, "<!-- TABLE_START -->", "<!-- TABLE_END -->")

    print(f"Faang: {faang_df.shape}  |  Quant: {quant_df.shape}  |  General: {general_df.shape}")
    return faang_df, quant_df, general_df


# ---------------------------------------------------------------------------
# Step 3: Job description scrapers (one per job board)
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 15) -> requests.Response:
    return requests.get(url, headers=_HEADERS, timeout=timeout)


def _to_clean(html_str: str) -> str:
    return BeautifulSoup(html_str, "html.parser").get_text(separator="\n", strip=True)


def _try_json_ld(soup: BeautifulSoup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}
            if data.get("@type") == "JobPosting":
                desc = data.get("description", "")
                if desc:
                    return desc, _to_clean(desc)
        except Exception:
            pass
    return np.nan, np.nan


def _extract_greenhouse(url: str):
    soup = BeautifulSoup(_get(url).text, "html.parser")
    div = soup.find("div", class_="job__description")
    if div:
        return str(div), div.get_text(separator="\n", strip=True)
    return _try_json_ld(soup)


def _extract_ashby(url: str):
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 2:
        company, job_id = parts[0], parts[1]
        api = f"https://api.ashbyhq.com/posting-api/job-board/{company}/postings/{job_id}"
        data = _get(api).json()
        raw = data.get("descriptionHtml", "")
        if raw:
            return raw, _to_clean(raw)
    return np.nan, np.nan


def _extract_workday(url: str):
    parsed = urlparse(url)
    host = parsed.hostname.split(".")
    company, wd = host[0], host[1]
    path = [p for p in parsed.path.split("/") if p]
    if len(path) >= 2:
        board = path[1]
        m = re.search(r'_([A-Za-z0-9]+)$', path[-1])
        if m:
            job_id = m.group(1)
            api = f"https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{board}/jobs/{job_id}"
            try:
                data = _get(api).json()
                desc = data.get("jobPostingInfo", {}).get("jobDescription", "")
                if desc:
                    return desc, _to_clean(desc)
            except Exception:
                pass
    try:
        soup = BeautifulSoup(_get(url).text, "html.parser")
        return _try_json_ld(soup)
    except Exception:
        return np.nan, np.nan


def _extract_lever(url: str):
    clean_url = re.sub(r'/apply/?$', '', url)
    soup = BeautifulSoup(_get(clean_url).text, "html.parser")
    div = (
        soup.find("div", {"data-qa": "job-description"})
        or soup.find("div", class_="section-wrapper")
        or soup.find("div", class_="content")
    )
    if div:
        return str(div), div.get_text(separator="\n", strip=True)
    return _try_json_ld(soup)


def _extract_smartrecruiters(url: str):
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2:
        company = parts[0]
        job_id = parts[1].split("-")[0]
        api = f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}"
        try:
            data = _get(api).json()
            sections = data.get("jobAd", {}).get("sections", {})
            texts = [
                sections.get(k, {}).get("text", "")
                for k in ("jobDescription", "qualifications", "additionalInformation")
            ]
            combined = "\n\n".join(t for t in texts if t)
            if combined:
                return combined, _to_clean(combined)
        except Exception:
            pass
    try:
        soup = BeautifulSoup(_get(url).text, "html.parser")
        div = soup.find("div", class_=re.compile(r"job-description", re.I))
        if div:
            return str(div), div.get_text(separator="\n", strip=True)
        return _try_json_ld(soup)
    except Exception:
        return np.nan, np.nan


def _extract_generic(url: str):
    soup = BeautifulSoup(_get(url).text, "html.parser")
    result = _try_json_ld(soup)
    if pd.notna(result[0]):
        return result
    for tag, attrs in [
        ("div", {"id": "job-description"}),
        ("div", {"class": "job-description"}),
        ("div", {"class": "jobDescription"}),
        ("div", {"class": "description"}),
        ("div", {"class": "posting-description"}),
        ("section", {"class": re.compile(r"description", re.I)}),
    ]:
        div = soup.find(tag, attrs)
        if div:
            return str(div), div.get_text(separator="\n", strip=True)
    return np.nan, np.nan


def fetch_description(url: str) -> tuple:
    """Route to the right extractor. Returns (raw_html, clean_text) or (NaN, NaN)."""
    if not url or (isinstance(url, float) and np.isnan(url)):
        return np.nan, np.nan
    try:
        domain = urlparse(url).hostname or ""
        if "greenhouse.io" in domain:
            raw, text = _extract_greenhouse(url)
        elif "ashbyhq.com" in domain:
            raw, text = _extract_ashby(url)
        elif "myworkdayjobs.com" in domain:
            raw, text = _extract_workday(url)
        elif "lever.co" in domain:
            raw, text = _extract_lever(url)
        elif "smartrecruiters.com" in domain:
            raw, text = _extract_smartrecruiters(url)
        else:
            raw, text = _extract_generic(url)
        return (
            raw  if pd.notna(raw)  else np.nan,
            text if pd.notna(text) else np.nan,
        )
    except Exception:
        return np.nan, np.nan


# ---------------------------------------------------------------------------
# Step 4: Scrape all descriptions with progress reporting
# ---------------------------------------------------------------------------

def scrape_descriptions(df: pd.DataFrame, delay: float = SCRAPE_DELAY) -> pd.DataFrame:
    df = df.copy()
    raw_descs, clean_descs = [], []

    for i, url in enumerate(tqdm(df["Posting"], desc="Fetching descriptions")):
        raw, clean = fetch_description(url)
        raw_descs.append(raw)
        clean_descs.append(clean)

        if (i + 1) % 50 == 0:
            n_ok = sum(1 for x in clean_descs if pd.notna(x))
            print(f"  [{i+1:3d}/{len(df)}] extracted so far: {n_ok}")

        time.sleep(delay)

    df["raw_description"]  = raw_descs
    df["description_text"] = clean_descs

    n_ok = df["description_text"].notna().sum()
    print(f"\nDone — extracted {n_ok}/{len(df)} descriptions ({100*n_ok/len(df):.1f}%)")
    return df


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def save_df(df: pd.DataFrame, path: Path = CACHE_PATH) -> None:
    df.to_parquet(path, index=True)
    print(f"Saved {len(df)} rows → {path}")


def load_df(path: Path = CACHE_PATH) -> pd.DataFrame:
    df = pd.read_parquet(path)
    print(f"Loaded {len(df)} rows from cache ({path})")
    return df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main(refresh: bool = False):
    # Step 1 — raw markdown
    md_text = load_raw_md()

    # Step 2 — parse tables
    faang_df, quant_df, general_df = load_tables(md_text)

    # Step 3/4 — descriptions (cached)
    if not refresh and CACHE_PATH.exists():
        general_df = load_df()
    else:
        general_df = scrape_descriptions(general_df)
        save_df(general_df)

    print("\nSample rows with descriptions:")
    print(general_df[["Company", "Position", "description_text"]].head(5).to_string())

    return faang_df, quant_df, general_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internship data pipeline")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-scrape job descriptions even if cache exists",
    )
    args = parser.parse_args()
    main(refresh=args.refresh)
