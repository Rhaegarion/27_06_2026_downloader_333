import bcrypt
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models.user import User

auth_bp = Blueprint(
    "auth", __name__, template_folder="../templates/auth"
)

GENDER_CHOICES = ["Male", "Female", "Other", "Prefer not to say"]


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        name_id = request.form.get("name_id", "").strip().upper()
        password = request.form.get("password", "")

        user = db.session.get(User, name_id) if name_id else None

        if user and bcrypt.checkpw(
            password.encode("utf-8"), user.PasswordHash.encode("utf-8")
        ):
            login_user(user)
            return redirect(url_for("dashboard.index"))

        flash("ID or password is incorrect.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        form = request.form
        name_id = form.get("name_id", "").strip().upper()
        name = form.get("name", "").strip()
        rank = form.get("rank", "").strip()
        id_number = form.get("id_number", "").strip()
        section = form.get("section", "").strip()
        gender = form.get("gender", "").strip()
        password = form.get("password", "")
        confirm_password = form.get("confirm_password", "")

        errors = []
        if not name_id or len(name_id) > 3:
            errors.append("ID (abbreviation) must be 2–3 characters.")
        if not name:
            errors.append("Full name is required.")
        if not password or len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")
        if name_id and db.session.get(User, name_id):
            errors.append(f'The ID "{name_id}" is already registered.')

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "auth/register.html", form=form, genders=GENDER_CHOICES
            )

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        new_user = User(
            NameID=name_id,
            Name=name,
            Rank=rank or None,
            IDnumber=id_number or None,
            Section=section or None,
            Gender=gender or None,
            PasswordHash=password_hash,
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Account created. You can sign in now.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form={}, genders=GENDER_CHOICES)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))
