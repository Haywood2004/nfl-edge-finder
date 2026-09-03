import sys
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

URL = "https://nfl-edge-finder.vercel.app/api/bets.csv"
N = 600  # bet rows supported
sample = len(sys.argv) > 1 and sys.argv[1] == "sample"

wb = Workbook()
log = wb.active; log.title = "Bet Log"
raw = wb.create_sheet("Raw")
F = "Arial"
hdr_fill = PatternFill("solid", fgColor="1F3864"); hdr_font = Font(name=F, bold=True, color="FFFFFF")
title_fill = PatternFill("solid", fgColor="0B0F14"); title_font = Font(name=F, bold=True, size=14, color="FFFFFF")
thin = Side(style="thin", color="D9D9D9"); box = Border(top=thin, bottom=thin, left=thin, right=thin)
inp = Font(name=F, color="0000FF")

# ---- Raw
raw["A1"] = f'=IMPORTDATA("{URL}")' if not sample else "date"
if sample:
    heads = ["date","week","market","bet","team","opponent","side","line","odds_decimal","odds_american","book","model_prob","market_prob","edge","confidence","tier","unit_size","result","actual","clv","kickoff_et","card_id","locked_at"]
    for j, h in enumerate(heads, 1): raw.cell(1, j, h)
    rows = [["2026-09-13",1,"Pass Yds","Jayden Daniels Under 204.5","WAS","PHI","Under",204.5,1.909,-110,"betonlineag",0.611,0.492,0.119,56,"paper",1.25,"win",172,0.012,"Sep 13, 4:25 PM",101,"2026-09-02T22:12:59Z"],
            ["2026-09-13",1,"Pass Yds","Trevor Lawrence Under 238.5","JAX","CLE","Under",238.5,1.877,-114,"fanduel",0.591,0.5,0.091,56,"paper",1.0,"loss",251,None,"Sep 13, 1:00 PM",102,"2026-09-02T22:12:59Z"],
            ["2026-09-13",1,"Moneyline","San Francisco 49ers ML","SF","LA","SF",None,2.86,186,"polymarket",0.362,0.35,0.012,52,"paper",0.25,"","",None,"Sep 10, 8:35 PM",103,"2026-09-02T22:12:59Z"],
            ["2026-09-20",2,"Pass Yds","Joe Burrow Over 270.5","CIN","TB","Over",270.5,1.909,-110,"draftkings",0.66,0.5,0.16,61,"flagged",2.0,"win",301,0.02,"Sep 20, 1:00 PM",104,"2026-09-15T18:00:00Z"]]
    for i, r in enumerate(rows, 2):
        for j, v in enumerate(r, 1): raw.cell(i, j, v)
raw["A" + str(N + 5)] = "This tab is filled automatically from the NFL Edge Finder site (IMPORTDATA refreshes about hourly). Do not edit."
raw["A" + str(N + 5)].font = Font(name=F, italic=True, color="808080")

# ---- Bet Log
log.merge_cells("A1:K1"); log["A1"] = "NFL Edge Finder — Paper Bet Log"; log["A1"].fill = title_fill; log["A1"].font = title_font
log.merge_cells("M1:S1"); log["M1"] = "Model Stats"; log["M1"].fill = title_fill; log["M1"].font = title_font
heads = ["Date", "Week", "Market", "Bet", "Odds", "Unit Size", "Win or Loss", "PnL", "Cumulative PnL", "Bankroll", "Tier"]
for j, h in enumerate(heads, 1):
    c = log.cell(2, j, h); c.fill = hdr_fill; c.font = hdr_font; c.alignment = Alignment(horizontal="center")
