from django.conf import settings
from django.db import models


class ResearchRun(models.Model):
    """Read-only Django admin view over the existing SQLAlchemy-owned table."""

    id = models.UUIDField(primary_key=True)
    status = models.CharField(max_length=32)
    progress = models.JSONField()
    error = models.TextField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "research_runs"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.id} ({self.status})"


class ResearchRunOwner(models.Model):
    research_id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="research_runs")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class UserProviderCredentials(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="provider_credentials")
    encrypted_keys = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Provider keys for user {self.user_id}"
