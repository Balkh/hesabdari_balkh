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
    path("returns/", api_views.sales_return_collection, name="sales-return-collection"),
    path("returns/create/", api_views.sales_return_create, name="sales-return-create"),
    path("returns/<int:pk>/reverse/", api_views.sales_return_reverse, name="sales-return-reverse"),
    path("returns/<int:return_id>/refunds/", api_views.refund_create, name="sales-refund-create"),
    path("refunds/<int:pk>/reverse/", api_views.refund_reverse, name="sales-refund-reverse"),
]
