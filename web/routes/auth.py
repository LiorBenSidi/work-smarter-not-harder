"""Auth routes — register / login / logout. OWNER: Shiri.

Mandatory (course): hash passwords with werkzeug; auth-gate protected endpoints; validate input
(NoSQL-injection-safe). How you structure it is up to you — implement behind these URLs.
"""
from flask import Blueprint, jsonify

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
def register():
    return jsonify(detail="register not implemented yet"), 501


@auth_bp.post("/login")
def login():
    return jsonify(detail="login not implemented yet"), 501


@auth_bp.post("/logout")
def logout():
    return jsonify(detail="logout not implemented yet"), 501