R = lambda col, r: f"Raw!{col}{r}"
for i in range(N):
    r = i + 3; rr = i + 2   # log row r ↔ Raw row rr
    blank = f'{R("A", rr)}=""'
    log[f"A{r}"] = f'=IF({blank},"",{R("A", rr)})'
    log[f"B{r}"] = f'=IF({blank},"",{R("B", rr)})'
    log[f"C{r}"] = f'=IF({blank},"",{R("C", rr)})'
    log[f"D{r}"] = f'=IF({blank},"",{R("D", rr)}&" ("&{R("J", rr)}&" "&{R("K", rr)}&")")'
    log[f"E{r}"] = f'=IF({blank},"",{R("I", rr)})'
    log[f"F{r}"] = f'=IF({blank},"",{R("Q", rr)}*$N$14)'
    log[f"G{r}"] = f'=IF({blank},"",IF({R("R", rr)}="","pending",{R("R", rr)}))'
    log[f"H{r}"] = f'=IF(A{r}="","",IF(G{r}="win",(E{r}-1)*F{r},IF(G{r}="loss",-F{r},0)))'
    log[f"I{r}"] = f'=IF(A{r}="","",SUM($H$3:H{r}))'
    log[f"J{r}"] = f'=IF(A{r}="","",$N$13+I{r})'
    log[f"K{r}"] = f'=IF({blank},"",{R("P", rr)})'
    for col in "EFH": log[f"{col}{r}"].number_format = "0.00"
    log[f"I{r}"].number_format = "0.00;-0.00"; log[f"J{r}"].number_format = "0.00"
    for col in "ABCDEFGHIJK": log[f"{col}{r}"].font = Font(name=F); log[f"{col}{r}"].border = box

# ---- Model Stats (M..S)
sh = ["Category", "# of Bets", "Won Bets", "Winrate", "Avg. Odds", "ROI", "PnL sum"]
for j, h in enumerate(sh):
    c = log.cell(2, 13 + j, h); c.fill = hdr_fill; c.font = hdr_font; c.alignment = Alignment(horizontal="center")
L = f"$A$3:$A${N+2}"; C_ = f"$C$3:$C${N+2}"; G_ = f"$G$3:$G${N+2}"; E_ = f"$E$3:$E${N+2}"; F_ = f"$F$3:$F${N+2}"; H_ = f"$H$3:$H${N+2}"; K_ = f"$K$3:$K${N+2}"
cats = [("Pass Yds", C_), ("Moneyline", C_), ("flagged (edge ≥15%)", K_), ("paper (edge 4–15%)", K_), ("Total", None)]
row = 3
for name, rng in cats:
    key = {"flagged (edge ≥15%)": "flagged", "paper (edge 4–15%)": "paper"}.get(name, name)
    log[f"M{row}"] = name
    if rng is None:
        n = f'COUNTIF({G_},"win")+COUNTIF({G_},"loss")'; w = f'COUNTIF({G_},"win")'
        avg = f'IFERROR((SUMIF({G_},"win",{E_})+SUMIF({G_},"loss",{E_}))/({n}),0)'
        stake = f'SUMIF({G_},"win",{F_})+SUMIF({G_},"loss",{F_})'
        pnl = f'SUM({H_})'
    else:
        n = f'COUNTIFS({rng},"{key}",{G_},"win")+COUNTIFS({rng},"{key}",{G_},"loss")'; w = f'COUNTIFS({rng},"{key}",{G_},"win")'
        avg = f'IFERROR((SUMIFS({E_},{rng},"{key}",{G_},"win")+SUMIFS({E_},{rng},"{key}",{G_},"loss"))/({n}),0)'
        stake = f'SUMIFS({F_},{rng},"{key}",{G_},"win")+SUMIFS({F_},{rng},"{key}",{G_},"loss")'
        pnl = f'SUMIF({rng},"{key}",{H_})'
    log[f"N{row}"] = f"={n}"; log[f"O{row}"] = f"={w}"
    log[f"P{row}"] = f'=IFERROR(O{row}/N{row},0)'; log[f"P{row}"].number_format = "0.00%"
    log[f"Q{row}"] = f"={avg}"; log[f"Q{row}"].number_format = "0.00"
    log[f"R{row}"] = f'=IFERROR(S{row}/({stake}),0)'; log[f"R{row}"].number_format = "0.00%"
    log[f"S{row}"] = f"={pnl}"; log[f"S{row}"].number_format = "0.00;-0.00"
    for col in "MNOPQRS": log[f"{col}{row}"].font = Font(name=F, bold=(name == "Total")); log[f"{col}{row}"].border = box
    row += 1
