"""
Hiring Signal — Weekly Job Market Data Collection
Fetches DS/MLE/AI Engineer job data from Adzuna API and writes to Google Sheets + data.json
"""

import os
import json
import time
import re
from collections import Counter
from datetime import datetime, date
import requests
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

ADZUNA_APP_ID = os.environ["ADZUNA_APP_ID"]
ADZUNA_APP_KEY = os.environ["ADZUNA_APP_KEY"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

SEARCHES = [
    ("mle", "machine learning engineer"),
    ("ds", "data scientist"),
    ("ai_eng", "ai engineer"),
    ("mlops", "mlops engineer"),
    ("llm_eng", "llm engineer"),
]

COUNTRIES = [("ca", "Canada"), ("us", "United States")]

STOPWORDS = {
    "experience", "work", "team", "ability", "strong", "good", "years",
    "looking", "required", "preferred", "must", "will", "with", "that",
    "have", "your", "this", "from", "they", "their", "what", "which",
    "you", "are", "the", "and", "for", "our", "not", "all", "new",
    "role", "join", "help", "build", "using", "also", "more", "both",
    "other", "been", "than", "well", "into", "such", "some", "who",
    "we", "is", "in", "of", "to", "a", "an", "be", "or", "on",
    "at", "as", "by", "up", "can", "us", "has", "its", "but",
    "use", "across", "including", "within", "how", "make", "take",
    "key", "high", "level", "business", "data", "solutions", "systems",
    "design", "develop", "knowledge", "skills", "models",
}

SKILL_TERMS = {
    "python", "pytorch", "tensorflow", "sql", "spark", "aws", "gcp", "azure",
    "kubernetes", "docker", "mlflow", "airflow", "dbt", "llm", "fine-tuning",
    "rag", "langchain", "transformers", "huggingface", "scikit-learn",
    "pandas", "numpy", "databricks", "snowflake", "kafka", "fastapi",
    "pydantic", "mlops", "prompt engineering", "vector database",
    "embedding", "inference", "deployment", "cuda", "triton", "ray",
    "sagemaker", "vertex", "openai", "anthropic", "gemini", "redis",
    "postgresql", "mongodb", "elasticsearch", "flink", "beam",
    "terraform", "ci/cd", "git", "bash", "scala", "java", "go", "rust",
    "r", "julia", "matlab", "tableau", "powerbi", "looker",
}

CA_REGIONS = {
    "toronto": ["toronto", "north york", "scarborough", "etobicoke", "mississauga"],
    "vancouver": ["vancouver", "richmond", "burnaby", "surrey", "victoria"],
    "montreal": ["montreal", "laval", "longueuil"],
    "other_ca": [],
}

US_REGIONS = {
    "san_francisco": ["san francisco", "san jose", "oakland", "palo alto", "mountain view", "menlo park", "sunnyvale", "santa clara"],
    "new_york": ["new york", "brooklyn", "manhattan", "jersey city", "hoboken"],
    "seattle": ["seattle", "bellevue", "redmond", "kirkland"],
    "austin": ["austin", "round rock"],
    "boston": ["boston", "cambridge", "somerville", "waltham"],
    "other_us": [],
}

SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]


def get_sheets_client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def fetch_jobs(role_key, query, country):
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 50,
        "what": query,
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        count = data.get("count", len(results))
        print(f"  Fetching {role_key} jobs in {country.upper()}... {count} results")
        return results, count
    except Exception as e:
        print(f"  ERROR fetching {role_key}/{country}: {e}")
        return [], 0


def extract_skills(results):
    text = " ".join(
        (r.get("description", "") + " " + r.get("title", "")).lower()
        for r in results
    )
    words = re.findall(r"[a-z][a-z0-9\-/]+", text)
    counts = Counter()
    for w in words:
        if w in SKILL_TERMS:
            counts[w] += 1
    # multi-word skill terms
    for skill in SKILL_TERMS:
        if " " in skill and skill in text:
            counts[skill] += text.count(skill)
    filtered = Counter()
    for w, c in counts.items():
        if w not in STOPWORDS and len(w) > 1:
            filtered[w] = c
    return filtered.most_common(15)


