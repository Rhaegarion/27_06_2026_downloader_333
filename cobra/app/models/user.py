from flask_login import UserMixin
from app.extensions import db


class User(db.Model, UserMixin):
    """
    Maps to the existing `name_details` table.
    NameID is treated as the login username / primary key (e.g. "JDS").
    """

    __tablename__ = "name_details"

    NameID = db.Column(db.String(50), primary_key=True, nullable=False)
    Name = db.Column(db.String(50), nullable=False)
    Rank = db.Column(db.String(50))
    IDnumber = db.Column(db.String(50))
    Section = db.Column(db.String(50))
    Gender = db.Column(db.String(255))
    PasswordHash = db.Column(db.String(255), nullable=False)

    # Flask-Login needs a string id — NameID already is one.
    def get_id(self):
        return self.NameID
