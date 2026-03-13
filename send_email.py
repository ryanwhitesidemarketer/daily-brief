#!/usr/bin/env python3
"""
Send the daily brief PDF via Gmail.
Uses Gmail API via the connected Gmail MCP tool (called externally).
This script prepares the email content — actual sending is done by Claude's Gmail connector.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_FILE = SCRIPT_DIR / "data" / "daily-brief.json"

RECIPIENT = "ryan@twowheelsmarketing.com"
DASHBOARD_URL = "https://ryanwhitesidemarketer.github.io/daily-brief/"


def generate_email_body():
    """Generate HTML email body from analysis data."""
    data = json.loads(DATA_FILE.read_text())
    summary = data["portfolio_summary"]
    priorities = data["priorities"]
    analysis_date = data.get("analysis_date", datetime.now().strftime("%Y-%m-%d"))

    try:
        dt = datetime.strptime(analysis_date, "%Y-%m-%d")
        date_display = dt.strftime("%B %d, %Y")
    except:
        date_display = analysis_date

    # Build priority summary rows
    priority_html = ""
    for i, p in enumerate(priorities[:10], 1):
        headline = p["issues"][0]["headline"] if p.get("issues") else "Monitoring"
        platform = p.get("platform_display", p["platform"])
        cost = p["current"]["cost"]

        if p["client_type"] == "ecommerce":
            key_stat = f'ROAS: {p["current"]["roas"]:.1f}x'
        else:
            cpl = p["current"].get("cpl")
            key_stat = f'CPL: ${cpl:,.0f}' if cpl else "No leads"

        bg = "#fff5f5" if p.get("priority_score", 0) >= 50 else "#fffff0" if p.get("priority_score", 0) >= 25 else "#f0fff0"

        priority_html += f"""
        <tr style="background:{bg};">
            <td style="padding:6px 10px;font-weight:bold;color:#6c5ce7;">#{i}</td>
            <td style="padding:6px 10px;font-weight:600;">{p['client_name']}</td>
            <td style="padding:6px 10px;font-size:12px;color:#666;">{platform}</td>
            <td style="padding:6px 10px;">${cost:,.0f}</td>
            <td style="padding:6px 10px;font-weight:600;">{key_stat}</td>
            <td style="padding:6px 10px;font-size:12px;color:#c0392b;">{headline[:60]}{'...' if len(headline) > 60 else ''}</td>
        </tr>"""

    body = f"""<div style="font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;max-width:700px;margin:0 auto;color:#1a1a2e;">
    <div style="background:linear-gradient(135deg,#6c5ce7,#2d1b69);color:#fff;padding:20px 24px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;font-size:22px;">PPC Daily Brief</h1>
        <p style="margin:4px 0 0;opacity:0.8;font-size:14px;">{date_display} — Day {summary['day_of_month']}/{summary['days_in_month']}</p>
    </div>

    <div style="background:#f8f9fa;padding:16px 24px;display:flex;border-bottom:1px solid #eee;">
        <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
            <td align="center" style="padding:8px;"><strong style="font-size:18px;">{summary['total_accounts_analyzed']}</strong><br><span style="font-size:11px;color:#888;">ACCOUNTS</span></td>
            <td align="center" style="padding:8px;"><strong style="font-size:18px;">${summary['total_mtd_spend']:,.0f}</strong><br><span style="font-size:11px;color:#888;">MTD SPEND</span></td>
            <td align="center" style="padding:8px;"><strong style="font-size:18px;">${summary['total_mtd_revenue']:,.0f}</strong><br><span style="font-size:11px;color:#888;">MTD REVENUE</span></td>
            <td align="center" style="padding:8px;"><strong style="font-size:18px;color:{'#2e7d32' if summary['overall_roas'] >= 3 else '#c62828'};">{summary['overall_roas']:.2f}x</strong><br><span style="font-size:11px;color:#888;">ROAS</span></td>
            <td align="center" style="padding:8px;"><strong style="font-size:18px;color:#c62828;">{summary['accounts_below_roas_target']}</strong><br><span style="font-size:11px;color:#888;">BELOW 3X</span></td>
        </tr>
        </table>
    </div>

    <div style="padding:20px 24px;">
        <h2 style="font-size:16px;margin:0 0 12px;color:#1a1a2e;">Top 10 Priority Accounts</h2>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
            <thead>
                <tr style="background:#f0f0f0;border-bottom:2px solid #ddd;">
                    <th style="padding:6px 10px;text-align:left;">#</th>
                    <th style="padding:6px 10px;text-align:left;">Client</th>
                    <th style="padding:6px 10px;text-align:left;">Platform</th>
                    <th style="padding:6px 10px;text-align:left;">MTD Spend</th>
                    <th style="padding:6px 10px;text-align:left;">Key Metric</th>
                    <th style="padding:6px 10px;text-align:left;">Issue</th>
                </tr>
            </thead>
            <tbody>
                {priority_html}
            </tbody>
        </table>
    </div>

    <div style="padding:16px 24px;text-align:center;border-top:1px solid #eee;">
        <a href="{DASHBOARD_URL}" style="display:inline-block;background:#6c5ce7;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">View Full Dashboard →</a>
    </div>

    <div style="padding:12px 24px;text-align:center;font-size:11px;color:#999;border-top:1px solid #f0f0f0;">
        Two Wheels Marketing — PPC Daily Brief<br>
        PDF archive attached | <a href="{DASHBOARD_URL}" style="color:#6c5ce7;">Dashboard</a>
    </div>
</div>"""

    return body, date_display


def get_email_subject():
    data = json.loads(DATA_FILE.read_text())
    summary = data["portfolio_summary"]
    analysis_date = data.get("analysis_date", "")
    roas = summary.get("overall_roas", 0)
    below = summary.get("accounts_below_roas_target", 0)
    spend = summary.get("total_mtd_spend", 0)

    dt = datetime.strptime(analysis_date, "%Y-%m-%d")
    date_short = dt.strftime("%b %d")

    return f"PPC Brief {date_short}: {roas:.1f}x ROAS | ${spend:,.0f} MTD | {below} accounts need attention"


if __name__ == "__main__":
    body, date_display = generate_email_body()
    subject = get_email_subject()
    print(f"Subject: {subject}")
    print(f"To: {RECIPIENT}")
    print(f"Date: {date_display}")
    print(f"\nEmail body length: {len(body)} chars")
    print("\n--- Preview (first 500 chars) ---")
    print(body[:500])
