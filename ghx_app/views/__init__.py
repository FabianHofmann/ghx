from ghx_app.base import ListView, Shared
from ghx_app.views.ci import CiView
from ghx_app.views.comments import CommentsView
from ghx_app.views.notifications import NotificationsView
from ghx_app.views.prs import PrsView


def build_views(shared: Shared) -> list[ListView]:
    return [PrsView(shared), CiView(shared), CommentsView(shared), NotificationsView(shared)]