# by week
row += 1
log[f"M{row}"] = "By week"; log[f"M{row}"].font = Font(name=F, bold=True); row += 1
wk_start = row
B_ = f"$B$3:$B${N+2}"
for wk in range(1, 19):
    log[f"M{row}"] = wk
    log[f"N{row}"] = f'=COUNTIFS({B_},M{row},{G_},"win")+COUNTIFS({B_},M{row},{G_},"loss")'
    log[f"O{row}"] = f'=COUNTIFS({B_},M{row},{G_},"win")'
    log[f"P{row}"] = f'=IFERROR(O{row}/N{row},0)'; log[f"P{row}"].number_format = "0.00%"
    log[f"Q{row}"] = f'=IFERROR((SUMIFS({E_},{B_},M{row},{G_},"win")+SUMIFS({E_},{B_},M{row},{G_},"loss"))/N{row},0)'; log[f"Q{row}"].number_format = "0.00"
    log[f"R{row}"] = f'=IFERROR(S{row}/(SUMIFS({F_},{B_},M{row},{G_},"win")+SUMIFS({F_},{B_},M{row},{G_},"loss")),0)'; log[f"R{row}"].number_format = "0.00%"
    log[f"S{row}"] = f'=SUMIF({B_},M{row},{H_})'; log[f"S{row}"].number_format = "0.00;-0.00"
    for col in "MNOPQRS": log[f"{col}{row}"].font = Font(name=F); log[f"{col}{row}"].border = box
    row += 1
# settings — placed at M13:N14 area? avoid collision: settings go to U column instead
log["U2"] = "Settings"; log["U2"].fill = hdr_fill; log["U2"].font = hdr_font
log["U3"] = "Starting bankroll (units)"; log["V3"] = 100; log["V3"].font = inp; log["V3"].fill = PatternFill("solid", fgColor="FFFF00")
log["U4"] = "Stake multiplier"; log["V4"] = 1; log["V4"].font = inp; log["V4"].fill = PatternFill("solid", fgColor="FFFF00")
log["U6"] = "Unit Size = quarter-Kelly on a 100u bankroll (0.25–3u) from the site × multiplier."
log["U7"] = "Win or Loss comes from the site's grading after each game; 'pending' until then."
log["U8"] = "A bet locks at the first snapshot where edge ≥ 4% and confidence ≥ 55 (tier 'paper');"
log["U9"] = "'flagged' = edge ≥ 15%, the site's publish bar. Pushes/voids count 0."
for r in range(6, 10): log[f"U{r}"].font = Font(name=F, italic=True, color="595959")
# re-point bankroll/stake refs (used $N$13/$N$14 above) → V3/V4
for i in range(N):
    r = i + 3
    log[f"F{r}"] = log[f"F{r}"].value.replace("$N$14", "$V$4")
    log[f"J{r}"] = log[f"J{r}"].value.replace("$N$13", "$V$3")
widths = {"A": 11, "B": 6, "C": 11, "D": 44, "E": 8, "F": 9, "G": 11, "H": 8, "I": 14, "J": 10, "K": 9, "L": 2, "M": 20, "N": 9, "O": 9, "P": 9, "Q": 9, "R": 9, "S": 9, "T": 2, "U": 26, "V": 8}
for k, v in widths.items(): log.column_dimensions[k].width = v
log.freeze_panes = "A3"
out = "paper_bets_sample.xlsx" if sample else "NFL Edge Finder — Paper Bets.xlsx"
wb.save(out); print("saved", out)
