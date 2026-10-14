from django.urls import path

from . import api_views

urlpatterns = [
    path("", api_views.sale_collection, name="sale-collection"),
    path("<int:pk>/", api_views.sale_detail, name="sale-detail"),
    path("<int:pk>/finalize/", api_views.sale_finalize, name="sale-finalize"),
    path("warehouse-checks/", api_views.warehouse_check_collection, name="warehouse-check-collection"),
    path("warehouse-checks/<int:pk>/", api_views.warehouse_check_detail, name="warehouse-check-detail"),
    path("warehouse-checks/<int:pk>/finalize/", api_views.warehouse_check_finalize, name="warehouse-check-finalize"),
    path("warehouse-checks/<int:pk>/cancel/", api_views.warehouse_check_cancel, name="warehouse-check-cancel"),
]
