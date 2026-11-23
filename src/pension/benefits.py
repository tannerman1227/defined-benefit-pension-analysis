"""Plan benefit amounts under the stated retirement assumption.

The census stores a normal-retirement-age life annuity for participants who
are not yet in pay, and the actual payment for retirees and beneficiaries.

Retirement behavior, used for both ABO and PBO: a participant commences at the
earliest age at which the benefit is unreduced. That is age 62 when 30 years
of service will have been earned by then (projected service for actives,
frozen service for deferred vesteds), and age 65 otherwise. Someone already
past that age and still active is assumed to retire immediately. There is no
actuarial increase for late retirement.

ABO uses the tape benefit multiplied by the early-retirement factor that
applies given service already earned. PBO, on the projected unit credit
method, uses the same tape benefit grown with the salary scale and multiplied
by the early-retirement factor that applies given projected service. For a
final-average-pay formula that is linear in service, future service accruals
are normal cost and cancel out of the PBO; they remain only to the extent
they unlock the unreduced 30-and-out subsidy.

Deferred vesteds get no salary growth. In-pay benefits are already the
payment amount, so ABO and PBO are equal.
"""

from __future__ import annotations

from pension.assumptions import Assumptions


def commencement_age(age: int, service: float, status: str, assumptions: Assumptions) -> int:
    """Integer age at which the valued benefit is assumed to start."""
    if status in {"retiree", "beneficiary"}:
        return age
    if age >= assumptions.normal_retirement_age:
        return age

    if status == "deferred_vested":
        if service >= assumptions.unreduced_service:
            return max(age, assumptions.unreduced_age)
        return assumptions.normal_retirement_age

    # Active. Project service only to decide when unreduced retirement is available.
    if service >= assumptions.unreduced_service and age >= assumptions.unreduced_age:
        return age
    if age < assumptions.unreduced_age:
        service_at_unreduced = service + (assumptions.unreduced_age - age)
        if service_at_unreduced >= assumptions.unreduced_service:
            return assumptions.unreduced_age
    return assumptions.normal_retirement_age


def early_retirement_factor(
    retirement_age: int,
    eligibility_service: float,
    assumptions: Assumptions,
) -> float:
    """Fraction of the age-65 life annuity payable at `retirement_age`."""
    if retirement_age >= assumptions.normal_retirement_age:
        return 1.0
    if eligibility_service >= assumptions.unreduced_service:
        return 1.0
    years_early = assumptions.normal_retirement_age - retirement_age
    return max(0.0, 1.0 - assumptions.early_reduction_per_year * years_early)


def valued_annual_benefits(
    *,
    age: int,
    service: float | None,
    status: str,
    tape_annual_benefit: float,
    assumptions: Assumptions,
) -> tuple[float, float, int]:
    """Return (ABO annual benefit, PBO annual benefit, commencement age).

    The annual amounts are the life-contingent pension payable at commencement,
    before mortality and interest. In-pay records return the tape payment.
    """
    if status in {"retiree", "beneficiary"}:
        return tape_annual_benefit, tape_annual_benefit, age

    if service is None:
        raise ValueError(f"{status} participant is missing credited service")
    retire_at = commencement_age(age, service, status, assumptions)
    years = retire_at - age
    if years < 0:
        raise ValueError("Commencement age is before the attained age")

    abo_factor = early_retirement_factor(retire_at, service, assumptions)
    abo = tape_annual_benefit * abo_factor

    if status == "active" and years > 0:
        projected_service = min(
            assumptions.max_credited_service,
            service + years,
        )
        pay_growth = (1.0 + assumptions.salary_scale) ** years
    else:
        projected_service = service
        pay_growth = 1.0
    pbo_factor = early_retirement_factor(retire_at, projected_service, assumptions)
    pbo = tape_annual_benefit * pay_growth * pbo_factor
    return abo, pbo, retire_at
