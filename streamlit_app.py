from datetime import date, timedelta

import pandas as pd
import streamlit as st

from planpilot.models import RequestStatus, Role, RuleOutcome
from planpilot.rules import evaluate_request
from planpilot.storage import Storage

st.set_page_config(page_title="PlanPilot", page_icon="🗓️", layout="wide")


@st.cache_resource
def get_storage() -> Storage:
    return Storage()


storage = get_storage()

TEAM_ID = 1  # v1: single seeded team ("Warehouse Ops")

OUTCOME_STYLE = {
    RuleOutcome.AUTO_APPROVED: ("✅", "success"),
    RuleOutcome.NEEDS_REVIEW: ("🟡", "warning"),
    RuleOutcome.BLOCKED: ("⛔", "error"),
}

STATUS_LABEL = {
    RequestStatus.PENDING: "Pending review",
    RequestStatus.APPROVED: "Approved",
    RequestStatus.DENIED: "Denied",
    RequestStatus.CANCELLED: "Cancelled",
}


def show_outcome(outcome: RuleOutcome, reasons: list[str]) -> None:
    icon, level = OUTCOME_STYLE[outcome]
    message = f"{icon} **{outcome.value.replace('_', ' ').title()}** — " + "; ".join(reasons)
    getattr(st, level)(message)


# -- sidebar: simulated login -------------------------------------------------

users = storage.get_users()
user_labels = {f"{u.name} ({u.role.value})": u.id for u in users}
st.sidebar.title("🗓️ PlanPilot")
selected_label = st.sidebar.selectbox("Signed in as", list(user_labels.keys()))
current_user = storage.get_user(user_labels[selected_label])

st.title("PlanPilot — Vacation Planning")
st.caption("Warehouse Ops · Northwind Logistics")

tab_names = ["Request Time Off", "Team Calendar"]
if current_user.role in (Role.LEADER, Role.ADMIN):
    tab_names.insert(1, "Team Review")
    tab_names.insert(2, "Team Rules")
tabs = st.tabs(tab_names)
tab_map = dict(zip(tab_names, tabs))


# -- Request Time Off ----------------------------------------------------------

with tab_map["Request Time Off"]:
    absence_types = storage.get_absence_types()
    team_members = storage.get_team_members(TEAM_ID)
    rules = storage.get_rules(TEAM_ID)
    approved_requests = storage.list_requests(team_id=TEAM_ID, status=RequestStatus.APPROVED)

    st.subheader("New request")
    with st.form("new_request"):
        absence_type = st.selectbox(
            "Absence type", absence_types, format_func=lambda a: a.name
        )
        col1, col2 = st.columns(2)
        start = col1.date_input("Start date", value=date.today() + timedelta(days=7))
        end = col2.date_input("End date", value=date.today() + timedelta(days=9))
        note = st.text_area("Note (optional)")
        submitted = st.form_submit_button("Submit request")

    if submitted:
        if end < start:
            st.error("End date must be on or after the start date.")
        else:
            candidate = type(
                "Candidate",
                (),
                {
                    "user_id": current_user.id,
                    "start_date": start,
                    "end_date": end,
                },
            )()
            evaluation = evaluate_request(candidate, team_members, approved_requests, rules)
            created = storage.create_request(
                user_id=current_user.id,
                absence_type_id=absence_type.id,
                start_date=start,
                end_date=end,
                note=note,
                outcome=evaluation.outcome,
                reasons=evaluation.reasons,
            )
            show_outcome(evaluation.outcome, evaluation.reasons)
            st.rerun()

    st.subheader("My requests")
    my_requests = storage.list_requests(user_id=current_user.id)
    if not my_requests:
        st.write("No requests yet.")
    else:
        for r in reversed(my_requests):
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{r.start_date} → {r.end_date}** · {STATUS_LABEL[r.status]}")
                    if r.outcome:
                        st.caption(f"{r.outcome.value.replace('_', ' ').title()} — " + "; ".join(r.reasons))
                with col2:
                    if r.status in (RequestStatus.PENDING, RequestStatus.APPROVED):
                        if st.button("Cancel", key=f"cancel_{r.id}"):
                            storage.cancel_request(r.id, current_user.id)
                            st.rerun()


# -- Team Review (leader/admin only) ------------------------------------------

