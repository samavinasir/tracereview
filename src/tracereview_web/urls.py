from django.conf import settings
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path

from tracereview_web.research import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", LogoutView.as_view(next_page="home"), name="logout"),
    path("accounts/signup/", views.signup, name="signup"),
    path("settings/api-keys/", views.api_keys, name="api_keys"),
    path("", views.home, name="home"),
    path("health", views.health, name="health"),
    path("research", views.start_research, name="start_research"),
    path("research/<uuid:research_id>/results", views.research_workspace, {"page": "results"}, name="research_results"),
    path("research/<uuid:research_id>/run", views.research_workspace, {"page": "run"}, name="research_run_details"),
    path("research/<uuid:research_id>", views.read_research, name="read_research"),
    path("research/<uuid:research_id>/status", views.read_status, name="read_status"),
    path("research/<uuid:research_id>/plan", views.read_plan, name="read_plan"),
    path("research/<uuid:research_id>/sources", views.read_sources, name="read_sources"),
    path("research/<uuid:research_id>/sources/decision", views.review_source, name="review_source"),
    path("research/<uuid:research_id>/evidence", views.read_evidence, name="read_evidence"),
    path("research/<uuid:research_id>/claims", views.read_claims, name="read_claims"),
    path("research/<uuid:research_id>/audit", views.read_audit, name="read_audit"),
    path("research/<uuid:research_id>/report", views.read_report, name="read_report"),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
