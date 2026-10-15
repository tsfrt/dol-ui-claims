"""Spec-driven normalization of the state payload contracts."""

from functools import reduce

from pyspark.sql import Column
from pyspark.sql import functions as F

from state_specs import STATE_SPECS


def _by_state(state_col: Column, per_state) -> Column:
    items = list(STATE_SPECS.items())
    return reduce(lambda acc, kv: acc.when(state_col == kv[0], per_state(*kv)), items[1:], F.when(state_col == items[0][0], per_state(*items[0])))


def _raw(payload: Column, state_col: Column, field: str) -> Column:
    return _by_state(state_col, lambda code, spec: F.get_json_object(payload, spec["fields"][field]))


def _date(raw: Column, fmt: str) -> Column:
    if fmt == "us":
        return F.to_date(raw, "MM/dd/yyyy")
    if fmt == "mmddyyyy":
        return F.to_date(raw, "MMddyyyy")
    if fmt == "yyyyww":
        jan4 = F.to_date(F.concat(F.substring(raw, 1, 4), F.lit("-01-04")))
        iso_dow = ((F.dayofweek(jan4) + 5) % 7) + 1
        week1_monday = F.date_sub(jan4, (iso_dow - 1).cast("int"))
        return F.date_add(week1_monday, ((F.substring(raw, 5, 2).cast("int") - 1) * 7).cast("int"))
    return F.to_date(raw)


def _amount(raw: Column, unit: str) -> Column:
    if unit == "cents":
        return F.round(raw.cast("double") / 100, 2)
    if unit == "currency_string":
        return F.regexp_replace(raw, r"[$,]", "").cast("double")
    return raw.cast("double")


def _decode(raw: Column, codes: dict) -> Column:
    return F.create_map(*[x for canon, code in codes.items() for x in (F.lit(str(code)), F.lit(canon))])[raw]


def parse_columns(state_col: Column, payload: Column) -> dict:
    def week(code, spec):
        d = _date(F.get_json_object(payload, spec["fields"]["week"]), spec["week_format"])
        return F.date_sub(d, 6) if spec["week_anchor"] == "end" else d

    return {
        "raw_status": _raw(payload, state_col, "status"),
        "canonical_status": _by_state(state_col, lambda c, s: _decode(F.get_json_object(payload, s["fields"]["status"]), s["status_codes"])),
        "ssn_norm": F.regexp_replace(_raw(payload, state_col, "ssn"), r"[^0-9]", ""),
        "first_name": F.initcap(F.trim(_raw(payload, state_col, "first_name"))),
        "last_name": F.initcap(F.trim(_raw(payload, state_col, "last_name"))),
        "dob": _by_state(state_col, lambda c, s: _date(F.get_json_object(payload, s["fields"]["dob"]), s["date_format"])),
        "claim_id": _raw(payload, state_col, "claim_id"),
        "week_start": _by_state(state_col, week),
        "weekly_benefit_amount": _by_state(state_col, lambda c, s: _amount(F.get_json_object(payload, s["fields"]["wba"]), s["amount_unit"])),
        "paid_amount": _by_state(state_col, lambda c, s: _amount(F.get_json_object(payload, s["fields"]["paid"]), s["amount_unit"])),
        "employer_name": _raw(payload, state_col, "employer"),
        "county": _raw(payload, state_col, "county"),
        "separation_reason": _by_state(state_col, lambda c, s: _decode(F.get_json_object(payload, s["fields"]["separation"]), s["separation_codes"])),
        "work_search_contacts": _raw(payload, state_col, "work_search").cast("int"),
        "bank_token": _raw(payload, state_col, "bank_token"),
        "device_id": _raw(payload, state_col, "device_id"),
        "ip_address": _raw(payload, state_col, "ip_address"),
    }
