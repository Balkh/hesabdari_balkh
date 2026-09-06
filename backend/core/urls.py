from django.urls import path
from .views import health_check, missing_resource

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("health/missing/", missing_resource, name="missing-resource"),
]