def extract_salary(results):
    salaries = []
    for r in results:
        sal = r.get("salary_min"), r.get("salary_max")
        if sal[0] and sal[1]:
            lo, hi = float(sal[0]), float(sal[1])
            # convert hourly to annual if suspiciously low
            if lo < 500:
                lo *= 2080
                hi *= 2080
            salaries.append((lo, hi))
    if not salaries:
        return None
    lows = [s[0] for s in salaries]
    highs = [s[1] for s in salaries]
    return {
        "low": int(sorted(lows)[len(lows) // 4]),
        "mid": int(sorted(lows + highs)[len(lows + highs) // 2]),
        "high": int(sorted(highs)[len(highs) * 3 // 4]),
    }


def classify_region(location_str, country):
    loc = location_str.lower() if location_str else ""
    regions = CA_REGIONS if country == "ca" else US_REGIONS
    for region, keywords in regions.items():
        if region == ("other_ca" if country == "ca" else "other_us"):
            continue
        if any(kw in loc for kw in keywords):
            return region
    return "other_ca" if country == "ca" else "other_us"


def extract_companies(results, country):
    region_companies = {}
    regions = CA_REGIONS if country == "ca" else US_REGIONS
    for r in regions:
        region_companies[r] = Counter()

    for r in results:
        company = r.get("company", {}).get("display_name", "Unknown")
        location = r.get("location", {}).get("display_name", "")
        region = classify_region(location, country)
        role = r.get("title", "")
        region_companies[region][company] += 1

    output = {}
    for region, counter in region_companies.items():
        output[region] = [
            {"company": co, "count": cnt}
            for co, cnt in counter.most_common(10)
        ]
    return output


def read_last_week_from_sheets(client):
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sheet.worksheet("weekly_job_counts")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return None
        last = rows[-1]
        headers = rows[0]
        return dict(zip(headers, last))
    except Exception as e:
        print(f"  WARNING: Could not read last week from Sheets: {e}")
        return None


def read_history_from_sheets(client):
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sheet.worksheet("weekly_job_counts")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return []
        headers = rows[0]
        history = []
        for row in rows[1:]:
            d = dict(zip(headers, row))
            entry = {"week": d.get("week_date", "")}
            for key in ["mle_ca", "mle_us", "ds_ca", "ds_us", "ai_eng_ca", "ai_eng_us", "mlops_ca", "mlops_us", "llm_eng_ca", "llm_eng_us"]:
                try:
                    entry[key] = int(d.get(key, 0))
                except (ValueError, TypeError):
                    entry[key] = 0
            history.append(entry)
        return history[-12:]
    except Exception as e:
        print(f"  WARNING: Could not read history from Sheets: {e}")
        return []


def wow_pct(current, last_str):
    if not last_str:
        return 0.0
    try:
        last = int(last_str)
        if last == 0:
            return 0.0
        return round((current - last) / last * 100, 1)
    except (ValueError, TypeError):
        return 0.0


def write_job_counts_to_sheets(client, week_date, counts):
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sheet.worksheet("weekly_job_counts")
        row = [
            week_date,
            counts["mle"]["ca"], counts["mle"]["us"],
            counts["ds"]["ca"], counts["ds"]["us"],
            counts["ai_eng"]["ca"], counts["ai_eng"]["us"],
            counts["mlops"]["ca"], counts["mlops"]["us"],
            counts["llm_eng"]["ca"], counts["llm_eng"]["us"],
        ]
        ws.append_row(row)
        print("  Google Sheets weekly_job_counts: row appended")
        return True
    except Exception as e:
        print(f"  ERROR writing job counts to Sheets: {e}")
        return False


def write_skills_to_sheets(client, week_date, all_skills):
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sheet.worksheet("skill_frequency")
        existing = ws.get_all_values()
        last_week_skills = set()
        if len(existing) > 1:
            for row in existing:
                if row:
                    last_week_skills.add(row[1] if len(row) > 1 else "")

        rows = []
        for (role_key, country), skills in all_skills.items():
            for skill, freq in skills:
                is_new = skill not in last_week_skills
                rows.append([week_date, skill, freq, role_key, country, "yes" if is_new else "no", ""])
        if rows:
            ws.append_rows(rows)
        print(f"  Google Sheets skill_frequency: {len(rows)} rows appended")
        return True
    except Exception as e:
        print(f"  ERROR writing skills to Sheets: {e}")
        return False


def write_companies_to_sheets(client, week_date, all_companies):
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = sheet.worksheet("company_hiring")
        rows = []
        for (role_key, country), region_data in all_companies.items():
            for region, companies in region_data.items():
                for co in companies:
                    rows.append([
                        week_date, co["company"], role_key, co["count"],
                        f"{region}_{country}", "", ""
                    ])
        if rows:
            ws.append_rows(rows)
        print(f"  Google Sheets company_hiring: {len(rows)} rows appended")
        return True
    except Exception as e:
        print(f"  ERROR writing companies to Sheets: {e}")
        return False


def build_top_skills_for_json(all_skills, last_week_row):
    combined = Counter()
    for skills in all_skills.values():
        for skill, freq in skills:
            combined[skill] += freq

    last_week_skills = set()
    if last_week_row:
        pass  # skill newness tracked separately

    result = []
    for skill, freq in combined.most_common(15):
        result.append({
            "skill": skill,
            "frequency": freq,
            "wow_change": 0.0,
            "new": False,
        })
    return result


def build_top_companies_for_json(all_companies):
    region_map = {
        "toronto": Counter(),
        "vancouver": Counter(),
        "san_francisco": Counter(),
        "new_york": Counter(),
    }
    for (role_key, country), region_data in all_companies.items():
        for region, companies in region_data.items():
            if region in region_map:
                for co in companies:
                    region_map[region][co["company"]] += co["count"]

    result = {}
    for region, counter in region_map.items():
        result[region] = [
            {"company": co, "count": cnt, "roles": []}
            for co, cnt in counter.most_common(5)
        ]
    return result


def write_data_json(week_date, job_counts, top_skills, top_companies, salary_ranges, history):
    data = {
        "last_updated": week_date,
        "week_label": f"Week of {datetime.strptime(week_date, '%Y-%m-%d').strftime('%B %-d, %Y')}",
        "job_counts": job_counts,
        "top_skills": top_skills,
        "top_companies": top_companies,
        "salary_ranges": salary_ranges,
        "history": history,
    }
    os.makedirs("data", exist_ok=True)
    with open("data/data.json", "w") as f:
        json.dump(data, f, indent=2)
    print("  data/data.json written")


def print_summary(week_date, job_counts, top_skills):
    print()
    print("=" * 50)
    print("HIRING SIGNAL WEEKLY SUMMARY")
    print(f"Week of {datetime.strptime(week_date, '%Y-%m-%d').strftime('%B %-d, %Y')}")
    print("=" * 50)
    print()
    print("JOB COUNTS:")
    labels = {"mle": "MLE", "ds": "Data Scientist", "ai_eng": "AI Engineer", "mlops": "MLOps", "llm_eng": "LLM Engineer"}
    for key, label in labels.items():
        ca = job_counts[key]["ca"]
        us = job_counts[key]["us"]
        ca_wow = job_counts[key]["ca_wow"]
        us_wow = job_counts[key]["us_wow"]
        ca_str = f"{ca:,} ({ca_wow:+.1f}%)" if ca_wow != 0 else f"{ca:,} (first run)"
        us_str = f"{us:,} ({us_wow:+.1f}%)" if us_wow != 0 else f"{us:,} (first run)"
        print(f"  {label} Canada: {ca_str}")
        print(f"  {label} US:     {us_str}")
    print()
    print("TOP SKILLS THIS WEEK:")
    for i, s in enumerate(top_skills[:10], 1):
        print(f"  {i:2}. {s['skill']} ({s['frequency']} mentions)")
    print()


def main():
    today = date.today().isoformat()
    print(f"Hiring Signal data fetch — {today}")
    print()

    # Connect to Google Sheets
    client = None
    try:
        client = get_sheets_client()
        print("Google Sheets: connected")
    except Exception as e:
        print(f"WARNING: Google Sheets connection failed: {e}")
        print("Will still collect data and write data.json")

    last_week = read_last_week_from_sheets(client) if client else None
    history = read_history_from_sheets(client) if client else []

    job_counts_raw = {}
    all_results = {}
    all_skills = {}
    all_companies = {}
    salary_ranges = {}

    for role_key, query in SEARCHES:
        for country, _ in COUNTRIES:
            results, count = fetch_jobs(role_key, query, country)
            time.sleep(1)
            all_results[(role_key, country)] = results
            job_counts_raw[(role_key, country)] = count
            all_skills[(role_key, country)] = extract_skills(results)
            all_companies[(role_key, country)] = extract_companies(results, country)

        # salary from US results (more data)
        us_results = all_results.get((role_key, "us"), [])
        sal = extract_salary(us_results)
        if sal:
            salary_ranges[role_key] = {**sal, "region": "US"}

    # Build job counts with WoW
    job_counts = {}
    for role_key, _ in SEARCHES:
        ca_count = job_counts_raw.get((role_key, "ca"), 0)
        us_count = job_counts_raw.get((role_key, "us"), 0)
        ca_col = f"{role_key}_ca"
        us_col = f"{role_key}_us"
        job_counts[role_key] = {
            "ca": ca_count,
            "us": us_count,
            "ca_wow": wow_pct(ca_count, last_week.get(ca_col) if last_week else None),
            "us_wow": wow_pct(us_count, last_week.get(us_col) if last_week else None),
        }

    top_skills = build_top_skills_for_json(all_skills, last_week)
    top_companies = build_top_companies_for_json(all_companies)

    # Write to Sheets
    if client:
        print()
        print("Writing to Google Sheets...")
        write_job_counts_to_sheets(client, today, {k: {"ca": job_counts[k]["ca"], "us": job_counts[k]["us"]} for k in job_counts})
        write_skills_to_sheets(client, today, all_skills)
        write_companies_to_sheets(client, today, all_companies)

    # Add current week to history
    current_entry = {"week": today}
    for role_key, _ in SEARCHES:
        current_entry[f"{role_key}_ca"] = job_counts[role_key]["ca"]
        current_entry[f"{role_key}_us"] = job_counts[role_key]["us"]
    history.append(current_entry)
    history = history[-12:]

    # Write data.json
    print()
    print("Writing data/data.json...")
    write_data_json(today, job_counts, top_skills, top_companies, salary_ranges, history)

    print_summary(today, job_counts, top_skills)


if __name__ == "__main__":
    main()
