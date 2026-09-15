from flask import Blueprint, render_template
from flask_login import login_required, current_user

dashboard_bp = Blueprint(
    "dashboard", __name__, template_folder="../templates/dashboard"
)

# Placeholder tiles — wire these to real pages as each module is built.
MODULES = [
    {"name": "New Message", "desc": "Extract JSON/XML, create message", "endpoint": "messages.new", "status": "ready"},
    {"name": "VOIP Table", "desc": "Search and edit VOIP records", "endpoint": None, "status": "planned"},
    {"name": "IP Table", "desc": "Search and edit IP records", "endpoint": None, "status": "planned"},
    {"name": "OSINT", "desc": "Injection and review", "endpoint": None, "status": "planned"},
    {"name": "WAN Allocation", "desc": "Allocation tracking", "endpoint": None, "status": "planned"},
    {"name": "WAN Utilization", "desc": "Utilization tracking", "endpoint": None, "status": "planned"},
]


@dashboard_bp.route("/dashboard")
@login_required
def index():
    return render_template("dashboard/index.html", user=current_user, modules=MODULES)
