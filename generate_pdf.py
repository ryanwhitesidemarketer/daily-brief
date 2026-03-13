#!/usr/bin/env python3
"""
Generate a PDF daily brief from the analysis JSON.
Outputs a clean, professional PDF summary of top priorities.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_FILE = SCRIPT_DIR / "data" / "daily-brief.json"
OUTPUT_DIR = SCRIPT_DIR / "data" / "archive"


def format_currency(val):
    if val is None:
        return "N/A"
    if val >= 1000:
        return f"${val:,.0f}"
    return f"${val:,.2f}"


def format_roas(val):
    if not val:
        return "N/A"
    return f"{val:.2f}x"


def generate_html(data):
    """Generate HTML content for PDF rendering."""
    summary = data["portfolio_summary"]
    priorities = data["priorities"]
    generated = data.get("generated_at", "")
    analysis_date = data.get("analysis_date", datetime.now().strftime("%Y-%m-%d"))

    # Format date nicely
    try:
        dt = datetime.strptime(analysis_date, "%Y-%m-%d")
        date_display = dt.strftime("%B %d, %Y")
    except:
        date_display = analysis_date

    priority_rows = ""
    for i, p in enumerate(priorities, 1):
        client = p["client_name"]
        platform = p.get("platform_display", p["platform"])
        ctype = p["client_type"].replace("_", " ").title()
        budget = format_currency(p["monthly_budget"])
        current = p["current"]
        cost = format_currency(current["cost"])

        if p["client_type"] == "ecommerce":
            revenue = format_currency(current["revenue"])
            key_metric = f'ROAS: {format_roas(current["roas"])}'
            revenue_col = revenue
        else:
            cpl = format_currency(current.get("cpl")) if current.get("cpl") else "N/A"
            key_metric = f'CPL: {cpl}'
            revenue_col = f'{current["conversions"]:.0f} leads'

        # Top issue headline
        headline = ""
        if p.get("issues"):
            headline = p["issues"][0].get("headline", "")

        # Actions
        actions_html = ""
        if p.get("actions"):
            actions_html = "<br>".join(f"→ {a}" for a in p["actions"][:2])

        # Campaign flags
        camp_flags = ""
        high_flags = [f for f in p.get("campaign_findings", []) if f.get("severity") == "high"]
        if high_flags:
            camp_flags = f'<div class="camp-flags">{len(high_flags)} campaign{"s" if len(high_flags) > 1 else ""} flagged</div>'

        # Score-based color
        score = p.get("priority_score", 0)
        if score >= 50:
            score_class = "score-high"
        elif score >= 25:
            score_class = "score-medium"
        else:
            score_class = "score-low"

        priority_rows += f"""
        <div class="priority-card">
            <div class="priority-header">
                <span class="rank">#{i}</span>
                <span class="client-name">{client}</span>
                <span class="badges">
                    <span class="badge platform">{platform}</span>
                    <span class="badge type">{ctype}</span>
                    <span class="badge {score_class}">Score: {score:.0f}</span>
                </span>
            </div>
            <div class="headline">{headline}</div>
            <div class="metrics-row">
                <div class="metric"><span class="label">MTD Spend</span><span class="value">{cost}</span></div>
                <div class="metric"><span class="label">{"Revenue" if p["client_type"] == "ecommerce" else "Leads"}</span><span class="value">{revenue_col}</span></div>
                <div class="metric"><span class="label">{key_metric.split(":")[0]}</span><span class="value">{key_metric.split(":")[1].strip()}</span></div>
                <div class="metric"><span class="label">Budget</span><span class="value">{budget}</span></div>
            </div>
            {"<div class='actions'>" + actions_html + "</div>" if actions_html else ""}
            {camp_flags}
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: letter;
        margin: 0.6in 0.65in;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
        font-size: 9.5pt;
        color: #1a1a2e;
        line-height: 1.45;
        background: #fff;
    }}
    .header {{
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-bottom: 3px solid #6c5ce7;
        padding-bottom: 10px;
        margin-bottom: 14px;
    }}
    .header h1 {{
        font-size: 18pt;
        color: #6c5ce7;
        font-weight: 700;
        letter-spacing: -0.3px;
    }}
    .header .subtitle {{
        font-size: 9pt;
        color: #666;
    }}
    .header .date {{
        font-size: 10pt;
        color: #333;
        text-align: right;
    }}
    .summary-bar {{
        display: flex;
        gap: 12px;
        background: linear-gradient(135deg, #2d1b69 0%, #1a1a2e 100%);
        color: #fff;
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 16px;
    }}
    .summary-stat {{
        flex: 1;
        text-align: center;
    }}
    .summary-stat .val {{
        font-size: 14pt;
        font-weight: 700;
    }}
    .summary-stat .lbl {{
        font-size: 7.5pt;
        opacity: 0.75;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .section-title {{
        font-size: 11pt;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 8px;
        padding-bottom: 3px;
        border-bottom: 1px solid #eee;
    }}
    .priority-card {{
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        padding: 9px 12px;
        margin-bottom: 8px;
        page-break-inside: avoid;
    }}
    .priority-header {{
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 4px;
    }}
    .rank {{
        font-weight: 800;
        color: #6c5ce7;
        font-size: 11pt;
        min-width: 28px;
    }}
    .client-name {{
        font-weight: 700;
        font-size: 10pt;
        flex: 1;
    }}
    .badges {{ display: flex; gap: 4px; }}
    .badge {{
        font-size: 7pt;
        padding: 2px 6px;
        border-radius: 3px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }}
    .badge.platform {{ background: #e8e3ff; color: #6c5ce7; }}
    .badge.type {{ background: #e3f2fd; color: #1976d2; }}
    .score-high {{ background: #ffebee; color: #c62828; }}
    .score-medium {{ background: #fff3e0; color: #e65100; }}
    .score-low {{ background: #e8f5e9; color: #2e7d32; }}
    .headline {{
        font-size: 9pt;
        color: #c0392b;
        font-weight: 600;
        margin-bottom: 5px;
    }}
    .metrics-row {{
        display: flex;
        gap: 16px;
    }}
    .metric {{ text-align: center; }}
    .metric .label {{
        display: block;
        font-size: 7pt;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }}
    .metric .value {{
        display: block;
        font-size: 9.5pt;
        font-weight: 700;
        color: #1a1a2e;
    }}
    .actions {{
        margin-top: 4px;
        font-size: 8pt;
        color: #2e7d32;
        font-style: italic;
    }}
    .camp-flags {{
        margin-top: 3px;
        font-size: 7.5pt;
        color: #e65100;
        font-weight: 600;
    }}
    .footer {{
        margin-top: 16px;
        padding-top: 8px;
        border-top: 1px solid #ddd;
        font-size: 7.5pt;
        color: #999;
        text-align: center;
    }}
</style>
</head>
<body>
    <div class="header">
        <div>
            <h1>PPC Daily Brief</h1>
            <div class="subtitle">Two Wheels Marketing — Top {len(priorities)} Priority Accounts</div>
        </div>
        <div class="date">{date_display}<br>Day {summary['day_of_month']}/{summary['days_in_month']} ({summary['pct_month_elapsed']:.0%} through month)</div>
    </div>

    <div class="summary-bar">
        <div class="summary-stat">
            <div class="val">{summary['total_accounts_analyzed']}</div>
            <div class="lbl">Accounts</div>
        </div>
        <div class="summary-stat">
            <div class="val">{format_currency(summary['total_mtd_spend'])}</div>
            <div class="lbl">MTD Spend</div>
        </div>
        <div class="summary-stat">
            <div class="val">{format_currency(summary['total_mtd_revenue'])}</div>
            <div class="lbl">MTD Revenue</div>
        </div>
        <div class="summary-stat">
            <div class="val">{format_roas(summary['overall_roas'])}</div>
            <div class="lbl">Portfolio ROAS</div>
        </div>
        <div class="summary-stat">
            <div class="val">{summary['accounts_below_roas_target']}</div>
            <div class="lbl">Below 3x ROAS</div>
        </div>
        <div class="summary-stat">
            <div class="val">{summary['ecommerce_accounts']}</div>
            <div class="lbl">Ecommerce</div>
        </div>
        <div class="summary-stat">
            <div class="val">{summary['lead_gen_accounts']}</div>
            <div class="lbl">Lead Gen</div>
        </div>
    </div>

    <div class="section-title">Priority Accounts</div>
    {priority_rows}

    <div class="footer">
        Generated {generated} | Dashboard: ryanwhitesidemarketer.github.io/daily-brief
    </div>
</body>
</html>"""
    return html


def main():
    data = json.loads(DATA_FILE.read_text())
    html = generate_html(data)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    analysis_date = data.get("analysis_date", datetime.now().strftime("%Y-%m-%d"))
    pdf_path = OUTPUT_DIR / f"daily-brief-{analysis_date}.pdf"
    html_path = OUTPUT_DIR / f"daily-brief-{analysis_date}.html"

    # Save HTML for debugging
    html_path.write_text(html)

    # Generate PDF
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(pdf_path))
        print(f"PDF generated: {pdf_path}")
        print(f"HTML saved: {html_path}")
        return str(pdf_path)
    except Exception as e:
        print(f"ERROR generating PDF: {e}", file=sys.stderr)
        # Fallback: just return HTML path
        print(f"HTML saved: {html_path}")
        return str(html_path)


if __name__ == "__main__":
    result = main()
    print(f"\nOutput: {result}")
