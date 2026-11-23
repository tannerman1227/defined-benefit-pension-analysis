"""Illustrative annuity buyout premium and two deal structures.

The premium is not a carrier quote. It is the price of a transparent
indication:

    premium = (PV of benefits on the pricing basis + PV of expenses)
              / (1 - premium load)

The pricing basis uses the same benefit cash-flow engine as the accounting
valuation, with two stated changes: mortality rates are multiplied by
`pricing_qx_multiplier` (below 1.0 means longer life), and the HQM spot curve
is shifted by `pricing_spread_bp`. Expenses are a flat dollar amount per
contract per year while the contract is in force, including while a deferred
benefit has not yet started. The load covers risk, capital, and margin and is
applied as a percent of premium, so it grosses up both benefits and expenses.

Deal comparison
- Retiree lift-out: buy annuities only for retirees and beneficiaries, in the
  form already in pay. The plan keeps actives and deferred vesteds. Because
  those in-pay benefits are fully accrued, their ABO and PBO are the same.
  Paying a premium above that liability, out of plan assets, is a settlement
  and usually leaves the remaining plan less well funded. That dilution is
  the central lift-out tradeoff.
- Full termination: curtail future salary and service accruals, then buy
  annuities for the accrued benefit of everyone. The benefit purchased is the
  ABO benefit, not the PBO benefit. The drop from PBO to ABO is the
  curtailment. The premium minus ABO is the settlement loss. The plan must
  contribute if the premium exceeds assets.

Settlement figures follow that arithmetic. They are an illustration of ASC 715
settlement and curtailment mechanics, not a completed accounting memo.
"""

from __future__ import annotations

from pension.assumptions import Assumptions
from pension.cashflows import STATUSES, CashFlowBook
from pension.discount import DiscountCurve
from pension.liability import present_value

IN_PAY = ("retiree", "beneficiary")


def indication(
    book: CashFlowBook,
    curve: DiscountCurve,
    assumptions: Assumptions,
    *,
    basis: str,
    statuses: tuple[str, ...] = STATUSES,
) -> dict[str, float]:
    """Price one population on an already-projected pricing-basis cash-flow book."""
    benefits = book.benefit(basis, statuses)
    contracts = book.contracts(statuses)
    pv_benefits = present_value(benefits, book.times, curve)
    pv_expenses = present_value(contracts * assumptions.expense_per_month, book.times, curve)
    if assumptions.premium_load >= 1:
        raise ValueError("Premium load must be below 100%")
    premium = (pv_benefits + pv_expenses) / (1.0 - assumptions.premium_load)
    return {
        "pv_benefits": pv_benefits,
        "pv_expenses": pv_expenses,
        "premium": premium,
        "lives": float((book.participants["status"].isin(statuses)).sum()) if len(book.participants) else 0.0,
    }


def deal_comparison(
    *,
    accounting_pbo: float,
    accounting_abo: float,
    in_pay_pbo: float,
    liftout: dict[str, float],
    termination: dict[str, float],
    assets: float,
) -> dict[str, float]:
    """Accounting and cash consequences of a lift-out and of a termination.

    `liftout` and `termination` are outputs of `indication`. Termination is
    priced on ABO benefits. Lift-out is priced on the in-pay benefits.
    """
    liftout_premium = liftout["premium"]
    termination_premium = termination["premium"]
    residual_assets = assets - liftout_premium
    residual_pbo = accounting_pbo - in_pay_pbo
    curtailment_gain = accounting_pbo - accounting_abo
    termination_settlement_loss = termination_premium - accounting_abo
    return {
        "liftout_lives": liftout["lives"],
        "liftout_premium": liftout_premium,
        "liftout_pv_benefits": liftout["pv_benefits"],
        "liftout_pv_expenses": liftout["pv_expenses"],
        "liftout_pbo_released": in_pay_pbo,
        "liftout_settlement_loss": liftout_premium - in_pay_pbo,
        "liftout_premium_over_pbo": (liftout_premium / in_pay_pbo) - 1.0 if in_pay_pbo else float("nan"),
        "residual_assets": residual_assets,
        "residual_pbo": residual_pbo,
        "residual_surplus": residual_assets - residual_pbo,
        "residual_funded_ratio": residual_assets / residual_pbo if residual_pbo else float("nan"),
        "liftout_cash_shortfall": max(0.0, liftout_premium - assets),
        "termination_lives": termination["lives"],
        "termination_premium": termination_premium,
        "termination_pv_benefits": termination["pv_benefits"],
        "termination_pv_expenses": termination["pv_expenses"],
        "termination_abo": accounting_abo,
        "termination_pbo_before_curtailment": accounting_pbo,
        "curtailment_gain": curtailment_gain,
        "termination_settlement_loss": termination_settlement_loss,
        "termination_net_accounting_cost": termination_premium - accounting_pbo,
        "termination_premium_over_abo": (termination_premium / accounting_abo) - 1.0 if accounting_abo else float("nan"),
        "termination_cash_shortfall": max(0.0, termination_premium - assets),
        "assets": assets,
    }