if "Team Review" in tab_map:
    with tab_map["Team Review"]:
        st.subheader("Pending requests")
        pending = storage.list_requests(team_id=TEAM_ID, status=RequestStatus.PENDING)
        if not pending:
            st.write("No pending requests. 🎉")
        for req in pending:
            requester = storage.get_user(req.user_id)
            with st.container(border=True):
                st.markdown(f"**{requester.name}** · {req.start_date} → {req.end_date}")
                if req.note:
                    st.caption(req.note)
                if req.reasons:
                    st.write("Rule engine flagged:")
                    for reason in req.reasons:
                        st.write(f"- {reason}")
                col1, col2 = st.columns(2)
                if col1.button("Approve", key=f"approve_{req.id}"):
                    storage.update_request_status(req.id, RequestStatus.APPROVED, current_user.id)
                    st.rerun()
                if col2.button("Deny", key=f"deny_{req.id}"):
                    storage.update_request_status(req.id, RequestStatus.DENIED, current_user.id)
                    st.rerun()


# -- Team Rules (leader/admin only) -------------------------------------------

if "Team Rules" in tab_map:
    with tab_map["Team Rules"]:
        team_rules = storage.get_rules(TEAM_ID)
        coverage_rule = next((r for r in team_rules if r.type == "min_coverage"), None)
        concurrent_rule = next((r for r in team_rules if r.type == "max_concurrent_absences"), None)
        blackout_rules = [r for r in team_rules if r.type == "blackout_period"]

        st.subheader("Coverage & concurrency")
        with st.form("coverage_rule_form"):
            min_pct = st.slider(
                "Minimum team coverage (%)",
                min_value=0,
                max_value=100,
                value=int(round((coverage_rule.config["min_coverage_pct"] if coverage_rule else 0.6) * 100)),
                help="If a request would drop coverage below this on any day, it's flagged for review.",
            )
            max_concurrent = st.number_input(
                "Max concurrent absences",
                min_value=1,
                max_value=max(len(team_members), 1),
                value=concurrent_rule.config["max_concurrent"] if concurrent_rule else 2,
                help="A request that would exceed this is blocked outright.",
            )
            save_coverage = st.form_submit_button("Save")
        if save_coverage:
            storage.upsert_single_rule(TEAM_ID, "min_coverage", {"min_coverage_pct": min_pct / 100})
            storage.upsert_single_rule(TEAM_ID, "max_concurrent_absences", {"max_concurrent": int(max_concurrent)})
            st.success("Rules updated.")
            st.rerun()

        st.subheader("Blackout periods")
        if not blackout_rules:
            st.write("No blackout periods configured.")
        for r in blackout_rules:
            with st.container(border=True):
                bcol1, bcol2 = st.columns([4, 1])
                bcol1.markdown(f"**{r.config['label']}** · {r.config['start']} → {r.config['end']}")
                if bcol2.button("Remove", key=f"remove_blackout_{r.id}"):
                    storage.delete_rule(r.id)
                    st.rerun()

        with st.form("new_blackout_form"):
            st.write("Add a blackout period")
            label = st.text_input("Label")
            bcol1, bcol2 = st.columns(2)
            b_start = bcol1.date_input("Start", value=date.today(), key="blackout_start")
            b_end = bcol2.date_input("End", value=date.today() + timedelta(days=7), key="blackout_end")
            add_blackout = st.form_submit_button("Add blackout period")
        if add_blackout:
            if b_end < b_start:
                st.error("End date must be on or after the start date.")
            elif not label:
                st.error("Label is required.")
            else:
                storage.add_blackout_rule(TEAM_ID, b_start, b_end, label)
                st.rerun()


# -- Team Calendar --------------------------------------------------------------

with tab_map["Team Calendar"]:
    st.subheader("Approved absence")
    default_start = date.today()
    default_end = date.today() + timedelta(days=30)
    col1, col2 = st.columns(2)
    range_start = col1.date_input("From", value=default_start, key="cal_start")
    range_end = col2.date_input("To", value=default_end, key="cal_end")

    approved = storage.list_requests(team_id=TEAM_ID, status=RequestStatus.APPROVED)
    visible = [r for r in approved if r.start_date <= range_end and r.end_date >= range_start]

    if not visible:
        st.write("No approved absence in this range.")
    else:
        rows = [
            {
                "Team member": storage.get_user(r.user_id).name,
                "Start": r.start_date,
                "End": r.end_date,
            }
            for r in visible
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
