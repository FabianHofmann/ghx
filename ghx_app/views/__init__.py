from ghx_app.base import ListView, Shared
from ghx_app.views.ci import CiView
from ghx_app.views.combined import AllView
from ghx_app.views.comments import CommentsView
from ghx_app.views.issues import IssuesView
from ghx_app.views.notifications import NotificationsView
from ghx_app.views.prs import PrsView
from ghx_app.views.work import WorkView


def build_views(shared: Shared) -> list[ListView]:
    return [view(shared) for view in (AllView, PrsView, IssuesView, WorkView, CiView, CommentsView, NotificationsView)]
