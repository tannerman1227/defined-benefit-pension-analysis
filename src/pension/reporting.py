"""Charts and the Excel summary workbook.

Figures are written for the README and the notebook. They use the measurement
outputs; they do not recompute liabilities.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

INK = "#1B2838"
MUTED = "#5E6A75"
GRID = "#E6E1D8"
STATUS_COLORS = {
    "active": "#1F4E79",
    "deferred_vested": "#3E8E86",
    "retiree": "#C4A35A",
    "beneficiary": "#8C3A3A",
}
STATUS_LABELS = {
    "active": "Active",
    "deferred_vested": "Deferred vested",
    "retiree": "Retiree",
    "beneficiary": "Beneficiary",
}
STATUS_ORDER = ["active", "deferred_vested", "retiree", "beneficiary"]


def money(value: float, decimals: int = 0) -> str:
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if decimals == 0:
        return f"{sign}${amount:,.0f}"
    return f"{sign}${amount:,.{decimals}f}"


def percent(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def _axes(title: str, subtitle: str):
    fig, ax = plt.subplots(figsize=(10.4, 5.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(left=0.09, right=0.97, top=0.80, bottom=0.18)
    fig.text(0.09, 0.935, title, fontsize=15, color=INK, fontweight="bold", ha="left")
    fig.text(0.09, 0.885, subtitle, fontsize=9.5, color=MUTED, ha="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#D5D0C8")
    ax.spines["bottom"].set_color("#D5D0C8")
    ax.tick_params(colors=INK, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _footnote(fig, text: str) -> None:
    fig.text(0.09, 0.035, text, fontsize=8, color=MUTED, ha="left")


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _millions(value, _position):
    return f"${value / 1e6:.0f}M"


def write_figures(
    directory: Path,
    *,
    census: pd.DataFrame,
    annual: pd.DataFrame,
    curve_maturities: np.ndarray,
    curve_spots: np.ndarray,
    liability: dict,
    rate_scenarios: list[dict],
    mortality_scenarios: list[dict],
    prt: dict,
    measurement_date: str,
) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    footnote = f"Synthetic census. Measurement {measurement_date}. Not a quote and not actuarial advice."
    paths = [
        _census_composition(directory / "census_composition.png", census, footnote),
        _age_distribution(directory / "age_distribution.png", census, footnote),
        _cash_flows(directory / "projected_cash_flows.png", annual, footnote),
        _pv_profile(directory / "present_value_profile.png", annual, footnote),
        _discount_curve(directory / "discount_curve.png", curve_maturities, curve_spots, measurement_date, footnote),
        _liability_bars(directory / "liability_comparison.png", liability, prt, footnote),
        _funded_status(directory / "funded_status_by_rates.png", rate_scenarios, footnote),
        _mortality(directory / "mortality_sensitivity.png", mortality_scenarios, footnote),
        _prt(directory / "prt_liftout_vs_termination.png", prt, footnote),
    ]
    return paths


def _census_composition(path: Path, census: pd.DataFrame, footnote: str) -> Path:
    counts = census.groupby("status").size().reindex(STATUS_ORDER)
    benefits = census.groupby("status")["annual_benefit"].sum().reindex(STATUS_ORDER)
    labels = [STATUS_LABELS[status] for status in STATUS_ORDER]
    colors = [STATUS_COLORS[status] for status in STATUS_ORDER]
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 5.8))
    fig.patch.set_facecolor("white")
    fig.subplots_adjust(left=0.08, right=0.97, top=0.78, bottom=0.18, wspace=0.28)
    fig.text(0.08, 0.935, "Who is in the plan", fontsize=15, color=INK, fontweight="bold")
    fig.text(
        0.08,
        0.885,
        "Clean census after hard data exceptions are removed. Benefits are tape amounts, not present values.",
        fontsize=9.5,
        color=MUTED,
    )
    for ax, values, title, formatter in (
        (axes[0], counts.to_numpy(dtype=float), "Participants", lambda v, _p: f"{v:,.0f}"),
        (axes[1], benefits.to_numpy(dtype=float), "Annual benefit on the tape", _millions),
    ):
        ax.bar(labels, values, color=colors, width=0.72)
        ax.set_title(title, loc="left", color=INK, fontsize=11, pad=8)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(formatter))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#D5D0C8")
        ax.spines["bottom"].set_color("#D5D0C8")
        ax.tick_params(colors=INK, labelsize=8)
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", labelrotation=15)
    _footnote(fig, footnote)
    _save(fig, path)
    return path


def _age_distribution(path: Path, census: pd.DataFrame, footnote: str) -> Path:
    fig, ax = _axes("Age profile of the clean census", "Headcount by integer age. In-pay lives sit to the right of the working population.")
    fig.subplots_adjust(top=0.74)
    bins = np.arange(25, 101, 2)
    bottoms = np.zeros(len(bins) - 1)
    for status in STATUS_ORDER:
        ages = census.loc[census["status"] == status, "age"].dropna().to_numpy()
        counts, _edges = np.histogram(ages, bins=bins)
        ax.bar(
            bins[:-1],
            counts,
            width=1.8,
            bottom=bottoms,
            color=STATUS_COLORS[status],
            label=STATUS_LABELS[status],
            align="edge",
        )
        bottoms = bottoms + counts
    ax.set_xlabel("Age last birthday at the measurement date", color=INK)
    ax.set_ylabel("Participants", color=INK)
    ax.legend(frameon=False, ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.02), fontsize=8)
    _footnote(fig, footnote)
    _save(fig, path)
    return path


def _yearly(annual: pd.DataFrame, column: str) -> pd.DataFrame:
    table = annual.pivot(index="calendar_year", columns="status", values=column).fillna(0.0)
    for status in STATUS_ORDER:
        if status not in table.columns:
            table[status] = 0.0
    table = table[STATUS_ORDER]
    # Keep the horizon a chart can still be read on. The tail after 60 years is small.
    return table.iloc[:60]


def _cash_flows(path: Path, annual: pd.DataFrame, footnote: str) -> Path:
    table = _yearly(annual, "expected_benefit_pbo")
    fig, ax = _axes(
        "Expected benefit payments",
        "Probability-weighted PBO benefits by year, including salary growth on active benefits. First 60 years.",
    )
    ax.stackplot(
        table.index,
        [table[status].to_numpy() for status in STATUS_ORDER],
        colors=[STATUS_COLORS[status] for status in STATUS_ORDER],
        labels=[STATUS_LABELS[status] for status in STATUS_ORDER],
    )
    ax.set_ylabel("Expected payment", color=INK)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_millions))
    ax.set_xlim(table.index.min(), table.index.max())
    ax.legend(frameon=False, ncol=4, loc="upper right", fontsize=8)
    _footnote(fig, footnote)
    _save(fig, path)
    return path


def _pv_profile(path: Path, annual: pd.DataFrame, footnote: str) -> Path:
    table = _yearly(annual, "pbo_present_value")
    fig, ax = _axes(
        "Where the PBO sits on the calendar",
        "Present value of each year's expected PBO payments on the HQM curve. First 60 years.",
    )
    ax.stackplot(
        table.index,
        [table[status].to_numpy() for status in STATUS_ORDER],
        colors=[STATUS_COLORS[status] for status in STATUS_ORDER],
        labels=[STATUS_LABELS[status] for status in STATUS_ORDER],
    )
    ax.set_ylabel("Present value", color=INK)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_millions))
    ax.set_xlim(table.index.min(), table.index.max())
    ax.legend(frameon=False, ncol=4, loc="upper right", fontsize=8)
    _footnote(fig, footnote)
    _save(fig, path)
    return path


def _discount_curve(path, maturities, spots, measurement_date, footnote) -> Path:
    fig, ax = _axes(
        "Treasury HQM corporate spot curve",
        f"End-of-month semiannual spots at {measurement_date}, with parallel 100 bp shocks used in the sensitivity.",
    )
    show = maturities <= 40
    maturity = maturities[show]
    base = spots[show] * 100
    ax.plot(maturity, base, color=INK, linewidth=2.2, label="HQM spot")
    ax.plot(maturity, base + 1.0, color="#1F4E79", linewidth=1.3, linestyle="--", label="+100 bp")
    ax.plot(maturity, base - 1.0, color="#8C3A3A", linewidth=1.3, linestyle="--", label="−100 bp")
    ax.set_ylabel("Spot rate (%)", color=INK)
    ax.set_xlabel("Maturity (years)", color=INK)
    ax.set_xlim(0, 40)
    ax.legend(frameon=False, fontsize=8)
    _footnote(fig, footnote + " Published through 100 years; chart shows 40.")
    _save(fig, path)
    return path


def _liability_bars(path, liability, prt, footnote) -> Path:
    labels = ["ABO", "PBO", "Pricing PV\nof benefits", "Termination\npremium"]
    values = [
        liability["abo"],
        liability["pbo"],
        prt["termination_pv_benefits"],
        prt["termination_premium"],
    ]
    colors = ["#8AA0B4", "#1F4E79", "#3E8E86", "#8C3A3A"]
    fig, ax = _axes(
        "Accounting liability and the termination indication",
        "ABO is the accrued benefit. PBO adds salary growth and the unreduced 30-and-out subsidy. The premium uses the pricing basis.",
    )
    bars = ax.bar(labels, values, color=colors, width=0.68)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_millions))
    ax.set_ylabel("Present value", color=INK)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            money(value),
            ha="center",
            va="bottom",
            color=INK,
            fontsize=8,
        )
    ax.set_ylim(0, max(values) * 1.14)
    _footnote(fig, footnote)
    _save(fig, path)
    return path


def _funded_status(path, scenarios, footnote) -> Path:
    labels = [f"{row['shock_bp']:+.0f} bp" if row["shock_bp"] else "Base" for row in scenarios]
    ratios = [row["funded_ratio"] * 100 for row in scenarios]
    colors = ["#8C3A3A" if row["shock_bp"] < 0 else "#1F4E79" if row["shock_bp"] > 0 else "#C4A35A" for row in scenarios]
    fig, ax = _axes(
        "Funded status moves with the discount curve",
        "Assets are held at the stated $200 million. Only the PBO is repriced. A lower curve raises the liability.",
    )
    ax.bar(labels, ratios, color=colors, width=0.68)
    ax.axhline(100, color=INK, linewidth=0.8, linestyle=":")
    ax.set_ylabel("Assets / PBO (%)", color=INK)
    for index, ratio in enumerate(ratios):
        ax.text(index, ratio, f"{ratio:.1f}%", ha="center", va="bottom", color=INK, fontsize=8)
    ax.set_ylim(0, max(ratios) * 1.15)
    _footnote(fig, footnote)
    _save(fig, path)
    return path


def _mortality(path, scenarios, footnote) -> Path:
    labels = [row["label"] for row in scenarios]
    values = [row["pbo"] for row in scenarios]
    fig, ax = _axes(
        "PBO under three mortality views",
        "Same census and the same HQM curve. Only future longevity changes.",
    )
    colors = ["#8AA0B4", "#1F4E79", "#3E8E86"]
    bars = ax.bar(labels, values, color=colors[: len(values)], width=0.62)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_millions))
    ax.set_ylabel("PBO", color=INK)
    for bar, row in zip(bars, scenarios):
        change = row["change_vs_base"] * 100
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{money(row['pbo'])}\n{change:+.1f}%",
            ha="center",
            va="bottom",
            color=INK,
            fontsize=8,
        )
    ax.set_ylim(0, max(values) * 1.18)
    ax.tick_params(axis="x", labelsize=8)
    _footnote(fig, footnote)
    _save(fig, path)
    return path


def _prt(path, prt, footnote) -> Path:
    fig, ax = _axes(
        "Lift-out versus full termination",
        "Premium is the illustrative buyout price. Lift-out releases in-pay PBO. Termination buys the accrued benefit.",
    )
    labels = ["Retiree lift-out", "Full termination"]
    released = [prt["liftout_pbo_released"], prt["termination_abo"]]
    premiums = [prt["liftout_premium"], prt["termination_premium"]]
    x = np.arange(len(labels))
    width = 0.34
    ax.bar(x - width / 2, released, width, color="#1F4E79", label="Accounting liability released")
    ax.bar(x + width / 2, premiums, width, color="#8C3A3A", label="Illustrative premium")
    ax.set_xticks(x, labels)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_millions))
    ax.set_ylabel("Dollars", color=INK)
    ax.legend(frameon=False, fontsize=8)
    _footnote(fig, footnote + " Termination bar is ABO.")
    _save(fig, path)
    return path


def write_workbook(path: Path, results: dict, annual: pd.DataFrame, findings: pd.DataFrame) -> None:
    """One workbook a reviewer can open without running the model."""
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True, name="Calibri", size=10)
    body_font = Font(name="Calibri", size=10, color="1B2838")
    thin = Border(
        left=Side(style="thin", color="E6E1D8"),
        right=Side(style="thin", color="E6E1D8"),
        top=Side(style="thin", color="E6E1D8"),
        bottom=Side(style="thin", color="E6E1D8"),
    )

    def write_sheet(name: str, rows: list[list], money_cols: set[int] | None = None, percent_cols: set[int] | None = None):
        sheet = book.active if book.active.title == "Sheet" and book.active.max_row == 1 else book.create_sheet(name)
        if sheet.title == "Sheet":
            sheet.title = name
        for row_index, row in enumerate(rows, start=1):
            for col_index, value in enumerate(row, start=1):
                cell = sheet.cell(row_index, col_index, value)
                cell.font = header_font if row_index == 1 else body_font
                cell.border = thin
                cell.alignment = Alignment(vertical="center", wrap_text=(row_index == 1))
                if row_index == 1:
                    cell.fill = header_fill
                elif money_cols and col_index in money_cols and isinstance(value, (int, float)):
                    cell.number_format = '$#,##0'
                elif percent_cols and col_index in percent_cols and isinstance(value, (int, float)):
                    cell.number_format = '0.0%'
        for col_index in range(1, len(rows[0]) + 1):
            width = max(len(str(row[col_index - 1])) for row in rows if col_index - 1 < len(row))
            sheet.column_dimensions[get_column_letter(col_index)].width = min(max(width + 3, 14), 42)
        sheet.auto_filter.ref = sheet.dimensions
        sheet.freeze_panes = "A2"
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToPage = True
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 1
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        return sheet

    liability = results["liability"]
    prt = results["prt"]
    write_sheet(
        "Summary",
        [
            ["Item", "Value"],
            ["Plan", results["plan_name"]],
            ["Measurement date", results["measurement_date"]],
            ["Clean participants", results["census"]["clean_records"]],
            ["Records excluded", results["validation"]["records_excluded"]],
            ["ABO", liability["abo"]],
            ["PBO", liability["pbo"]],
            ["Market value of assets", liability["assets"]],
            ["Surplus (assets − PBO)", liability["surplus"]],
            ["Funded ratio on PBO", liability["funded_ratio"]],
            ["Single effective discount rate", liability["effective_annual_rate"]],
            ["Effective duration (100 bp)", liability["effective_duration"]],
            ["Average payment time (years)", liability["average_payment_time"]],
            ["Liability DV01", liability["dv01"]],
            ["Lift-out premium", prt["liftout_premium"]],
            ["Lift-out settlement loss", prt["liftout_settlement_loss"]],
            ["Residual funded ratio after lift-out", prt["residual_funded_ratio"]],
            ["Termination premium", prt["termination_premium"]],
            ["Termination cash shortfall", prt["termination_cash_shortfall"]],
            ["Data", "Synthetic. Not actuarial advice."],
        ],
    )
    summary = book["Summary"]
    for row in (6, 7, 8, 9, 14, 15, 16, 18, 19):
        summary.cell(row, 2).number_format = '$#,##0'
    for row in (10, 17):
        summary.cell(row, 2).number_format = "0.0%"
    summary.cell(11, 2).number_format = "0.00%"
    summary.cell(4, 2).number_format = "#,##0"
    summary.cell(5, 2).number_format = "#,##0"
    summary.cell(12, 2).number_format = "0.00"
    summary.cell(13, 2).number_format = "0.00"

    rate_rows = [["Shock (bp)", "PBO", "Funded ratio", "Surplus"]]
    for row in results["rate_scenarios"]:
        rate_rows.append([row["shock_bp"], row["pbo"], row["funded_ratio"], row["surplus"]])
    write_sheet("Rate scenarios", rate_rows, money_cols={2, 4}, percent_cols={3})

    mort_rows = [["Scenario", "PBO", "Change vs base"]]
    for row in results["mortality_scenarios"]:
        mort_rows.append([row["label"], row["pbo"], row["change_vs_base"]])
    write_sheet("Mortality scenarios", mort_rows, money_cols={2}, percent_cols={3})

    rule_rows = [["Rule", "Findings"]]
    for rule, count in results["validation"]["findings_by_rule"].items():
        rule_rows.append([rule, count])
    write_sheet("Validation counts", rule_rows)

    finding_rows = [["Participant", "Status", "Severity", "Rule", "Message"]]
    for record in findings.itertuples(index=False):
        finding_rows.append([record.participant_id, record.status, record.severity, record.rule_id, record.message])
    write_sheet("Validation detail", finding_rows)

    flow_rows = [["Year", "Status", "Expected ABO benefit", "Expected PBO benefit", "PBO present value"]]
    for record in annual.itertuples(index=False):
        flow_rows.append(
            [
                int(record.calendar_year),
                record.status,
                float(record.expected_benefit_abo),
                float(record.expected_benefit_pbo),
                float(record.pbo_present_value),
            ]
        )
    write_sheet("Annual cash flows", flow_rows, money_cols={3, 4, 5})

    curve_rows = [["Maturity (years)", "HQM spot"]]
    for tenor, rate in results["discount_curve"]["spots"].items():
        curve_rows.append([float(tenor), rate])
    write_sheet("Discount curve", curve_rows, percent_cols={2})

    book.save(path)
