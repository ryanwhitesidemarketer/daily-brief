#!/usr/bin/env python3
"""
Daily Brief Analysis Engine
Reads ad-data JSON files + budgets.json, scores every account,
and outputs a prioritized daily-brief.json with actionable recommendations.
"""

import json
import os
import sys
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict
import statistics

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
AD_DATA_DIR = Path(os.environ.get("AD_DATA_DIR", SCRIPT_DIR.parent / "ad-data" / "data"))
BUDGETS_FILE = Path(os.environ.get("BUDGETS_FILE", SCRIPT_DIR.parent / "ad-pacing" / "data" / "budgets.json"))
OUTPUT_FILE = SCRIPT_DIR / "data" / "daily-brief.json"

# Thresholds
ECOM_ROAS_TARGET = 3.0       # Below this = focus on improving ROAS
ECOM_ROAS_STRONG = 4.0       # Above this = definitely scale
CPL_SPIKE_THRESHOLD = 1.35   # Flag if CPL is 35%+ above historical baseline
MOM_DROP_THRESHOLD = 0.25    # Flag if metric drops 25%+ month-over-month
YOY_DROP_THRESHOLD = 0.30    # Flag if metric drops 30%+ year-over-year
PACING_OVER = 1.15            # Flag if projected spend is 15%+ over budget
PACING_UNDER = 0.80           # Flag if projected spend is 20%+ under budget
MAX_PRIORITIES = 15

CURRENT_MONTH = datetime.now().strftime("%Y-%m")
TODAY = date.today()
DAYS_IN_MONTH = (date(TODAY.year, TODAY.month % 12 + 1, 1) - date(TODAY.year, TODAY.month, 1)).days if TODAY.month < 12 else 31
DAY_OF_MONTH = TODAY.day
PCT_MONTH_ELAPSED = DAY_OF_MONTH / DAYS_IN_MONTH

# Prior month and prior year same month
if TODAY.month == 1:
    PRIOR_MONTH = f"{TODAY.year - 1}-12"
    PRIOR_YEAR_MONTH = f"{TODAY.year - 2}-{TODAY.month:02d}"
else:
    PRIOR_MONTH = f"{TODAY.year}-{TODAY.month - 1:02d}"
    PRIOR_YEAR_MONTH = f"{TODAY.year - 1}-{TODAY.month:02d}"

