from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import io
import re
from datetime import datetime
from app.database import supabase
from app.signal_engine import clean_price

def parse_holdings(holdings_text: str) -> list:
    pattern = r'(\d+[\d,]*)\s+([A-Z]+)\s+(?:at|@)?\s*[₦]?(\d+[\d.]*)'
    matches = re.findall(pattern, holdings_text.upper())
    results = []
    for qty, ticker, buy_price in matches:
        results.append({
            "qty": int(qty.replace(",", "")),
            "ticker": ticker,
            "buy_price": float(buy_price)
        })
    return results

def get_sector(ticker: str) -> str:
    banking = ["GTCO", "ZENITHBANK", "ACCESSCORP", "UBA", "FIDELITYBK", 
               "FCMB", "WEMABANK", "STANBIC", "FIRSTHOLDCO", "JAIZBANK"]
    telecoms = ["MTNN", "AIRTELAFRI"]
    oil_gas = ["SEPLAT", "OANDO", "TOTAL", "ETERNA", "CONOIL", "ARADEL"]
    consumer = ["DANGSUGAR", "NASCON", "FLOURMILL", "NESTLE", "UNILEVER", 
                "CADBURY", "NB", "GUINNESS", "HONYFLOUR", "BUAFOODS"]
    cement = ["DANGCEM", "BUACEMENT", "WAPCO"]
    insurance = ["AIICO", "MANSARD", "CUSTODIAN", "NEM", "CORNERST"]
    
    if ticker in banking: return "Banking"
    if ticker in telecoms: return "Telecoms"
    if ticker in oil_gas: return "Oil & Gas"
    if ticker in consumer: return "Consumer Goods"
    if ticker in cement: return "Cement/Construction"
    if ticker in insurance: return "Insurance"
    return "Other"

