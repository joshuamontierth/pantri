from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import config, quantities, scan, services
from .models import Household, Invite, Membership

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))
templates.env.globals["format_quantity"] = quantities.format_quantity
templates.env.globals["format_part"] = quantities.format_part
templates.env.globals["unit_label"] = quantities.unit_label
templates.env.globals["COMMON_UNITS"] = quantities.COMMON_UNITS
templates.env.globals["OTHER_LABEL"] = services.OTHER_LABEL
templates.env.globals["scan_enabled"] = scan.enabled
templates.env.globals["MAX_PHOTOS"] = scan.MAX_PHOTOS

# Inline stroke icons (24px grid), drawn in currentColor.
_ICONS = {
    "more": '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-9 9"/>',
    "camera": '<path d="M3 8.5A2.5 2.5 0 0 1 5.5 6H7l1.6-2h6.8L17 6h1.5A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/><circle cx="12" cy="12.5" r="3.6"/>',
    "book": '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
}


def icon(name, size=20, stroke=1.9):
    return Markup(
        f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>'
    )


templates.env.globals["icon"] = icon
# Cache-buster for CSS/JS: changes whenever a static file changes (i.e. on upgrade).
templates.env.globals["static_v"] = str(
    int(max(p.stat().st_mtime for p in (config.BASE_DIR / "static").rglob("*") if p.is_file()))
)


def _user_households(db, user):
    return (
        db.query(Household)
        .join(Membership, Membership.household_id == Household.id)
        .filter(Membership.user_id == user.id)
        .order_by(Household.name)
        .all()
    )


def render(request: Request, name, context=None, status_code=200, db=None, membership=None, headers=None):
    ctx = dict(context or {})
    user = getattr(request.state, "user", None)
    ctx.setdefault("user", user)
    ctx.setdefault("csrf_token", getattr(request.state, "csrf_token", ""))
    if membership is not None:
        ctx.setdefault("membership", membership)
        ctx.setdefault("household", membership.household)
    if db is not None and user is not None:
        ctx.setdefault("user_households", _user_households(db, user))
        ctx.setdefault("pending_invite_count", db.query(Invite).filter_by(user_id=user.id).count())
    return templates.TemplateResponse(request, name, ctx, status_code=status_code, headers=headers)