PLATFORM_FOLDER_MAP = {
    "google_ads": "google-ads",
    "meta_ads": "meta-ads",
    "bing_ads": "bing-ads",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def normalize(name):
    """Normalize a name for fuzzy matching."""
    import re
    n = name.lower().strip()
    # Remove platform indicators
    for term in ["google ads", "bing ads", "fb ads", "meta ads", "linkedin ads",
                 "(google)", "(bing)", "(fb)", "(meta)", "(linkedin)",
                 "google", "bing"]:
        n = n.replace(term, "")
    # Remove parenthetical suffixes
    n = re.sub(r'\(.*?\)', '', n)
    # Remove common suffixes
    for term in ["florist", "flowers", "flower", "& gifts", "floral"]:
        n = n.replace(term, "")
    n = re.sub(r'[^a-z0-9]', '', n)
    return n.strip()


def load_json(path):
    """Load a JSON file, return None on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_account_history(platform_folder, account_slug):
    """Load all monthly JSON files for an account, return dict keyed by month."""
    account_dir = AD_DATA_DIR / platform_folder / account_slug
    if not account_dir.exists():
        return {}
    history = {}
    for f in sorted(account_dir.glob("*.json")):
        data = load_json(f)
        if data and "month" in data:
            history[data["month"]] = data
    return history


def calc_historical_cpl(history, current_month):
    """Calculate historical average CPL from all months except current."""
    cpls = []
    for month, data in history.items():
        if month == current_month:
            continue
        totals = data.get("totals", {})
        cost = totals.get("cost", 0)
        conversions = totals.get("conversions", 0)
        if conversions > 0 and cost > 0:
            cpls.append(cost / conversions)
    if cpls:
        return statistics.median(cpls)
    return None


def calc_historical_roas(history, current_month):
    """Calculate historical average ROAS from all months except current."""
    roas_vals = []
    for month, data in history.items():
        if month == current_month:
            continue
        totals = data.get("totals", {})
        roas = totals.get("roas", 0)
        if roas and roas > 0:
            roas_vals.append(roas)
    if roas_vals:
        return statistics.median(roas_vals)
    return None


def find_account_slug(platform_folder, budget_name):
    """Find the ad-data folder slug that matches a budget entry name."""
    platform_dir = AD_DATA_DIR / platform_folder
    if not platform_dir.exists():
        return None

    budget_norm = normalize(budget_name)
    slugs = [d.name for d in platform_dir.iterdir() if d.is_dir()]

    # Try exact slug match first
    for slug in slugs:
        # Load any file to get account name
        files = list((platform_dir / slug).glob("*.json"))
        if not files:
            continue
        data = load_json(files[0])
        if data:
            account_name = data.get("account", "")
            if normalize(account_name) == budget_norm:
                return slug
            # Also try slug-based normalization
            slug_norm = slug.replace("-", "")
            if slug_norm == budget_norm or budget_norm.startswith(slug_norm) or slug_norm.startswith(budget_norm):
                return slug

    # Fuzzy: find best word overlap
    best_slug = None
    best_score = 0
    budget_words = set(normalize(budget_name))

    for slug in slugs:
        slug_clean = slug.replace("-", "")
        # Simple containment check
        if budget_norm and slug_clean and (budget_norm in slug_clean or slug_clean in budget_norm):
            score = len(slug_clean)
            if score > best_score:
                best_score = score
                best_slug = slug

    return best_slug


def analyze_campaigns(data, client_type):
    """Analyze individual campaigns for opportunities."""
    campaigns = data.get("campaigns", [])
    findings = []

    for camp in campaigns:
        name = camp.get("campaign_name", "Unknown")
        status = camp.get("campaign_status", "").lower()
        cost = camp.get("cost", 0)
        conversions = camp.get("conversions", 0)
        revenue = camp.get("revenue", 0)
        clicks = camp.get("clicks", 0)
        cpc = camp.get("cpc", 0)
        conv_rate = camp.get("conversion_rate", 0)

        if "paused" in status or "budget paused" in status:
            continue  # Skip paused campaigns for active recommendations

        if client_type == "ecommerce":
            roas = revenue / cost if cost > 0 else 0
            if cost > 100 and roas < 1.5:
                findings.append({
                    "campaign": name,
                    "issue": "very_low_roas",
                    "severity": "high",
                    "detail": f"ROAS of {roas:.1f}x on ${cost:,.0f} spend — consider pausing or restructuring",
                    "metrics": {"cost": cost, "revenue": revenue, "roas": round(roas, 2), "conversions": conversions}
                })
            elif cost > 200 and roas >= ECOM_ROAS_STRONG:
                findings.append({
                    "campaign": name,
                    "issue": "scale_opportunity",
                    "severity": "opportunity",
                    "detail": f"Strong {roas:.1f}x ROAS on ${cost:,.0f} — room to increase budget",
                    "metrics": {"cost": cost, "revenue": revenue, "roas": round(roas, 2), "conversions": conversions}
                })
            elif cost > 50 and conversions == 0:
                findings.append({
                    "campaign": name,
                    "issue": "zero_conversions",
                    "severity": "high",
                    "detail": f"${cost:,.0f} spent with zero conversions this month",
                    "metrics": {"cost": cost, "clicks": clicks, "conversions": 0}
                })
        else:  # lead_gen
            cpl = cost / conversions if conversions > 0 else None
            if cost > 100 and conversions == 0:
                findings.append({
                    "campaign": name,
                    "issue": "zero_leads",
                    "severity": "high",
                    "detail": f"${cost:,.0f} spent with zero leads this month",
                    "metrics": {"cost": cost, "clicks": clicks, "conversions": 0}
                })
            elif cost > 50 and cpl and cpl > 200:
                findings.append({
                    "campaign": name,
                    "issue": "high_cpl",
                    "severity": "medium",
                    "detail": f"CPL of ${cpl:,.0f} — check targeting and ad relevance",
                    "metrics": {"cost": cost, "conversions": conversions, "cpl": round(cpl, 2)}
                })

    return findings


def score_account(analysis):
    """Score an account for prioritization. Higher = more urgent."""
    score = 0
    issues = analysis.get("issues", [])

    for issue in issues:
        itype = issue.get("type", "")
        if itype == "low_roas":
            score += 30 + (analysis.get("monthly_budget", 0) / 1000)  # Weight by budget
        elif itype == "roas_drop_mom":
            score += 25
        elif itype == "roas_drop_yoy":
            score += 20
        elif itype == "high_cpl":
            score += 30 + (analysis.get("monthly_budget", 0) / 1000)
        elif itype == "cpl_spike":
            score += 25
        elif itype == "overpacing":
            score += 15
        elif itype == "underpacing":
            score += 10
        elif itype == "scale_opportunity":
            score += 20 + (analysis.get("monthly_budget", 0) / 2000)
        elif itype == "zero_conversions":
            score += 35

    # Weight by budget size — bigger accounts matter more
    budget = analysis.get("monthly_budget", 0)
    if budget > 20000:
        score *= 1.5
    elif budget > 5000:
        score *= 1.2

    # Boost for campaign-level findings
    campaign_findings = analysis.get("campaign_findings", [])
    high_severity = sum(1 for f in campaign_findings if f.get("severity") == "high")
    score += high_severity * 10

    return round(score, 1)


# ── Main Analysis ─────────────────────────────────────────────────────────────

def main():
    print(f"Daily Brief Analysis — {TODAY.isoformat()}")
    print(f"Current month: {CURRENT_MONTH} | Day {DAY_OF_MONTH}/{DAYS_IN_MONTH} ({PCT_MONTH_ELAPSED:.0%} elapsed)")
    print(f"Prior month: {PRIOR_MONTH} | Prior year same month: {PRIOR_YEAR_MONTH}")
    print()

    # Load budgets
    budgets_data = load_json(BUDGETS_FILE)
    if not budgets_data:
        sys.exit(f"ERROR: Could not load budgets from {BUDGETS_FILE}")

    budgets = budgets_data.get("budgets", [])
    print(f"Loaded {len(budgets)} budget entries")

    # Skip LinkedIn for now (only 1 entry, no ad-data)
    budgets = [b for b in budgets if b["platform"] in PLATFORM_FOLDER_MAP]
    print(f"Analyzing {len(budgets)} entries (Google/Meta/Bing)")
    print()

    all_analyses = []

    for budget in budgets:
        client_name = budget["client_name"]
        platform = budget["platform"]
        client_type = budget["client_type"]
        monthly_budget = budget["monthly_budget"]
        platform_folder = PLATFORM_FOLDER_MAP[platform]

        # Find matching ad-data folder
        slug = find_account_slug(platform_folder, client_name)
        if not slug:
            continue

        # Load history
        history = load_account_history(platform_folder, slug)
        if not history:
            continue

        current_data = history.get(CURRENT_MONTH)
        prior_month_data = history.get(PRIOR_MONTH)
        prior_year_data = history.get(PRIOR_YEAR_MONTH)

        if not current_data:
            continue

        totals = current_data.get("totals", {})
        cost = totals.get("cost", 0)
        impressions = totals.get("impressions", 0)
        clicks = totals.get("clicks", 0)
        conversions = totals.get("conversions", 0)
        revenue = totals.get("revenue", 0)
        roas = totals.get("roas", 0)
        cpc = totals.get("cpc", 0)
        ctr = totals.get("ctr", 0)
        conv_rate = totals.get("conversion_rate", 0)

        issues = []
        actions = []

        # ── Ecommerce Analysis ────────────────────────────────────────────
        if client_type == "ecommerce":
            # ROAS check
            if cost > 0 and roas < ECOM_ROAS_TARGET:
                issues.append({
                    "type": "low_roas",
                    "headline": f"ROAS below {ECOM_ROAS_TARGET}x — focus on improving efficiency",
                    "detail": f"Current ROAS is {roas:.2f}x on ${cost:,.0f} spend. Target is {ECOM_ROAS_TARGET}x+.",
                })
                actions.append(f"Audit campaigns below {ECOM_ROAS_TARGET}x ROAS — pause worst performers or tighten targeting")

            elif cost > 0 and roas >= ECOM_ROAS_STRONG and monthly_budget > 0:
                projected_spend = cost / PCT_MONTH_ELAPSED if PCT_MONTH_ELAPSED > 0 else cost
                headroom = monthly_budget - projected_spend
                if headroom > monthly_budget * 0.1:
                    issues.append({
                        "type": "scale_opportunity",
                        "headline": f"Strong {roas:.1f}x ROAS with budget headroom — scale up",
                        "detail": f"ROAS of {roas:.2f}x with ~${headroom:,.0f} unspent budget potential. Revenue opportunity.",
                    })
                    actions.append(f"Increase bids or expand targeting on top campaigns to capture more revenue")

            # ROAS trend - month over month
            if prior_month_data:
                pm_roas = prior_month_data.get("totals", {}).get("roas", 0)
                if pm_roas > 0 and roas > 0:
                    roas_change = (roas - pm_roas) / pm_roas
                    if roas_change < -MOM_DROP_THRESHOLD:
                        issues.append({
                            "type": "roas_drop_mom",
                            "headline": f"ROAS dropped {abs(roas_change):.0%} vs. last month",
                            "detail": f"ROAS went from {pm_roas:.2f}x → {roas:.2f}x month-over-month.",
                        })
                        actions.append("Compare campaign mix to last month — identify which campaigns lost efficiency")

            # ROAS trend - year over year
            if prior_year_data:
                py_roas = prior_year_data.get("totals", {}).get("roas", 0)
                if py_roas > 0 and roas > 0:
                    roas_change_yoy = (roas - py_roas) / py_roas
                    if roas_change_yoy < -YOY_DROP_THRESHOLD:
                        issues.append({
                            "type": "roas_drop_yoy",
                            "headline": f"ROAS down {abs(roas_change_yoy):.0%} vs. same month last year",
                            "detail": f"ROAS was {py_roas:.2f}x in {PRIOR_YEAR_MONTH}, now {roas:.2f}x.",
                        })
                        actions.append("Check for market shifts, competitor activity, or landing page issues vs. last year")

        # ── Lead Gen Analysis ─────────────────────────────────────────────
        elif client_type == "lead_gen":
            cpl = cost / conversions if conversions > 0 else None
            historical_cpl = calc_historical_cpl(history, CURRENT_MONTH)

            if cost > 100 and conversions == 0:
                issues.append({
                    "type": "zero_conversions",
                    "headline": f"${cost:,.0f} spent with ZERO leads this month",
                    "detail": "No conversions tracked. Check conversion tracking, landing pages, and ad targeting.",
                })
                actions.append("Verify conversion tracking is firing. Check landing page load times and form functionality.")
            elif cpl and historical_cpl and cpl > historical_cpl * CPL_SPIKE_THRESHOLD:
                issues.append({
                    "type": "cpl_spike",
                    "headline": f"CPL spiked to ${cpl:,.0f} (historical median: ${historical_cpl:,.0f})",
                    "detail": f"Cost per lead is {((cpl / historical_cpl) - 1):.0%} above your historical baseline.",
                })
                actions.append("Review search terms for irrelevant queries. Check if ad copy or landing page changed recently.")
            elif cpl and cpl > 0:
                if historical_cpl:
                    issues.append({
                        "type": "cpl_tracking",
                        "headline": f"CPL at ${cpl:,.0f} (baseline: ${historical_cpl:,.0f})",
                        "detail": f"Currently {'above' if cpl > historical_cpl else 'at or below'} historical baseline.",
                    })

            # MoM conversion volume drop
            if prior_month_data:
                pm_conv = prior_month_data.get("totals", {}).get("conversions", 0)
                if pm_conv > 0 and conversions > 0:
                    conv_change = (conversions - pm_conv) / pm_conv
                    if conv_change < -MOM_DROP_THRESHOLD:
                        issues.append({
                            "type": "lead_volume_drop",
                            "headline": f"Lead volume down {abs(conv_change):.0%} vs. last month",
                            "detail": f"Conversions went from {pm_conv:.0f} → {conversions:.0f}.",
                        })
                        actions.append("Check impression share — may need to increase bids or budgets to maintain volume")

        # ── Pacing Analysis (both types) ──────────────────────────────────
        if monthly_budget > 0 and cost > 0 and PCT_MONTH_ELAPSED > 0.1:
            projected_spend = cost / PCT_MONTH_ELAPSED
            pacing_ratio = projected_spend / monthly_budget

            if pacing_ratio > PACING_OVER:
                issues.append({
                    "type": "overpacing",
                    "headline": f"On pace to overspend by ${projected_spend - monthly_budget:,.0f}",
                    "detail": f"Projected: ${projected_spend:,.0f} vs. budget ${monthly_budget:,.0f} ({pacing_ratio:.0%}).",
                })
                actions.append("Reduce daily budgets or bids to slow spend rate for remainder of month")
            elif pacing_ratio < PACING_UNDER:
                issues.append({
                    "type": "underpacing",
                    "headline": f"Underspending — on pace for only ${projected_spend:,.0f} of ${monthly_budget:,.0f} budget",
                    "detail": f"Only {pacing_ratio:.0%} of budget likely to be used. Potential lost opportunity.",
                })
                if client_type == "ecommerce" and roas >= ECOM_ROAS_TARGET:
                    actions.append("ROAS is strong — increase bids or expand targeting to capture the remaining budget")
                else:
                    actions.append("Review if campaigns are limited by budget, bid, or targeting constraints")

        # ── Campaign-level drill down ─────────────────────────────────────
        campaign_findings = analyze_campaigns(current_data, client_type)

        # ── Build analysis object ─────────────────────────────────────────
        analysis = {
            "client_name": client_name,
            "account_name": current_data.get("account", client_name),
            "platform": platform,
            "platform_display": platform.replace("_", " ").title(),
            "client_type": client_type,
            "slug": slug,
            "monthly_budget": monthly_budget,
            "current_month": CURRENT_MONTH,
            "current": {
                "cost": round(cost, 2),
                "impressions": impressions,
                "clicks": clicks,
                "conversions": round(conversions, 2),
                "revenue": round(revenue, 2),
                "roas": round(roas, 2) if roas else 0,
                "cpc": round(cpc, 2),
                "ctr": round(ctr, 2) if ctr else 0,
                "conversion_rate": round(conv_rate, 2) if conv_rate else 0,
                "cpl": round(cost / conversions, 2) if conversions > 0 else None,
            },
            "prior_month": {
                "cost": round(prior_month_data["totals"].get("cost", 0), 2),
                "conversions": round(prior_month_data["totals"].get("conversions", 0), 2),
                "revenue": round(prior_month_data["totals"].get("revenue", 0), 2),
                "roas": round(prior_month_data["totals"].get("roas", 0), 2),
            } if prior_month_data else None,
            "prior_year": {
                "cost": round(prior_year_data["totals"].get("cost", 0), 2),
                "conversions": round(prior_year_data["totals"].get("conversions", 0), 2),
                "revenue": round(prior_year_data["totals"].get("revenue", 0), 2),
                "roas": round(prior_year_data["totals"].get("roas", 0), 2),
            } if prior_year_data else None,
            "issues": issues,
            "actions": actions,
            "campaign_findings": campaign_findings,
            "campaigns": current_data.get("campaigns", []),
        }

        analysis["priority_score"] = score_account(analysis)
        all_analyses.append(analysis)

    # ── Sort and prioritize ───────────────────────────────────────────────
    all_analyses.sort(key=lambda x: x["priority_score"], reverse=True)

    priorities = all_analyses[:MAX_PRIORITIES]
    remaining = all_analyses[MAX_PRIORITIES:]

    # Portfolio health summary
    total_spend = sum(a["current"]["cost"] for a in all_analyses)
    total_revenue = sum(a["current"]["revenue"] for a in all_analyses)
    total_budget = sum(a["monthly_budget"] for a in all_analyses if a["monthly_budget"])
    ecom_accounts = [a for a in all_analyses if a["client_type"] == "ecommerce"]
    lead_accounts = [a for a in all_analyses if a["client_type"] == "lead_gen"]
    accounts_below_roas = sum(1 for a in ecom_accounts if a["current"]["roas"] > 0 and a["current"]["roas"] < ECOM_ROAS_TARGET)
    accounts_strong_roas = sum(1 for a in ecom_accounts if a["current"]["roas"] >= ECOM_ROAS_STRONG)

    portfolio_summary = {
        "total_accounts_analyzed": len(all_analyses),
        "total_mtd_spend": round(total_spend, 2),
        "total_mtd_revenue": round(total_revenue, 2),
        "total_monthly_budget": round(total_budget, 2),
        "overall_roas": round(total_revenue / total_spend, 2) if total_spend > 0 else 0,
        "ecommerce_accounts": len(ecom_accounts),
        "lead_gen_accounts": len(lead_accounts),
        "accounts_below_roas_target": accounts_below_roas,
        "accounts_with_strong_roas": accounts_strong_roas,
        "pct_month_elapsed": round(PCT_MONTH_ELAPSED, 3),
        "day_of_month": DAY_OF_MONTH,
        "days_in_month": DAYS_IN_MONTH,
    }

    # ── Output ────────────────────────────────────────────────────────────
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "analysis_date": TODAY.isoformat(),
        "current_month": CURRENT_MONTH,
        "prior_month": PRIOR_MONTH,
        "prior_year_month": PRIOR_YEAR_MONTH,
        "portfolio_summary": portfolio_summary,
        "priorities": [{k: v for k, v in a.items()} for a in priorities],
        "remaining": [{
            "client_name": a["client_name"],
            "platform": a["platform"],
            "platform_display": a["platform_display"],
            "client_type": a["client_type"],
            "monthly_budget": a["monthly_budget"],
            "current": a["current"],
            "issues": a["issues"],
            "priority_score": a["priority_score"],
        } for a in remaining],
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"Accounts analyzed: {len(all_analyses)}")
    print(f"Top priorities: {len(priorities)}")
    print(f"Portfolio MTD spend: ${total_spend:,.0f}")
    print(f"Portfolio MTD revenue: ${total_revenue:,.0f}")
    print(f"Overall ROAS: {total_revenue / total_spend:.2f}x" if total_spend > 0 else "No spend")
    print(f"\nTop 5 priorities:")
    for i, p in enumerate(priorities[:5], 1):
        top_issue = p["issues"][0]["headline"] if p["issues"] else "Monitoring"
        print(f"  {i}. [{p['platform_display']}] {p['client_name']} (score: {p['priority_score']})")
        print(f"     → {top_issue}")
    print(f"\nOutput: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