def generate_portfolio_pdf(holdings_text: str, user_name: str) -> bytes:
    holdings = parse_holdings(holdings_text)
    if not holdings:
        return None
    
    portfolio = []
    total_value = 0
    total_cost = 0
    
    for h in holdings:
        result = supabase.table("stocks")\
            .select("price, signal, company")\
            .eq("ticker", h["ticker"])\
            .order("scraped_at", desc=True)\
            .limit(1)\
            .execute()
        
        if result.data:
            current_price = clean_price(result.data[0]["price"])
            company = result.data[0]["company"]
            signal = result.data[0]["signal"]
        else:
            current_price = h["buy_price"]
            company = h["ticker"]
            signal = "NO DATA"
        
        current_value = h["qty"] * current_price
        cost_basis = h["qty"] * h["buy_price"]
        pnl = current_value - cost_basis
        pnl_pct = ((current_price - h["buy_price"]) / h["buy_price"]) * 100
        sector = get_sector(h["ticker"])
        
        total_value += current_value
        total_cost += cost_basis
        
        portfolio.append({
            "ticker": h["ticker"],
            "company": company,
            "quantity": h["qty"],
            "buy_price": h["buy_price"],
            "current_price": current_price,
            "current_value": current_value,
            "cost_basis": cost_basis,
            "pnl": pnl,
            "pnl_pct": round(pnl_pct, 2),
            "signal": signal,
            "sector": sector
        })
    
    total_pnl = total_value - total_cost
    total_pnl_pct = ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0
    
    # sector breakdown
    sectors = {}
    for h in portfolio:
        s = h["sector"]
        sectors[s] = sectors.get(s, 0) + h["current_value"]
    
    # concentration risk
    max_weight = max(h["current_value"] / total_value * 100 for h in portfolio) if portfolio else 0
    concentration_risk = "High" if max_weight > 40 else "Medium" if max_weight > 25 else "Low"
    
    # generate PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                           rightMargin=0.75*inch, leftMargin=0.75*inch,
                           topMargin=0.75*inch, bottomMargin=0.75*inch)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], 
                                  fontSize=18, textColor=colors.HexColor('#1a1a2e'),
                                  alignment=TA_CENTER)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'],
                                    fontSize=12, textColor=colors.HexColor('#16213e'),
                                    spaceAfter=6)
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'],
                                   fontSize=9, leading=14)
    
    story = []
    
    # header
    story.append(Paragraph("StockOracle", title_style))
    story.append(Paragraph("Portfolio Audit Report", ParagraphStyle('sub', 
                            parent=styles['Normal'], fontSize=12, 
                            alignment=TA_CENTER, textColor=colors.grey)))
    story.append(Paragraph(f"Prepared for: {user_name} | {datetime.now().strftime('%B %d, %Y')}", 
                           ParagraphStyle('date', parent=styles['Normal'], 
                                         fontSize=9, alignment=TA_CENTER, 
                                         textColor=colors.grey)))
    story.append(Spacer(1, 0.3*inch))
    
    # summary box
    summary_data = [
        ["Total Portfolio Value", "Total Cost", "Total P&L", "Concentration Risk"],
        [f"₦{total_value:,.0f}", f"₦{total_cost:,.0f}", 
         f"₦{total_pnl:,.0f} ({total_pnl_pct:.1f}%)", concentration_risk]
    ]
    summary_table = Table(summary_data, colWidths=[1.6*inch]*4)
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('FONTSIZE', (0,1), (-1,1), 11),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWHEIGHT', (0,0), (-1,-1), 25),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('TEXTCOLOR', (2,1), (2,1), colors.green if total_pnl >= 0 else colors.red),
        ('TEXTCOLOR', (3,1), (3,1), 
         colors.red if concentration_risk == "High" else 
         colors.orange if concentration_risk == "Medium" else colors.green),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.25*inch))
    
    # holdings table
    story.append(Paragraph("Holdings Breakdown", heading_style))
    holdings_data = [["Ticker", "Company", "Qty", "Buy ₦", "Now ₦", "Value ₦", "P&L%", "Signal"]]
    for h in portfolio:
        pnl_color = colors.green if h["pnl_pct"] >= 0 else colors.red
        holdings_data.append([
            h["ticker"],
            h["company"][:20] if len(h["company"]) > 20 else h["company"],
            f"{h['quantity']:,}",
            f"₦{h['buy_price']:,.0f}",
            f"₦{h['current_price']:,.0f}",
            f"₦{h['current_value']:,.0f}",
            f"{h['pnl_pct']}%",
            h["signal"][:4] if h["signal"] else "—"
        ])
    
    col_widths = [0.7*inch, 1.8*inch, 0.6*inch, 0.7*inch, 0.7*inch, 0.9*inch, 0.5*inch, 0.5*inch]
    holdings_table = Table(holdings_data, colWidths=col_widths)
    holdings_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#16213e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWHEIGHT', (0,0), (-1,-1), 18),
        ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    story.append(holdings_table)
    story.append(Spacer(1, 0.25*inch))
    
    # sector breakdown
    story.append(Paragraph("Sector Allocation", heading_style))
    sector_data = [["Sector", "Value (₦)", "Weight (%)"]]
    for sector, value in sorted(sectors.items(), key=lambda x: x[1], reverse=True):
        weight = (value / total_value * 100) if total_value > 0 else 0
        sector_data.append([sector, f"₦{value:,.0f}", f"{weight:.1f}%"])
    
    sector_table = Table(sector_data, colWidths=[2*inch, 2*inch, 1.5*inch])
    sector_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#16213e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
        ('ROWHEIGHT', (0,0), (-1,-1), 20),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    story.append(sector_table)
    story.append(Spacer(1, 0.25*inch))
    
    # risk notes
    story.append(Paragraph("Risk Assessment", heading_style))
    risk_notes = []
    
    for h in portfolio:
        weight = h["current_value"] / total_value * 100
        if weight > 40:
            risk_notes.append(f"{h['ticker']} represents {weight:.1f}% of your portfolio — dangerously concentrated. Consider reducing.")
        elif weight > 25:
            risk_notes.append(f"{h['ticker']} at {weight:.1f}% is above comfortable levels. Monitor closely.")
    
    if len(sectors) < 3:
        risk_notes.append("Your portfolio is concentrated in fewer than 3 sectors. Diversification is recommended.")
    
    sells = [h for h in portfolio if "SELL" in h["signal"].upper()]
    if sells:
        tickers = ", ".join(h["ticker"] for h in sells)
        risk_notes.append(f"{tickers} currently showing SELL signals. Review these positions.")
    
    if not risk_notes:
        risk_notes.append("No major risk flags detected. Portfolio appears reasonably balanced.")
    
    for note in risk_notes:
        story.append(Paragraph(f"• {note}", normal_style))
    
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(
        "Disclaimer: This report is generated by StockOracle AI for informational purposes only. "
        "It does not constitute financial advice. Always consult a licensed financial advisor before making investment decisions.",
        ParagraphStyle('disclaimer', parent=styles['Normal'], fontSize=7, 
                      textColor=colors.grey, alignment=TA_CENTER)
    ))
    
    doc.build(story)
    return buffer.getvalue()